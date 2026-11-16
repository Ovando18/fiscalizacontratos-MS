"""
Base geográfica do FiscalizaObras-MS.

Contém:
  * Municípios com Fiscais Fixos (pesquisa individual, fora das regiões);
  * As 18 Regiões de Fiscalização numeradas;
  * Código IBGE (7 dígitos) de cada um dos 79 municípios de MS;
  * URL base do site/portal da transparência e o sistema de transparência
    utilizado (quando conhecido), usados pelos conectores municipais.

Observação sobre URLs e sistemas
--------------------------------
Os portais municipais mudam de fornecedor e de endereço com frequência.
Por isso a URL padrão segue o domínio oficial ``<slug>.ms.gov.br`` e o campo
``sistema`` fica ``None`` (somente PNCP) até ser confirmado. Para ativar um
conector específico (Betha, Fiorilli, Elotech, IPM, GovBR, Coplan), preencha
``PORTAIS_CONFIRMADOS`` abaixo com a URL real do portal e o sistema.
Use ``python scripts/verificar_portais.py`` para checar quais URLs respondem.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional

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
# Sistemas de transparência suportados pelos conectores
# ---------------------------------------------------------------------------
SISTEMAS_SUPORTADOS = ("BETHA", "FIORILLI", "ELOTECH", "IPM", "GOVBR", "COPLAN")

# Preencha aqui os portais já confirmados (URL real + sistema + CNPJ da prefeitura).
# Exemplo:
#   "NOME DO MUNICÍPIO": {
#       "url_portal": "https://<endereco-real-do-portal>/",
#       "sistema": "FIORILLI",
#       "cnpj_prefeitura": "00000000000000",
#   },
# Enquanto não houver entrada, o município é consultado somente via PNCP
# (fonte oficial nacional), com o site oficial como link de referência.
PORTAIS_CONFIRMADOS: Dict[str, Dict[str, Optional[str]]] = {}


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
    conf = PORTAIS_CONFIRMADOS.get(nome, {})
    url = conf.get("url_portal") or f"https://www.{slug_municipio(nome)}.ms.gov.br/"
    return Municipio(
        nome=nome,
        codigo_ibge=CODIGOS_IBGE[nome],
        regiao=regiao,
        url_portal=url,
        sistema=(conf.get("sistema") or None),
        cnpj_prefeitura=(conf.get("cnpj_prefeitura") or None),
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
    return problemas
