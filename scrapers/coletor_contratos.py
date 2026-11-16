"""
Motor de coleta de contratos públicos — FiscalizaObras-MS.

Fonte primária: API oficial de Consulta do PNCP (Lei 14.133/2021, art. 174)
    https://pncp.gov.br/api/consulta/swagger-ui/index.html

Fluxo otimizado (requisições paralelas com ThreadPoolExecutor):
  1. Descoberta dos órgãos municipais (esfera "M") de cada município, via
     /contratacoes/publicacao filtrada por UF=MS e código IBGE;
  2. Coleta dos contratos do exercício por CNPJ de órgão (/contratos), com
     paginação paralela;
  3. Classificação técnica (Engenharia/Agronomia/Geociências) ANTES do
     enriquecimento, para economizar requisições;
  4. Enriquecimento só dos contratos técnicos: arquivos (Contrato, OS,
     Empenho), termos aditivos (vigência/valor) e modalidade da compra;
  5. Portais da Transparência municipais com API de Dados Abertos (Fiorilli
     SCPI, 39 municípios) — consultados em paralelo e fundidos ao PNCP SEM
     duplicar: contratos já existentes no PNCP recebem valor empenhado,
     liquidado e saldo; contratos ausentes do PNCP são incluídos.

Regra de resiliência dos anexos: quando o documento não é localizado, o link
aponta para a página de detalhamento do contrato e o status do anexo indica
"Disponível na página do contrato" ou "Não publicado no portal".
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.regioes_ms import UF, Municipio
from utils.classificador_tecnico import AREA_NAO_TECNICA, classificar

log = logging.getLogger("fiscalizaobras.coletor")

PNCP_CONSULTA = "https://pncp.gov.br/api/consulta/v1"
PNCP_API = "https://pncp.gov.br/api/pncp/v1"
PNCP_APP = "https://pncp.gov.br/app"
BRASILAPI_CNPJ = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"

USER_AGENT = "FiscalizaObras-MS/1.0 (+painel de fiscalizacao; python-requests)"
TIMEOUT = (15, 90)  # (conexão, leitura) — a API de consulta do PNCP é lenta
TAMANHO_PAGINA = 500  # máximo aceito pelo endpoint /contratos
MAX_WORKERS = 8
MAX_ENRIQUECIMENTO = 400  # teto de contratos técnicos enriquecidos por consulta

# Modalidades usadas para descobrir órgãos (pregão eletr., dispensa,
# concorrência eletr./presencial, inexigibilidade)
MODALIDADES_DESCOBERTA = (6, 8, 4, 5, 9)

STATUS_DOC_OK = "Documento localizado"
STATUS_DOC_PAGINA = "Disponível na página do contrato"
STATUS_DOC_AUSENTE = "Não publicado no portal"

SITUACAO_VIGENTE = "Vigente / Em Execução"
SITUACAO_PARALISADO = "Paralisado / Suspenso"
SITUACAO_CONCLUIDO = "Concluído"
SITUACOES = ["Todos", SITUACAO_VIGENTE, SITUACAO_PARALISADO, SITUACAO_CONCLUIDO]

_local = threading.local()


# ---------------------------------------------------------------------------
# Infra HTTP
# ---------------------------------------------------------------------------
def _sessao() -> requests.Session:
    """Sessão HTTP por thread, com retry exponencial para falhas transitórias."""
    s = getattr(_local, "sessao", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9"})
        retry = Retry(
            total=5, connect=5, read=3, backoff_factor=1.2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}), respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=MAX_WORKERS * 2, pool_maxsize=MAX_WORKERS * 2)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _local.sessao = s
    return s


def _get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout=TIMEOUT) -> Any:
    """GET que devolve JSON ou ``None`` (204/404/corpo vazio/erro)."""
    try:
        r = _sessao().get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        log.warning("Falha de rede em %s: %s", url, exc)
        raise
    if r.status_code in (204, 404) or not r.content:
        return None
    if r.status_code >= 400:
        log.warning("HTTP %s em %s params=%s: %s", r.status_code, url, params, r.text[:200])
        r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return None


def _get_json_seguro(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    try:
        return _get_json(url, params)
    except requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# Utilidades de formatação
# ---------------------------------------------------------------------------
def so_digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def formatar_cnpj(valor: Any) -> str:
    d = so_digitos(valor)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return str(valor or "")


def _data(valor: Any) -> Optional[date]:
    if not valor:
        return None
    if isinstance(valor, date):
        return valor if not isinstance(valor, datetime) else valor.date()
    texto = str(valor).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def _num(valor: Any) -> Optional[float]:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).replace("R$", "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)).lower()


# ---------------------------------------------------------------------------
# Cliente PNCP
# ---------------------------------------------------------------------------
@dataclass
class OrgaoMunicipal:
    cnpj: str
    razao_social: str
    municipio: str


class ClientePNCP:
    """Acesso à API de Consulta do PNCP."""

    def descobrir_orgaos(self, mun: Municipio, exercicio: int) -> List[OrgaoMunicipal]:
        """Órgãos da esfera municipal com publicações no município/exercício."""
        ini, fim = _periodo(exercicio)
        orgaos: Dict[str, OrgaoMunicipal] = {}
        if mun.cnpj_prefeitura:
            orgaos[so_digitos(mun.cnpj_prefeitura)] = OrgaoMunicipal(
                so_digitos(mun.cnpj_prefeitura), f"MUNICÍPIO DE {mun.nome}", mun.nome
            )

        def consulta(modalidade: int):
            return _get_json_seguro(
                f"{PNCP_CONSULTA}/contratacoes/publicacao",
                dict(dataInicial=ini, dataFinal=fim, codigoModalidadeContratacao=modalidade,
                     uf=UF, codigoMunicipioIbge=mun.codigo_ibge, pagina=1, tamanhoPagina=50),
            )

        with ThreadPoolExecutor(max_workers=len(MODALIDADES_DESCOBERTA)) as ex:
            for resp in ex.map(consulta, MODALIDADES_DESCOBERTA):
                for item in (resp or {}).get("data", []) or []:
                    org = item.get("orgaoEntidade") or {}
                    uni = item.get("unidadeOrgao") or {}
                    if org.get("esferaId") != "M":
                        continue
                    if str(uni.get("codigoIbge", "")) not in ("", mun.codigo_ibge):
                        continue
                    cnpj = so_digitos(org.get("cnpj"))
                    if cnpj and cnpj not in orgaos:
                        orgaos[cnpj] = OrgaoMunicipal(cnpj, org.get("razaoSocial", ""), mun.nome)
        return list(orgaos.values())

    def contratos_do_orgao(self, cnpj: str, exercicio: int) -> List[Dict[str, Any]]:
        """Todos os contratos publicados pelo órgão no exercício (paginação paralela)."""
        ini, fim = _periodo(exercicio)
        base = dict(dataInicial=ini, dataFinal=fim, cnpjOrgao=cnpj, tamanhoPagina=TAMANHO_PAGINA)
        primeira = _get_json(f"{PNCP_CONSULTA}/contratos", {**base, "pagina": 1}) or {}
        dados = list(primeira.get("data") or [])
        total_paginas = int(primeira.get("totalPaginas") or 1)
        if total_paginas > 1:
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, total_paginas - 1)) as ex:
                futuros = [ex.submit(_get_json_seguro, f"{PNCP_CONSULTA}/contratos", {**base, "pagina": p})
                           for p in range(2, total_paginas + 1)]
                for fut in as_completed(futuros):
                    dados.extend((fut.result() or {}).get("data") or [])
        return dados

    def arquivos(self, cnpj: str, ano: int, seq: int) -> List[Dict[str, Any]]:
        return _get_json_seguro(f"{PNCP_API}/orgaos/{cnpj}/contratos/{ano}/{seq}/arquivos") or []

    def termos(self, cnpj: str, ano: int, seq: int) -> List[Dict[str, Any]]:
        return _get_json_seguro(f"{PNCP_API}/orgaos/{cnpj}/contratos/{ano}/{seq}/termos") or []

    def compra(self, numero_controle_compra: str) -> Optional[Dict[str, Any]]:
        m = re.match(r"(\d{14})-\d-(\d+)/(\d{4})", numero_controle_compra or "")
        if not m:
            return None
        cnpj, seq, ano = m.group(1), int(m.group(2)), m.group(3)
        return _get_json_seguro(f"{PNCP_CONSULTA}/orgaos/{cnpj}/compras/{ano}/{seq}")


def _periodo(exercicio: int) -> Tuple[str, str]:
    hoje = date.today()
    fim = date(exercicio, 12, 31)
    if fim > hoje and exercicio == hoje.year:
        fim = hoje
    return f"{exercicio}0101", fim.strftime("%Y%m%d")


def url_pagina_pncp(cnpj: str, ano: Any, seq: Any) -> str:
    return f"{PNCP_APP}/contratos/{cnpj}/{ano}/{seq}"


# ---------------------------------------------------------------------------
# Normalização do contrato PNCP para o modelo do painel
# ---------------------------------------------------------------------------
_RE_PARALISACAO = re.compile(r"paralisa|suspens|interrup", re.I)
_RE_OS = re.compile(r"ordem\s*(de)?\s*servi|\bo\.?\s?s\.?\b|autoriza\w*\s+(de\s+)?inicio", re.I)
_RE_EMPENHO = re.compile(r"empenho|\bn\.?\s?e\.?\b|nota\s+de\s+empenho", re.I)
_RE_CONTRATO = re.compile(r"contrato|instrumento", re.I)


def _situacao(vig_ini: Optional[date], vig_fim: Optional[date], textos: Iterable[str]) -> str:
    if any(_RE_PARALISACAO.search(_sem_acento(t or "")) for t in textos):
        return SITUACAO_PARALISADO
    hoje = date.today()
    if vig_fim and vig_fim < hoje:
        return SITUACAO_CONCLUIDO
    return SITUACAO_VIGENTE


def normalizar_contrato_pncp(bruto: Dict[str, Any], mun: Municipio) -> Dict[str, Any]:
    org = bruto.get("orgaoEntidade") or {}
    cnpj_org = so_digitos(org.get("cnpj"))
    ano, seq = bruto.get("anoContrato"), bruto.get("sequencialContrato")
    categoria = (bruto.get("categoriaProcesso") or {}).get("nome")
    objeto = (bruto.get("objetoContrato") or "").strip()
    vig_ini, vig_fim = _data(bruto.get("dataVigenciaInicio")), _data(bruto.get("dataVigenciaFim"))
    cls = classificar(objeto, categoria)
    url_pag = url_pagina_pncp(cnpj_org, ano, seq)
    numero = str(bruto.get("numeroContratoEmpenho") or seq or "").strip()
    return {
        "id": bruto.get("numeroControlePNCP") or f"{cnpj_org}-{ano}-{seq}",
        "municipio": mun.nome,
        "codigo_ibge": mun.codigo_ibge,
        "regiao": mun.rotulo_regiao,
        "orgao": org.get("razaoSocial", ""),
        "cnpj_orgao": formatar_cnpj(cnpj_org),
        "_cnpj_orgao": cnpj_org,
        "_ano": ano,
        "_seq": seq,
        "numero_contrato": f"{numero}/{ano}" if ano and "/" not in numero else numero,
        "tipo_instrumento": (bruto.get("tipoContrato") or {}).get("nome", ""),
        "processo": bruto.get("processo") or "",
        "modalidade": "",
        "categoria_pncp": categoria or "",
        "fornecedor": (bruto.get("nomeRazaoSocialFornecedor") or "").strip(),
        "cnpj_fornecedor": formatar_cnpj(bruto.get("niFornecedor")),
        "_ni_fornecedor": so_digitos(bruto.get("niFornecedor")),
        "objeto": objeto,
        "informacao_complementar": bruto.get("informacaoComplementar") or "",
        "valor_global": _num(bruto.get("valorGlobal")) or _num(bruto.get("valorInicial")) or 0.0,
        "valor_empenhado": None,
        "saldo_a_empenhar": None,
        "data_assinatura": _data(bruto.get("dataAssinatura")),
        "vigencia_inicio": vig_ini,
        "vigencia_fim": vig_fim,
        "situacao": _situacao(vig_ini, vig_fim, [objeto, bruto.get("informacaoComplementar") or ""]),
        "area": cls.area,
        "areas_secundarias": cls.areas_secundarias,
        "pontuacao_tecnica": cls.pontuacao,
        "motivo_classificacao": cls.motivo,
        "fonte": "PNCP",
        "numero_controle_pncp": bruto.get("numeroControlePNCP") or "",
        "_controle_compra": bruto.get("numeroControlePncpCompra") or "",
        "url_pagina": url_pag,
        "url_portal_municipal": mun.url_portal,
        "url_contrato": url_pag, "status_contrato": STATUS_DOC_PAGINA,
        "url_os": url_pag, "status_os": STATUS_DOC_PAGINA,
        "url_empenho": url_pag, "status_empenho": STATUS_DOC_PAGINA,
        "empenhos": [],
        "termos_aditivos": [],
        "documentos": [],
    }


def _classificar_documento(doc: Dict[str, Any]) -> Optional[str]:
    tipo = _sem_acento(doc.get("tipoDocumentoNome") or "")
    titulo = _sem_acento(doc.get("titulo") or "")
    texto = f"{tipo} {titulo}"
    if _RE_OS.search(titulo) or "ordem de servico" in texto:
        return "os"
    if _RE_EMPENHO.search(texto):
        return "empenho"
    if tipo.startswith("contrato") or _RE_CONTRATO.search(titulo):
        return "contrato"
    return None


def enriquecer_contrato(c: Dict[str, Any], cliente: ClientePNCP) -> Dict[str, Any]:
    """Busca anexos, termos aditivos e modalidade da compra (PNCP)."""
    cnpj, ano, seq = c["_cnpj_orgao"], c["_ano"], c["_seq"]
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_arq = ex.submit(cliente.arquivos, cnpj, ano, seq)
        f_ter = ex.submit(cliente.termos, cnpj, ano, seq)
        f_cmp = ex.submit(cliente.compra, c["_controle_compra"])
        arquivos, termos, compra = f_arq.result(), f_ter.result(), f_cmp.result()

    achados: Dict[str, List[Dict[str, Any]]] = {"contrato": [], "os": [], "empenho": []}
    for doc in arquivos or []:
        url = doc.get("url") or doc.get("uri")
        if not url:
            continue
        tipo = _classificar_documento(doc)
        c["documentos"].append({"titulo": doc.get("titulo"), "tipo": doc.get("tipoDocumentoNome"), "url": url})
        if tipo:
            achados[tipo].append({"titulo": doc.get("titulo"), "url": url})

    tem_anexos = bool(c["documentos"])
    for chave in ("contrato", "os", "empenho"):
        if achados[chave]:
            c[f"url_{chave}"] = achados[chave][0]["url"]
            c[f"status_{chave}"] = STATUS_DOC_OK
        elif c.get(f"status_{chave}") not in (STATUS_DOC_OK, STATUS_DOC_PORTAL):  # preserva dado do portal
            c[f"url_{chave}"] = c["url_pagina"]
            c[f"status_{chave}"] = STATUS_DOC_PAGINA if tem_anexos else STATUS_DOC_AUSENTE
    if achados["empenho"]:
        c["empenhos"].extend({"descricao": d["titulo"], "url": d["url"], "valor": None} for d in achados["empenho"])

    # Termos aditivos: prorrogação de vigência, acréscimos e indícios de paralisação
    textos_termos = []
    for t in termos or []:
        textos_termos.append(t.get("objetoTermoContrato") or "")
        c["termos_aditivos"].append({
            "numero": t.get("numeroTermoContrato"),
            "assinatura": _data(t.get("dataAssinatura")),
            "objeto": (t.get("objetoTermoContrato") or "")[:500],
            "valor_acrescido": _num(t.get("valorAcrescido")),
            "nova_vigencia_fim": _data(t.get("dataVigenciaFim")),
        })
        nova_fim = _data(t.get("dataVigenciaFim"))
        if nova_fim and (c["vigencia_fim"] is None or nova_fim > c["vigencia_fim"]):
            c["vigencia_fim"] = nova_fim
        if t.get("valorGlobal"):
            c["valor_global"] = _num(t.get("valorGlobal")) or c["valor_global"]
    c["situacao"] = _situacao(c["vigencia_inicio"], c["vigencia_fim"],
                              [c["objeto"], c["informacao_complementar"], *textos_termos])

    if compra:
        c["modalidade"] = compra.get("modalidadeNome") or ""
        num_compra = compra.get("numeroCompra")
        ano_compra = compra.get("anoCompra")
        if not c["processo"]:
            c["processo"] = compra.get("processo") or ""
        if num_compra:
            c["processo"] = f"{c['processo']} (Licitação {num_compra}/{ano_compra})".strip()
    return c


def vincular_empenhos(tecnicos: List[Dict[str, Any]], todos: List[Dict[str, Any]]) -> None:
    """Liga registros PNCP do tipo 'Empenho' ao contrato da mesma compra/fornecedor."""
    idx: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for c in todos:
        if _sem_acento(c.get("tipo_instrumento")).startswith("empenho") and c["_controle_compra"]:
            idx.setdefault((c["_controle_compra"], c["_ni_fornecedor"]), []).append(c)
    for c in tecnicos:
        if _sem_acento(c.get("tipo_instrumento")).startswith("empenho"):
            if c.get("valor_empenhado") is None:
                c["valor_empenhado"] = c["valor_global"]
            c["url_empenho"], c["status_empenho"] = c["url_pagina"], STATUS_DOC_OK
            continue
        emps = idx.get((c["_controle_compra"], c["_ni_fornecedor"]), [])
        if emps:
            c["empenhos"].extend({"descricao": f"Empenho {e['numero_contrato']}", "url": e["url_pagina"],
                                  "valor": e["valor_global"]} for e in emps)
            if c.get("valor_empenhado") is None:
                c["valor_empenhado"] = sum(e["valor_global"] or 0 for e in emps)
            if c["status_empenho"] != STATUS_DOC_OK:
                c["url_empenho"], c["status_empenho"] = emps[0]["url_pagina"], STATUS_DOC_OK


def enriquecer_cnae(contratos: List[Dict[str, Any]]) -> None:
    """(Opcional) Busca o CNAE fiscal da contratada na BrasilAPI e reclassifica."""
    cnpjs = {c["_ni_fornecedor"] for c in contratos if len(c["_ni_fornecedor"]) == 14}

    def busca(cnpj: str):
        dados = _get_json_seguro(BRASILAPI_CNPJ.format(cnpj=cnpj))
        return cnpj, (dados or {}).get("cnae_fiscal"), (dados or {}).get("cnae_fiscal_descricao")

    cnaes: Dict[str, Tuple[Any, Any]] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for cnpj, cod, desc in ex.map(busca, cnpjs):
            cnaes[cnpj] = (cod, desc)
    for c in contratos:
        cod, desc = cnaes.get(c["_ni_fornecedor"], (None, None))
        if cod:
            c["cnae_fornecedor"] = f"{cod} - {desc}" if desc else str(cod)
            cls = classificar(c["objeto"], c["categoria_pncp"], str(cod))
            c.update(area=cls.area, areas_secundarias=cls.areas_secundarias,
                     pontuacao_tecnica=cls.pontuacao, motivo_classificacao=cls.motivo)


# ---------------------------------------------------------------------------
# Portais da Transparência municipais — Fiorilli SCPI (API de Dados Abertos)
# ---------------------------------------------------------------------------
# Endpoint oficial documentado em <portal>/versaoJson/DadosAbertos/:
#   GET /VersaoJson/LicitacoesEContratos/?ConectarExercicio={ano}&Listagem=Contratos
#       &Ano={ano}&Empresa=1&MostraDadosConsolidado=True&ContratosApenasPublicados=False
# Validado com dados reais (Corumbá e Ivinhema, 2026). Traz valor empenhado,
# liquidado e saldo a empenhar — informação que o PNCP normalmente não tem.
STATUS_DOC_PORTAL = "Disponível no Portal da Transparência"
FONTE_FIORILLI = "Portal Fiorilli (SCPI)"
TIMEOUT_PORTAL = (10, 120)


def _sessao_portal() -> requests.Session:
    """Sessão para portais municipais: poucas tentativas (servidores podem estar fora do ar)."""
    s = getattr(_local, "sessao_portal", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        retry = Retry(total=2, connect=1, read=1, backoff_factor=1.5, status_forcelist=(502, 503, 504),
                      allowed_methods=frozenset({"GET"}))
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _local.sessao_portal = s
    return s


def base_api_fiorilli(url_portal: str) -> Optional[str]:
    """'http://host:8079/transparencia/Default.aspx' -> 'http://host:8079/transparencia'."""
    m = re.match(r"(https?://[^/]+/transparencia)", url_portal or "", re.I)
    return m.group(1) if m else None


def _cnpj_ou_cpf(valor: Any) -> str:
    d = so_digitos(valor)
    return d if len(d) in (11, 14) else ""


def normalizar_contrato_fiorilli(reg: Dict[str, Any], mun: Municipio) -> Dict[str, Any]:
    """Converte um registro da listagem 'Contratos' do SCPI para o modelo do painel."""
    ano = int(so_digitos(reg.get("ANO")) or 0) or None
    num = so_digitos(reg.get("CONTRATONUM")).lstrip("0")
    codigo = str(reg.get("CODIGO") or "").strip()
    objeto = (reg.get("OBJETO_COMPLETO") or reg.get("OBJETO") or "").strip()
    modalidade = (reg.get("LICIT") or reg.get("MODALI") or "").strip()
    eh_obra = bool(str(reg.get("TIPOCOOBRA") or "").strip() or str(reg.get("NUMOBRA") or "").strip()
                   or "OBRA" in str(reg.get("MODALI") or "").upper())
    categoria = "Obras" if eh_obra else ""
    cls = classificar(objeto, categoria)
    vig_ini = _data(reg.get("VIGENI"))
    vig_fim = _data(reg.get("VENCIMENTO_ATUAL")) or _data(reg.get("VIGENF"))
    empenhado = sum(v for v in (_num(reg.get("EMPENHADOANT")), _num(reg.get("EMPENHADO"))) if v is not None)
    tem_empenho = any(_num(reg.get(k)) is not None for k in ("EMPENHADOANT", "EMPENHADO"))
    liquidado = sum(v for v in (_num(reg.get("LIQUIDADOANT")), _num(reg.get("LIQUIDADO"))) if v is not None)
    saldo = _num(reg.get("SALDOEMPENHAR"))
    situacao = SITUACAO_CONCLUIDO if _data(reg.get("DTENCERRAMENTO")) else _situacao(vig_ini, vig_fim, [objeto])
    processo = str(reg.get("PROCLIC") or "").strip()
    if reg.get("NUMLICMOD"):
        processo = f"{processo} (Licitação {reg['NUMLICMOD']})".strip()
    base = mun.url_portal
    return {
        "id": f"FIORILLI-{mun.codigo_ibge}-{reg.get('EMPRESA') or 0}-{codigo}-{ano}",
        "municipio": mun.nome,
        "codigo_ibge": mun.codigo_ibge,
        "regiao": mun.rotulo_regiao,
        "orgao": (reg.get("ENTIDADE") or "").strip(),
        "cnpj_orgao": "",
        "_cnpj_orgao": "",
        "_ano": ano,
        "_seq": None,
        "_num_portal": num,
        "_codigo_portal": so_digitos(codigo.split("/")[0]).lstrip("0"),
        "numero_contrato": f"{num}/{ano}" if num and ano else codigo,
        "tipo_instrumento": "Contrato",
        "processo": processo,
        "modalidade": modalidade.title(),
        "categoria_pncp": categoria,
        "fornecedor": (reg.get("FORNECEDOR") or "").strip(),
        "cnpj_fornecedor": formatar_cnpj(reg.get("INSMF")),
        "_ni_fornecedor": _cnpj_ou_cpf(reg.get("INSMF")),
        "objeto": objeto,
        "informacao_complementar": "",
        "valor_global": _num(reg.get("VALCON")) or 0.0,
        "valor_aditado": _num(reg.get("ADITADO")),
        "valor_empenhado": empenhado if tem_empenho else None,
        "valor_liquidado": liquidado if tem_empenho else None,
        "saldo_a_empenhar": saldo,
        "data_assinatura": _data(reg.get("DTASSI")),
        "vigencia_inicio": vig_ini,
        "vigencia_fim": vig_fim,
        "situacao": situacao,
        "area": cls.area,
        "areas_secundarias": cls.areas_secundarias,
        "pontuacao_tecnica": cls.pontuacao,
        "motivo_classificacao": cls.motivo,
        "fonte": FONTE_FIORILLI,
        "numero_controle_pncp": "",
        "_controle_compra": "",
        "url_pagina": base,
        "url_portal_municipal": base,
        "url_contrato": base, "status_contrato": STATUS_DOC_PORTAL,
        "url_os": base, "status_os": STATUS_DOC_PORTAL,
        "url_empenho": base, "status_empenho": STATUS_DOC_PORTAL,
        "empenhos": [],
        "termos_aditivos": [],
        "documentos": [],
    }


class ConectorFiorilli:
    """Lê a listagem de contratos da API de Dados Abertos do Fiorilli SCPI."""

    sistema = "FIORILLI"

    def __init__(self, mun: Municipio):
        self.mun = mun
        self.base = base_api_fiorilli(mun.url_portal)

    def buscar_contratos(self, exercicio: int) -> List[Dict[str, Any]]:
        if not self.base:
            return []
        params = {"ConectarExercicio": exercicio, "Listagem": "Contratos", "Ano": exercicio, "Empresa": 1,
                  "MostraDadosConsolidado": "True", "ContratosApenasPublicados": "False"}
        r = _sessao_portal().get(f"{self.base}/VersaoJson/LicitacoesEContratos/", params=params,
                                 timeout=TIMEOUT_PORTAL)
        r.raise_for_status()
        dados = r.json() if r.content else []
        if isinstance(dados, dict):
            dados = next((v for v in dados.values() if isinstance(v, list)), [])
        saida, vistos = [], set()
        for reg in dados or []:
            if not isinstance(reg, dict) or str(reg.get("DTANULA") or "").strip():
                continue  # anulados ficam de fora
            if so_digitos(reg.get("ANO")) != str(exercicio):
                continue
            chave = (reg.get("EMPRESA"), reg.get("CODIGO"), reg.get("ANO"))
            if chave in vistos:  # duplicidade dentro do próprio portal
                continue
            vistos.add(chave)
            saida.append(normalizar_contrato_fiorilli(reg, self.mun))
        return saida


CONECTORES = {"FIORILLI": ConectorFiorilli}


def _mesmo_numero(portal: Dict[str, Any], c: Dict[str, Any]) -> bool:
    num_c = so_digitos(str(c.get("numero_contrato", "")).split("/")[0]).lstrip("0")
    return bool(num_c) and num_c in {portal.get("_num_portal"), portal.get("_codigo_portal")} - {""}


def _mesmo_valor(a: Optional[float], b: Optional[float]) -> bool:
    if not a or not b:
        return False
    return abs(a - b) <= max(1.0, 0.01 * max(a, b))


def _pontuar_par(portal: Dict[str, Any], c: Dict[str, Any]) -> int:
    pts = 0
    if _mesmo_numero(portal, c):
        pts += 3
    if _mesmo_valor(portal["valor_global"], c.get("valor_global")):
        pts += 2
    if portal["data_assinatura"] and portal["data_assinatura"] == c.get("data_assinatura"):
        pts += 1
    return pts


def _fundir(c: Dict[str, Any], p: Dict[str, Any]) -> None:
    """Complementa o contrato do PNCP com os dados financeiros do portal municipal."""
    for campo in ("valor_empenhado", "valor_liquidado", "saldo_a_empenhar", "valor_aditado"):
        if p.get(campo) is not None:
            c[campo] = p[campo]
    if not c.get("modalidade"):
        c["modalidade"] = p["modalidade"]
    if p["situacao"] == SITUACAO_CONCLUIDO and c["situacao"] == SITUACAO_VIGENTE:
        c["situacao"] = SITUACAO_CONCLUIDO
    if c.get("status_empenho") != STATUS_DOC_OK:
        c["url_empenho"], c["status_empenho"] = p["url_portal_municipal"], STATUS_DOC_PORTAL
    c["url_portal_municipal"] = p["url_portal_municipal"]
    c["numero_contrato_portal"] = p["numero_contrato"]
    c["fonte"] = f"PNCP + {FONTE_FIORILLI}"


def mesclar_portal(todos: List[Dict[str, Any]], registros: List[Dict[str, Any]], mun: Municipio) -> Tuple[int, int, int]:
    """Funde registros do portal com os do PNCP SEM duplicar.

    Regra (validada com dados reais): mesmo município + mesmo CNPJ/CPF da contratada
    + pelo menos um entre nº do contrato, valor global (±1%) ou data de assinatura.
    - casou com contrato PNCP ainda livre  -> complementa o registro PNCP (não cria novo);
    - casou só com contrato PNCP já usado  -> duplicidade, descartado;
    - não casou                           -> contrato ausente no PNCP, incluído com fonte do portal.
    Retorna (vinculados, novos, descartados_por_duplicidade).
    """
    candidatos: Dict[str, List[Dict[str, Any]]] = {}
    for c in todos:
        if c["municipio"] == mun.nome and c["fonte"].startswith("PNCP") and c.get("_ni_fornecedor"):
            candidatos.setdefault(c["_ni_fornecedor"], []).append(c)
    usados: set = set()
    vinculados = novos = descartados = 0
    for p in registros:
        melhor, melhor_pts, ja_usado = None, 0, False
        for c in candidatos.get(p["_ni_fornecedor"], []) if p["_ni_fornecedor"] else []:
            pts = _pontuar_par(p, c)
            if pts == 0:
                continue
            if c["id"] in usados:
                ja_usado = ja_usado or pts >= 3
                continue
            if pts > melhor_pts:
                melhor, melhor_pts = c, pts
        if melhor is not None:
            _fundir(melhor, p)
            usados.add(melhor["id"])
            vinculados += 1
        elif ja_usado:
            descartados += 1
        else:
            todos.append(p)
            novos += 1
    return vinculados, novos, descartados


def deduplicar(contratos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove publicações duplicadas do mesmo contrato no PNCP.

    Há publicações repetidas do mesmo instrumento (ex.: "000064/2026" e "64/2026",
    ou o mesmo contrato publicado pela Prefeitura e pelo Fundo Municipal), o que
    inflaria os totais. Chave: município + nº normalizado + contratada + valor +
    data de assinatura. Mantém o de maior sequencial (publicação mais recente).
    """
    escolhidos: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for c in contratos:
        num = so_digitos(c["numero_contrato"].split("/")[0]).lstrip("0")
        # sem o CNPJ do órgão: o mesmo contrato às vezes é publicado pela Prefeitura E pelo Fundo
        chave = (c["municipio"], num, c["_ano"], c["_ni_fornecedor"], round(c["valor_global"] or 0, 2),
                 c["data_assinatura"], _sem_acento(c["tipo_instrumento"])[:8])
        atual = escolhidos.get(chave)
        if atual is None or (c["_seq"] or 0) > (atual["_seq"] or 0):
            escolhidos[chave] = c
    return list(escolhidos.values())


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
@dataclass
class ResultadoColeta:
    contratos: List[Dict[str, Any]] = field(default_factory=list)
    total_bruto: int = 0
    orgaos: List[OrgaoMunicipal] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)
    municipios_sem_orgao: List[str] = field(default_factory=list)  # sem dados no PNCP nem no portal
    total_portal: int = 0


Progresso = Callable[[float, str], None]


def coletar_contratos(
    municipios: List[Municipio],
    exercicio: int,
    incluir_nao_tecnicos: bool = False,
    enriquecer_cnae_fornecedor: bool = False,
    progresso: Optional[Progresso] = None,
) -> ResultadoColeta:
    """Coleta (PNCP + portais municipais), deduplica, classifica e enriquece os contratos."""
    prog = progresso or (lambda f, m: None)
    cliente = ClientePNCP()
    res = ResultadoColeta()
    municipios = list({m.nome: m for m in municipios}.values())  # sem município repetido

    # 0) Portais municipais com API (em paralelo ao PNCP) -------------------
    ex_portais = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    fut_portais = {
        ex_portais.submit(CONECTORES[m.sistema](m).buscar_contratos, exercicio): m
        for m in municipios if m.sistema in CONECTORES
    }

    try:
        # 1) Descoberta de órgãos municipais no PNCP ------------------------
        prog(0.02, f"Descobrindo órgãos municipais em {len(municipios)} município(s)…")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futuros = {ex.submit(cliente.descobrir_orgaos, m, exercicio): m for m in municipios}
            for fut in as_completed(futuros):
                m = futuros[fut]
                try:
                    res.orgaos.extend(fut.result())
                except Exception as exc:  # noqa: BLE001
                    res.avisos.append(f"{m.nome}: falha na descoberta de órgãos no PNCP ({exc}).")

        # 2) Contratos por órgão --------------------------------------------
        por_nome = {m.nome: m for m in municipios}
        brutos: List[Tuple[Dict[str, Any], Municipio]] = []
        total = max(len(res.orgaos), 1)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futuros = {ex.submit(cliente.contratos_do_orgao, o.cnpj, exercicio): o for o in res.orgaos}
            for i, fut in enumerate(as_completed(futuros), 1):
                o = futuros[fut]
                prog(0.05 + 0.5 * i / total, f"PNCP: contratos de {o.razao_social[:45]} ({i}/{total})")
                try:
                    itens = fut.result()
                except Exception as exc:  # noqa: BLE001
                    res.avisos.append(f"{o.razao_social}: não foi possível ler os contratos no PNCP ({exc}).")
                    continue
                for b in itens:
                    brutos.append((b, por_nome[o.municipio]))
        res.total_bruto = len(brutos)

        # 3) Normalização + filtro do exercício + deduplicação PNCP ---------
        vistos = set()
        todos: List[Dict[str, Any]] = []
        for b, m in brutos:
            c = normalizar_contrato_pncp(b, m)
            if c["id"] in vistos:
                continue
            vistos.add(c["id"])
            ano_ass = c["data_assinatura"].year if c["data_assinatura"] else None
            if c["_ano"] != exercicio and ano_ass != exercicio:
                continue
            todos.append(c)
        todos = deduplicar(todos)

        # 4) Fusão com os portais municipais (sem duplicar) -----------------
        n_fut = max(len(fut_portais), 1)
        for i, fut in enumerate(as_completed(fut_portais), 1):
            m = fut_portais[fut]
            prog(0.56 + 0.04 * i / n_fut, f"Portal da Transparência de {m.nome.title()} ({i}/{len(fut_portais)})")
            try:
                regs = fut.result()
            except Exception as exc:  # noqa: BLE001
                res.avisos.append(f"{m.nome.title()}: portal da transparência indisponível agora "
                                  f"({type(exc).__name__}); mantidos apenas os dados do PNCP.")
                continue
            vinc, novos, desc = mesclar_portal(todos, regs, m)
            res.total_portal += len(regs)
            res.avisos.append(f"{m.nome.title()} (Fiorilli): {len(regs)} contrato(s) no portal — {vinc} já "
                              f"no PNCP (complementados), {novos} incluído(s) só do portal"
                              + (f", {desc} duplicado(s) descartado(s)." if desc else "."))
    finally:
        ex_portais.shutdown(wait=False, cancel_futures=True)

    com_dados = {c["municipio"] for c in todos}
    res.municipios_sem_orgao = sorted(m.nome for m in municipios if m.nome not in com_dados)

    tecnicos = [c for c in todos if incluir_nao_tecnicos or c["area"] != AREA_NAO_TECNICA]
    tecnicos.sort(key=lambda c: c["valor_global"] or 0, reverse=True)

    # 5) Enriquecimento PNCP (anexos, termos, modalidade) -------------------
    alvo = [c for c in tecnicos if c.get("_cnpj_orgao")][:MAX_ENRIQUECIMENTO]
    if len([c for c in tecnicos if c.get("_cnpj_orgao")]) > MAX_ENRIQUECIMENTO:
        res.avisos.append(f"Anexos do PNCP buscados para os {MAX_ENRIQUECIMENTO} contratos de maior valor "
                          f"(demais com link para a página do contrato).")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futuros = [ex.submit(enriquecer_contrato, c, cliente) for c in alvo]
        for i, fut in enumerate(as_completed(futuros), 1):
            if i % 5 == 0 or i == len(alvo):
                prog(0.6 + 0.3 * i / max(len(alvo), 1), f"Buscando Contrato/OS/Empenho ({i}/{len(alvo)})")
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("Falha ao enriquecer contrato: %s", exc)
    vincular_empenhos(tecnicos, todos)

    if enriquecer_cnae_fornecedor and tecnicos:
        prog(0.95, "Consultando CNAE das contratadas (BrasilAPI)…")
        enriquecer_cnae(tecnicos)
        if not incluir_nao_tecnicos:
            tecnicos = [c for c in tecnicos if c["area"] != AREA_NAO_TECNICA]

    for c in tecnicos:
        if c.get("saldo_a_empenhar") is None and c.get("valor_empenhado") is not None:
            c["saldo_a_empenhar"] = max((c["valor_global"] or 0) - c["valor_empenhado"], 0.0)

    res.contratos = tecnicos
    prog(1.0, f"Concluído: {len(tecnicos)} contrato(s) técnico(s).")
    return res


__all__ = [
    "ClientePNCP", "ResultadoColeta", "coletar_contratos", "formatar_cnpj", "SITUACOES",
    "SITUACAO_VIGENTE", "SITUACAO_PARALISADO", "SITUACAO_CONCLUIDO", "STATUS_DOC_OK", "STATUS_DOC_PAGINA",
    "STATUS_DOC_AUSENTE", "STATUS_DOC_PORTAL", "CONECTORES", "ConectorFiorilli", "mesclar_portal",
]
