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
  5. Conectores municipais (Betha, Fiorilli, Elotech, IPM, GovBR, Coplan)
     complementam valores empenhados e links quando o município está
     configurado em ``config.regioes_ms.PORTAIS_CONFIRMADOS``.

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

from config.regioes_ms import UF, Municipio, normalizar_nome
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
        else:
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
            c["valor_empenhado"] = c["valor_global"]
            c["url_empenho"], c["status_empenho"] = c["url_pagina"], STATUS_DOC_OK
            continue
        emps = idx.get((c["_controle_compra"], c["_ni_fornecedor"]), [])
        if emps:
            c["empenhos"].extend({"descricao": f"Empenho {e['numero_contrato']}", "url": e["url_pagina"],
                                  "valor": e["valor_global"]} for e in emps)
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
# Conectores dos sistemas de transparência municipais
# ---------------------------------------------------------------------------
_CHAVES = {
    "numero": ("numero", "nrcontrato", "numerocontrato", "contrato", "nr"),
    "fornecedor": ("fornecedor", "contratado", "credor", "razaosocial", "nomefornecedor", "empresa"),
    "cnpj": ("cnpj", "cpfcnpj", "cnpjcpf", "documento", "nicredor"),
    "objeto": ("objeto", "descricao", "historico", "finalidade"),
    "valor_global": ("valor", "valorcontrato", "valorglobal", "valortotal"),
    "valor_empenhado": ("empenhado", "valorempenhado", "totalempenhado"),
    "assinatura": ("assinatura", "dataassinatura", "data"),
    "url": ("url", "link", "arquivo", "anexo"),
}


def _chave_norm(k: str) -> str:
    return re.sub(r"[^a-z]", "", _sem_acento(k))


def mapear_registro_generico(reg: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia um registro de qualquer portal (JSON ou linha de tabela) para campos padrão."""
    norm = {_chave_norm(k): v for k, v in reg.items()}
    saida: Dict[str, Any] = {}
    for campo, candidatos in _CHAVES.items():
        for cand in candidatos:
            hit = next((v for k, v in norm.items() if k == cand), None)
            if hit is None:
                hit = next((v for k, v in norm.items() if cand in k), None)
            if hit not in (None, ""):
                saida[campo] = hit
                break
    return saida


class ConectorMunicipal:
    """Base dos conectores. Cada sistema implementa ``buscar_contratos``.

    Os conectores são *best-effort*: endereços e formatos variam por
    prefeitura/versão do sistema. Qualquer falha devolve lista vazia e o
    painel segue apenas com o PNCP.
    """

    sistema = "GENERICO"
    caminhos_html: Tuple[str, ...] = ("contratos", "transparencia/contratos")

    def __init__(self, mun: Municipio):
        self.mun = mun
        self.base = mun.url_portal.rstrip("/")

    def buscar_contratos(self, exercicio: int) -> List[Dict[str, Any]]:
        for caminho in self.caminhos_html:
            regs = self._raspar_tabela(f"{self.base}/{caminho}", {"exercicio": exercicio, "ano": exercicio})
            if regs:
                return regs
        return []

    def link_detalhe(self, numero: str = "") -> str:
        return self.mun.url_portal

    def _raspar_tabela(self, url: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        from bs4 import BeautifulSoup  # import tardio

        try:
            r = _sessao().get(url, params=params, timeout=(10, 40))
            if r.status_code >= 400 or "html" not in r.headers.get("Content-Type", "html"):
                return []
        except requests.RequestException:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        regs: List[Dict[str, Any]] = []
        for tabela in soup.find_all("table"):
            cab = [th.get_text(" ", strip=True) for th in tabela.find_all("th")]
            if not cab or not any("contrat" in _sem_acento(h) or "objeto" in _sem_acento(h) for h in cab):
                continue
            for tr in tabela.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                linha = {cab[i] if i < len(cab) else f"col{i}": td.get_text(" ", strip=True) for i, td in enumerate(tds)}
                link = tr.find("a", href=True)
                if link:
                    linha["url"] = requests.compat.urljoin(r.url, link["href"])
                regs.append(mapear_registro_generico(linha))
        return regs


class ConectorFiorilli(ConectorMunicipal):
    """Fiorilli SCPI — Portal da Transparência com exportação JSON."""

    sistema = "FIORILLI"

    def buscar_contratos(self, exercicio: int) -> List[Dict[str, Any]]:
        params = {"Listagem": "Contratos", "Empresa": 1, "Exercicio": exercicio,
                  "DiaInicioPeriodo": "01", "MesInicialPeriodo": "01",
                  "DiaFinalPeriodo": "31", "MesFinalPeriodo": "12", "MostrarFornecedor": "True"}
        for caminho in ("VersaoJson/LicitacoesEContratos/", "Transparencia/VersaoJson/LicitacoesEContratos/"):
            dados = _get_json_seguro(f"{self.base}/{caminho}", params)
            if isinstance(dados, dict):
                dados = next((v for v in dados.values() if isinstance(v, list)), None)
            if isinstance(dados, list) and dados:
                return [mapear_registro_generico(d) for d in dados if isinstance(d, dict)]
        return super().buscar_contratos(exercicio)


class ConectorElotech(ConectorMunicipal):
    """Elotech OXY — portal com API REST pública."""

    sistema = "ELOTECH"

    def buscar_contratos(self, exercicio: int) -> List[Dict[str, Any]]:
        for caminho in ("portaltransparencia-api/api/contratos", "api/contratos"):
            dados = _get_json_seguro(f"{self.base}/{caminho}", {"entidade": 1, "exercicio": exercicio, "size": 500})
            if isinstance(dados, dict):
                dados = dados.get("content") or dados.get("data")
            if isinstance(dados, list) and dados:
                return [mapear_registro_generico(d) for d in dados if isinstance(d, dict)]
        return []

    def link_detalhe(self, numero: str = "") -> str:
        return f"{self.base}/portaltransparencia/1/contratos"


class ConectorIPM(ConectorMunicipal):
    """IPM Sistemas (Atende.Net) — páginas HTML de transparência."""

    sistema = "IPM"
    caminhos_html = ("transparencia/item/contratos", "transparencia/contratos")


class ConectorBetha(ConectorMunicipal):
    """Betha Cloud — portal SPA; sem API pública estável sem chave da entidade.

    Retorna vazio e direciona para o portal. Para habilitar, informe em
    PORTAIS_CONFIRMADOS a URL de consulta de contratos da entidade.
    """

    sistema = "BETHA"

    def buscar_contratos(self, exercicio: int) -> List[Dict[str, Any]]:
        return []


class ConectorGovBR(ConectorMunicipal):
    sistema = "GOVBR"
    caminhos_html = ("transparencia/contratos", "contratos", "portal-da-transparencia/contratos")


class ConectorCoplan(ConectorMunicipal):
    sistema = "COPLAN"
    caminhos_html = ("transparencia/contratos", "contratos.php", "contratos")


CONECTORES = {
    "FIORILLI": ConectorFiorilli, "ELOTECH": ConectorElotech, "IPM": ConectorIPM,
    "BETHA": ConectorBetha, "GOVBR": ConectorGovBR, "COPLAN": ConectorCoplan,
}


def _mesclar_portal(contratos: List[Dict[str, Any]], regs: List[Dict[str, Any]], conector: ConectorMunicipal) -> int:
    """Complementa contratos PNCP com dados do portal municipal (empenhado/link)."""
    mesclados = 0
    for reg in regs:
        num = so_digitos(str(reg.get("numero", "")).split("/")[0])
        cnpj = so_digitos(reg.get("cnpj"))
        for c in contratos:
            if c["municipio"] != conector.mun.nome:
                continue
            num_c = so_digitos(c["numero_contrato"].split("/")[0])
            if num and num_c and num.lstrip("0") == num_c.lstrip("0") and (not cnpj or cnpj == c["_ni_fornecedor"]):
                emp = _num(reg.get("valor_empenhado"))
                if emp is not None:
                    c["valor_empenhado"] = emp
                if reg.get("url") and c["status_contrato"] != STATUS_DOC_OK:
                    c["url_contrato"], c["status_contrato"] = reg["url"], STATUS_DOC_PAGINA
                c["fonte"] = f"PNCP + {conector.sistema}"
                mesclados += 1
                break
    return mesclados


def deduplicar(contratos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove publicações duplicadas do mesmo contrato no PNCP.

    Alguns órgãos publicam o mesmo instrumento mais de uma vez (ex.: "000064/2026"
    e "64/2026"), o que inflaria os totais. Chave: órgão + nº normalizado +
    fornecedor + valor global. Mantém o de maior sequencial (publicação mais recente).
    """
    escolhidos: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for c in contratos:
        num = so_digitos(c["numero_contrato"].split("/")[0]).lstrip("0")
        chave = (c["_cnpj_orgao"], num, c["_ano"], c["_ni_fornecedor"], round(c["valor_global"] or 0, 2),
                 _sem_acento(c["tipo_instrumento"])[:8])
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
    municipios_sem_orgao: List[str] = field(default_factory=list)


Progresso = Callable[[float, str], None]


def coletar_contratos(
    municipios: List[Municipio],
    exercicio: int,
    incluir_nao_tecnicos: bool = False,
    enriquecer_cnae_fornecedor: bool = False,
    progresso: Optional[Progresso] = None,
) -> ResultadoColeta:
    """Coleta, classifica e enriquece os contratos dos municípios selecionados."""
    prog = progresso or (lambda f, m: None)
    cliente = ClientePNCP()
    res = ResultadoColeta()

    # 1) Descoberta de órgãos municipais -----------------------------------
    prog(0.02, f"Descobrindo órgãos municipais em {len(municipios)} município(s)…")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futuros = {ex.submit(cliente.descobrir_orgaos, m, exercicio): m for m in municipios}
        for fut in as_completed(futuros):
            m = futuros[fut]
            try:
                orgs = fut.result()
            except Exception as exc:  # noqa: BLE001
                res.avisos.append(f"{m.nome}: falha na descoberta de órgãos no PNCP ({exc}).")
                orgs = []
            if not orgs:
                res.municipios_sem_orgao.append(m.nome)
            res.orgaos.extend(orgs)

    # 2) Contratos por órgão -----------------------------------------------
    por_nome = {m.nome: m for m in municipios}
    brutos: List[Tuple[Dict[str, Any], Municipio]] = []
    total = max(len(res.orgaos), 1)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futuros = {ex.submit(cliente.contratos_do_orgao, o.cnpj, exercicio): o for o in res.orgaos}
        for i, fut in enumerate(as_completed(futuros), 1):
            o = futuros[fut]
            prog(0.05 + 0.55 * i / total, f"Contratos de {o.razao_social[:45]} ({i}/{total})")
            try:
                itens = fut.result()
            except Exception as exc:  # noqa: BLE001
                res.avisos.append(f"{o.razao_social}: não foi possível ler os contratos ({exc}).")
                continue
            for b in itens:
                brutos.append((b, por_nome[o.municipio]))
    res.total_bruto = len(brutos)

    # 3) Normalização + classificação + filtro do exercício ---------------
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
    tecnicos = [c for c in todos if incluir_nao_tecnicos or c["area"] != AREA_NAO_TECNICA]
    tecnicos.sort(key=lambda c: c["valor_global"] or 0, reverse=True)
    if len(tecnicos) > MAX_ENRIQUECIMENTO:
        res.avisos.append(
            f"{len(tecnicos)} contratos técnicos; anexos detalhados buscados para os "
            f"{MAX_ENRIQUECIMENTO} de maior valor (demais com link para a página do contrato)."
        )

    # 4) Enriquecimento (anexos, termos, modalidade) ------------------------
    alvo = tecnicos[:MAX_ENRIQUECIMENTO]
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

    # 5) Conectores municipais ---------------------------------------------
    for m in municipios:
        if not m.sistema or m.sistema not in CONECTORES:
            continue
        prog(0.92, f"Consultando portal {m.sistema} de {m.nome}…")
        conector = CONECTORES[m.sistema](m)
        try:
            regs = conector.buscar_contratos(exercicio)
            n = _mesclar_portal(tecnicos, regs, conector)
            res.avisos.append(f"{m.nome} ({m.sistema}): {len(regs)} registro(s) no portal, {n} vinculado(s).")
        except Exception as exc:  # noqa: BLE001
            res.avisos.append(f"{m.nome} ({m.sistema}): conector indisponível ({exc}).")

    if enriquecer_cnae_fornecedor and tecnicos:
        prog(0.95, "Consultando CNAE das contratadas (BrasilAPI)…")
        enriquecer_cnae(tecnicos)
        if not incluir_nao_tecnicos:
            tecnicos = [c for c in tecnicos if c["area"] != AREA_NAO_TECNICA]

    for c in tecnicos:
        if c["valor_empenhado"] is not None:
            c["saldo_a_empenhar"] = max((c["valor_global"] or 0) - c["valor_empenhado"], 0.0)

    res.contratos = tecnicos
    prog(1.0, f"Concluído: {len(tecnicos)} contrato(s) técnico(s) de {res.total_bruto} publicados.")
    return res


__all__ = [
    "ClientePNCP", "ResultadoColeta", "coletar_contratos", "formatar_cnpj", "SITUACOES",
    "SITUACAO_VIGENTE", "SITUACAO_PARALISADO", "SITUACAO_CONCLUIDO",
    "STATUS_DOC_OK", "STATUS_DOC_PAGINA", "STATUS_DOC_AUSENTE", "CONECTORES", "normalizar_nome",
]
