"""
Base geográfica do FiscalizaObras-MS.

Contém:
  * Municípios com Fiscais Fixos (pesquisa individual, fora das regiões);
  * As 18 Regiões de Fiscalização numeradas;
  * Código IBGE (7 dígitos) de cada um dos 79 municípios de MS;
  * URL base do site/portal da transparência e o sistema de transparência
    utilizado (quando conhecido), usados pelos conectores municipais.

Os endereços dos portais vêm da planilha fornecida pela fiscalização. Para
alterar um portal, edite ``PORTAIS_TRANSPARENCIA``; para checar quais
respondem, rode ``python scripts/verificar_portais.py``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

UF = "MS"
CODIGO_UF_IBGE = "50"

# ---------------------------------------------------------------------------
# Códigos IBGE (7 dígitos) — 79 municípios de Mato Grosso do Sul
# ---------------------------------------------------------------------------
CODIGOS_IBGE: Dict[str, str] = {
    "ÁGUA CLARA": "5000203",
    "ALCINÓPOLIS": "5000252",
    "AMAMBAI": "5000609",
    "ANASTÁCIO": "5000708",
    "ANAURILÂNDIA": "5000807",
    "ANGÉLICA": "5000856",
    "ANTÔNIO JOÃO": "5000906",
    "APARECIDA DO TABOADO": "5001003",
    "AQUIDAUANA": "5001102",
    "ARAL MOREIRA": "5001243",
    "BANDEIRANTES": "5001508",
    "BATAGUASSU": "5001904",
    "BATAYPORÃ": "5002001",
    "BELA VISTA": "5002100",
    "BODOQUENA": "5002159",
    "BONITO": "5002209",
    "BRASILÂNDIA": "5002308",
    "CAARAPÓ": "5002407",
    "CAMAPUÃ": "5002605",
    "CAMPO GRANDE": "5002704",
    "CARACOL": "5002803",
    "CASSILÂNDIA": "5002902",
    "CHAPADÃO DO SUL": "5002951",
    "CORGUINHO": "5003108",
    "CORONEL SAPUCAIA": "5003157",
    "CORUMBÁ": "5003207",
    "COSTA RICA": "5003256",
    "COXIM": "5003306",
    "DEODÁPOLIS": "5003454",
    "DOIS IRMÃOS DO BURITI": "5003488",
    "DOURADINA": "5003504",
    "DOURADOS": "5003702",
    "ELDORADO": "5003751",
    "FÁTIMA DO SUL": "5003801",
    "FIGUEIRÃO": "5003900",
    "GLÓRIA DE DOURADOS": "5004007",
    "GUIA LOPES DA LAGUNA": "5004106",
    "IGUATEMI": "5004304",
    "INOCÊNCIA": "5004403",
    "ITAPORÃ": "5004502",
    "ITAQUIRAÍ": "5004601",
    "IVINHEMA": "5004700",
    "JAPORÃ": "5004809",
    "JARAGUARI": "5004908",
    "JARDIM": "5005004",
    "JATEÍ": "5005103",
    "JUTI": "5005152",
    "LADÁRIO": "5005202",
    "LAGUNA CARAPÃ": "5005251",
    "MARACAJU": "5005400",
    "MIRANDA": "5005608",
    "MUNDO NOVO": "5005681",
    "NAVIRAÍ": "5005707",
    "NIOAQUE": "5005806",
    "NOVA ALVORADA DO SUL": "5006002",
    "NOVA ANDRADINA": "5006200",
    "NOVO HORIZONTE DO SUL": "5006259",
    "PARAÍSO DAS ÁGUAS": "5006275",
    "PARANAÍBA": "5006309",
    "PARANHOS": "5006358",
    "PEDRO GOMES": "5006408",
    "PONTA PORÃ": "5006606",
    "PORTO MURTINHO": "5006903",
    "RIBAS DO RIO PARDO": "5007109",
    "RIO BRILHANTE": "5007208",
    "RIO NEGRO": "5007307",
    "RIO VERDE DE MATO GROSSO": "5007406",
    "ROCHEDO": "5007505",
    "SANTA RITA DO PARDO": "5007554",
    "SÃO GABRIEL DO OESTE": "5007695",
    "SETE QUEDAS": "5007703",
    "SELVÍRIA": "5007802",
    "SIDROLÂNDIA": "5007901",
    "SONORA": "5007935",
    "TACURU": "5007950",
    "TAQUARUSSU": "5007976",
    "TERENOS": "5008008",
    "TRÊS LAGOAS": "5008305",
    "VICENTINA": "5008404",
}

# ---------------------------------------------------------------------------
# Bloco A — Municípios com Fiscais Fixos (pesquisa individual separada)
# ---------------------------------------------------------------------------
FISCAIS_FIXOS: List[str] = ["CAMPO GRANDE", "DOURADOS", "PARANAÍBA", "TRÊS LAGOAS"]
ROTULO_FISCAL_FIXO = "Fiscal Fixo"

# ---------------------------------------------------------------------------
# Bloco B — 18 Regiões de Fiscalização
# ---------------------------------------------------------------------------
REGIOES: Dict[int, List[str]] = {
    1: ["ANGÉLICA", "IVINHEMA", "GLÓRIA DE DOURADOS", "DEODÁPOLIS"],
    2: ["TERENOS", "DOIS IRMÃOS DO BURITI", "AQUIDAUANA", "ANASTÁCIO"],
    3: ["BONITO", "BELA VISTA", "PORTO MURTINHO", "CARACOL"],
    4: ["CORUMBÁ", "LADÁRIO", "MIRANDA", "BODOQUENA"],
    5: ["COSTA RICA", "CHAPADÃO DO SUL", "PARAÍSO DAS ÁGUAS"],
    6: ["COXIM", "SONORA", "PEDRO GOMES", "ALCINÓPOLIS"],
    7: ["FÁTIMA DO SUL", "VICENTINA", "JATEÍ", "ITAPORÃ", "DOURADINA"],
    8: ["SÃO GABRIEL DO OESTE", "RIO VERDE DE MATO GROSSO", "CAMAPUÃ", "FIGUEIRÃO"],
    9: ["NOVA ANDRADINA", "BATAYPORÃ", "TAQUARUSSU", "NOVO HORIZONTE DO SUL"],
    10: ["PONTA PORÃ", "ANTÔNIO JOÃO", "ARAL MOREIRA", "MARACAJU"],
    11: ["RIO BRILHANTE", "NOVA ALVORADA DO SUL", "RIBAS DO RIO PARDO", "ÁGUA CLARA"],
    12: ["JARAGUARI", "BANDEIRANTES", "RIO NEGRO", "CORGUINHO", "ROCHEDO"],
    13: ["SIDROLÂNDIA", "NIOAQUE", "JARDIM", "GUIA LOPES DA LAGUNA"],
    14: ["AMAMBAI", "CORONEL SAPUCAIA", "PARANHOS", "SETE QUEDAS", "TACURU"],
    15: ["IGUATEMI", "ITAQUIRAÍ", "ELDORADO", "MUNDO NOVO", "JAPORÃ"],
    16: ["NAVIRAÍ", "LAGUNA CARAPÃ", "CAARAPÓ", "JUTI"],
    17: ["APARECIDA DO TABOADO", "SELVÍRIA", "CASSILÂNDIA", "INOCÊNCIA"],
    18: ["BRASILÂNDIA", "SANTA RITA DO PARDO", "BATAGUASSU", "ANAURILÂNDIA"],
}

OPCAO_TODOS_REGIAO = "TODOS OS MUNICÍPIOS DA REGIÃO"

# ---------------------------------------------------------------------------
# Portais da Transparência municipais (fonte: planilha "Transparências MS
# completo", fornecida pela equipe de fiscalização — 79 municípios)
# ---------------------------------------------------------------------------
# Sistema identificado pela URL:
#   FIORILLI  — SCPI 9.0: possui API pública de Dados Abertos (JSON), integrada
#               ao coletor (contratos, valor empenhado, liquidado e saldo).
#   BETHA, QUALITY, MEGASOFT, CR2, OUTRO — usados como link oficial do portal
#               (sem API validada; não são raspados para evitar dados errados).
# Observação: as URLs de NOVA ANDRADINA (domínio .ms.leg.br) e NOVO HORIZONTE
# DO SUL ("camara_municipal") apontam para portais da Câmara Municipal.
SISTEMA_FIORILLI = "FIORILLI"
SISTEMAS_CONHECIDOS = ("FIORILLI", "BETHA", "QUALITY", "MEGASOFT", "CR2", "OUTRO")

PORTAIS_TRANSPARENCIA: Dict[str, Tuple[str, str]] = {
    "ÁGUA CLARA": ("FIORILLI", "http://45.183.236.226:8079/transparencia/"),
    "ALCINÓPOLIS": ("FIORILLI", "http://45.173.125.13:8079/transparencia/"),
    "AMAMBAI": ("FIORILLI", "http://177.67.190.178:5656/transparencia/"),
    "ANASTÁCIO": ("MEGASOFT", "https://anastacio.megasofttransparencia.com.br/"),
    "ANAURILÂNDIA": ("OUTRO", "http://portaltransparenciaanaurilandia.ddns.com.br:8181/"),
    "ANGÉLICA": ("BETHA", "https://transparencia.betha.cloud/#/3CsimkdlAFWc2SxNasIRBA=="),
    "ANTÔNIO JOÃO": ("QUALITY", "https://web.qualitysistemas.com.br/portal/transparencia_publica/prefeitura_municipal_de_antonio_joao"),
    "APARECIDA DO TABOADO": ("FIORILLI", "http://143.0.127.202:8079/transparencia/"),
    "AQUIDAUANA": ("BETHA", "https://e-gov.betha.com.br/transparencia/01037-173/recursos.faces?mun=tR-qJvZ6sQY="),
    "ARAL MOREIRA": ("FIORILLI", "http://177.73.104.13:8079/transparencia/"),
    "BANDEIRANTES": ("QUALITY", "https://web.qualitysistemas.com.br/portal/prefeitura_municipal_de_bandeirantes"),
    "BATAGUASSU": ("FIORILLI", "http://45.182.157.6:8079/transparencia/"),
    "BATAYPORÃ": ("OUTRO", "https://www.publicacoesmunicipais.inf.br/transparencia/bataypora"),
    "BELA VISTA": ("FIORILLI", "http://191.5.174.198:8079/transparencia/"),
    "BODOQUENA": ("BETHA", "https://transparencia.betha.cloud/#/9thTqEHpf4m-Nn7nTliYbw=="),
    "BONITO": ("FIORILLI", "http://45.188.183.155:8079/transparencia/"),
    "BRASILÂNDIA": ("FIORILLI", "http://187.17.197.14:8079/transparencia/"),
    "CAARAPÓ": ("BETHA", "https://transparencia.betha.cloud/#/61M0eJ_21GlQw6p7f3svmg=="),
    "CAMAPUÃ": ("QUALITY", "https://web.qualitysistemas.com.br/portal/municipio_de_camapua"),
    "CAMPO GRANDE": ("OUTRO", "https://transparencia.campogrande.ms.gov.br/"),
    "CARACOL": ("QUALITY", "https://web.qualitysistemas.com.br/portal/transparencia_publica/prefeitura_municipal_de_caracol"),
    "CASSILÂNDIA": ("FIORILLI", "http://45.189.53.3:8076/transparencia/"),
    "CHAPADÃO DO SUL": ("FIORILLI", "https://pmchapadao.rcmsuporte.com.br/transparencia/"),
    "CORGUINHO": ("QUALITY", "https://web.qualitysistemas.com.br/portal/transparencia_publica/prefeitura_municipal_de_corguinho"),
    "CORONEL SAPUCAIA": ("FIORILLI", "https://coronelsapucaia.rcmsuporte.com.br:8079/transparencia/"),
    "CORUMBÁ": ("FIORILLI", "https://scpi.corumba.ms.gov.br/transparencia/"),
    "COSTA RICA": ("FIORILLI", "http://pmcostarica.rcmsuporte.com.br:8079/transparencia/"),
    "COXIM": ("FIORILLI", "http://pmcoxim.rcmsuporte.com.br:8079/transparencia/Default.aspx"),
    "DEODÁPOLIS": ("BETHA", "https://transparencia.betha.cloud/#/whlvWPlYqIFeODuQD0dKgA=="),
    "DOIS IRMÃOS DO BURITI": ("FIORILLI", "http://transparencia.doisirmaosdoburiti.ms.gov.br:8079/transparencia/"),
    "DOURADINA": ("OUTRO", "http://portaltransparenciadouradina.ddns.com.br/"),
    "DOURADOS": ("BETHA", "https://transparencia.betha.cloud/#/yJ9y3J_D09niojsx99D7Dw=="),
    "ELDORADO": ("FIORILLI", "https://scpi.eldorado.rcmsuporte.com.br/transparencia/"),
    "FÁTIMA DO SUL": ("BETHA", "https://e-gov.betha.com.br/transparencia/01037-173/recursos.faces?mun=jIUn5a88xr8="),
    "FIGUEIRÃO": ("OUTRO", "https://www.figueirao.ms.gov.br/portal-da-transparencia/"),
    "GLÓRIA DE DOURADOS": ("FIORILLI", "http://177.73.106.211:5656/Transparencia/"),
    "GUIA LOPES DA LAGUNA": ("FIORILLI", "http://45.171.204.95:8079/transparencia/"),
    "IGUATEMI": ("CR2", "https://www.portalcr2.com.br/entidade/iguatemi"),
    "INOCÊNCIA": ("FIORILLI", "http://179.125.63.161:8079/transparencia/"),
    "ITAPORÃ": ("FIORILLI", "https://transparencia.itapora.ms.gov.br/Transparencia/"),
    "ITAQUIRAÍ": ("BETHA", "https://e-gov.betha.com.br/transparencia/01037-173/recursos.faces?mun=QKBgJkx3Atw="),
    "IVINHEMA": ("FIORILLI", "https://transparencia.ivinhema.ms.gov.br/transparencia/"),
    "JAPORÃ": ("FIORILLI", "http://181.191.195.74:5656/transparencia/"),
    "JARAGUARI": ("FIORILLI", "http://pmjaraguari.rcmsuporte.com.br:8079/transparencia/"),
    "JARDIM": ("OUTRO", "http://200.209.160.172:4545/index"),
    "JATEÍ": ("OUTRO", "https://transparencia-ocmblue.com.br/jatei"),
    "JUTI": ("FIORILLI", "http://177.73.104.96:5656/transparencia/"),
    "LADÁRIO": ("OUTRO", "https://www.ladario.ms.gov.br/portal/transparencia"),
    "LAGUNA CARAPÃ": ("BETHA", "https://transparencia.betha.cloud/#/Qamj9G2f8WhljKQKjl9BnQ=="),
    "MARACAJU": ("OUTRO", "https://www.maracaju.ms.gov.br/portal/transparencia"),
    "MIRANDA": ("FIORILLI", "http://168.228.168.93:5656/transparencia/"),
    "MUNDO NOVO": ("BETHA", "https://transparencia.betha.cloud/#/S0vZYp2x1AO4UFMuI6vo6w=="),
    "NAVIRAÍ": ("OUTRO", "https://transparencia.navirai.ms.gov.br/"),
    "NIOAQUE": ("QUALITY", "https://web.qualitysistemas.com.br/portal/transparencia_publica/prefeitura_municipal_de_nioaque"),
    "NOVA ALVORADA DO SUL": ("FIORILLI", "https://transparencia.novaalvoradadosul.ms.gov.br/transparencia/"),
    "NOVA ANDRADINA": ("OUTRO", "https://www.novaandradina.ms.leg.br/transparencia/pagina-de-links/transparencia"),
    "NOVO HORIZONTE DO SUL": ("QUALITY", "https://web.qualitysistemas.com.br/portal/transparencia_publica/camara_municipal_de_novo_horizonte_do_sul"),
    "PARAÍSO DAS ÁGUAS": ("FIORILLI", "http://170.81.37.97:8079/transparencia/"),
    "PARANAÍBA": ("FIORILLI", "http://45.184.83.32:8079/Transparencia/"),
    "PARANHOS": ("FIORILLI", "http://45.179.174.190:8079/transparencia/"),
    "PEDRO GOMES": ("FIORILLI", "http://45.6.108.122:5656/transparencia/"),
    "PONTA PORÃ": ("FIORILLI", "https://contabilidade.pontapora.ms.gov.br/transparencia/"),
    "PORTO MURTINHO": ("BETHA", "https://e-gov.betha.com.br/transparencia/01037-173/recursos.faces"),
    "RIBAS DO RIO PARDO": ("FIORILLI", "http://45.174.220.245:8079/transparencia/"),
    "RIO BRILHANTE": ("BETHA", "https://transparencia.betha.cloud/#/KLojapoJwJLapEYmhbLUHQ=="),
    "RIO NEGRO": ("QUALITY", "https://web.qualitysistemas.com.br/portal/transparencia_publica/prefeitura_municipal_de_rio_negro"),
    "RIO VERDE DE MATO GROSSO": ("BETHA", "https://transparencia.betha.cloud/#/KlxQinrZBH80Uqv9BDVJaw=="),
    "ROCHEDO": ("QUALITY", "https://web.qualitysistemas.com.br/contratos_e_convenios/prefeitura_municipal_de_rochedo"),
    "SANTA RITA DO PARDO": ("CR2", "https://santaritadopardo.cr2.site/"),
    "SÃO GABRIEL DO OESTE": ("FIORILLI", "https://appsaogabriel.rcmsuporte.com.br:8086/transparencia/"),
    "SELVÍRIA": ("FIORILLI", "http://45.186.221.158:5656/transparencia/"),
    "SETE QUEDAS": ("FIORILLI", "http://transparencia.setequedas.ms.gov.br:8079/transparencia/"),
    "SIDROLÂNDIA": ("FIORILLI", "http://187.6.86.78:5656/transparencia/"),
    "SONORA": ("FIORILLI", "http://pmsonora.rcmsuporte.com.br:8079/transparencia/"),
    "TACURU": ("MEGASOFT", "https://tacuru.megasofttransparencia.com.br/"),
    "TAQUARUSSU": ("BETHA", "https://transparencia.betha.cloud/#/_VQj5BoEPGmm_VeoePaAKg=="),
    "TERENOS": ("QUALITY", "https://web.qualitysistemas.com.br/portal/transparencia_publica/prefeitura_municipal_de_terenos"),
    "TRÊS LAGOAS": ("FIORILLI", "http://pmtreslagoas.rcmsuporte.com.br:8079/transparencia/"),
    "VICENTINA": ("OUTRO", "http://portaltransparenciavicentina.ddns.com.br/"),
}

# Sobrescritas opcionais (ex.: CNPJ da prefeitura para acelerar a descoberta no PNCP)
#   "NOME DO MUNICÍPIO": {"cnpj_prefeitura": "00000000000000"}
AJUSTES_MUNICIPIOS: Dict[str, Dict[str, Optional[str]]] = {}


def remover_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)
    )


def normalizar_nome(nome: str) -> str:
    """Normaliza nome de município para comparação (sem acento, maiúsculo)."""
    return " ".join(remover_acentos(nome).upper().replace("-", " ").split())


def slug_municipio(nome: str) -> str:
    return remover_acentos(nome).lower().replace(" ", "")


@dataclass(frozen=True)
class Municipio:
    nome: str
    codigo_ibge: str
    regiao: Optional[int]  # None = Fiscal Fixo
    url_portal: str
    sistema: Optional[str] = None
    cnpj_prefeitura: Optional[str] = None
    extras: Dict[str, str] = field(default_factory=dict, compare=False, hash=False)

    @property
    def rotulo_regiao(self) -> str:
        return ROTULO_FISCAL_FIXO if self.regiao is None else f"Região {self.regiao:02d}"

    @property
    def fiscal_fixo(self) -> bool:
        return self.regiao is None


def _montar_municipio(nome: str, regiao: Optional[int]) -> Municipio:
    sistema, url = PORTAIS_TRANSPARENCIA.get(nome, (None, f"https://www.{slug_municipio(nome)}.ms.gov.br/"))
    ajuste = AJUSTES_MUNICIPIOS.get(nome, {})
    return Municipio(
        nome=nome,
        codigo_ibge=CODIGOS_IBGE[nome],
        regiao=regiao,
        url_portal=url,
        sistema=sistema,
        cnpj_prefeitura=(ajuste.get("cnpj_prefeitura") or None),
    )


def _construir_catalogo() -> Dict[str, Municipio]:
    catalogo: Dict[str, Municipio] = {}
    for nome in FISCAIS_FIXOS:
        catalogo[nome] = _montar_municipio(nome, None)
    for numero, nomes in REGIOES.items():
        for nome in nomes:
            if nome in catalogo:
                raise ValueError(f"Município duplicado no mapeamento: {nome}")
            catalogo[nome] = _montar_municipio(nome, numero)
    return catalogo


MUNICIPIOS: Dict[str, Municipio] = _construir_catalogo()
_INDICE_NORMALIZADO = {normalizar_nome(n): m for n, m in MUNICIPIOS.items()}
_INDICE_IBGE = {m.codigo_ibge: m for m in MUNICIPIOS.values()}


def obter_municipio(nome: str) -> Optional[Municipio]:
    return MUNICIPIOS.get(nome) or _INDICE_NORMALIZADO.get(normalizar_nome(nome))


def municipio_por_ibge(codigo: str) -> Optional[Municipio]:
    return _INDICE_IBGE.get(str(codigo or "")[:7])


def municipios_da_regiao(numero: int) -> List[Municipio]:
    return [MUNICIPIOS[n] for n in REGIOES.get(numero, [])]


def validar_base() -> List[str]:
    """Retorna lista de inconsistências encontradas (vazia = base íntegra)."""
    problemas: List[str] = []
    if len(REGIOES) != 18:
        problemas.append(f"Esperadas 18 regiões, encontradas {len(REGIOES)}")
    if len(MUNICIPIOS) != len(CODIGOS_IBGE):
        faltantes = set(CODIGOS_IBGE) - set(MUNICIPIOS)
        problemas.append(f"Municípios de MS fora do mapeamento: {sorted(faltantes)}")
    for nome, cod in CODIGOS_IBGE.items():
        if len(cod) != 7 or not cod.startswith(CODIGO_UF_IBGE):
            problemas.append(f"Código IBGE inválido para {nome}: {cod}")
    if len(set(CODIGOS_IBGE.values())) != len(CODIGOS_IBGE):
        problemas.append("Há códigos IBGE duplicados")
    sem_portal = set(CODIGOS_IBGE) - set(PORTAIS_TRANSPARENCIA)
    if sem_portal:
        problemas.append(f"Municípios sem portal configurado: {sorted(sem_portal)}")
    for nome, (sistema, url) in PORTAIS_TRANSPARENCIA.items():
        if nome not in CODIGOS_IBGE:
            problemas.append(f"Portal para município desconhecido: {nome}")
        if sistema not in SISTEMAS_CONHECIDOS or not url.startswith(("http://", "https://")):
            problemas.append(f"Portal inválido para {nome}: {sistema} {url}")
    return problemas
