"""
Classificador técnico de contratos — Engenharia, Agronomia e Geociências.

Combina três sinais, em ordem de força:
  1. Categoria do processo no PNCP ("Obras", "Serviços de Engenharia");
  2. CNAE da contratada (quando disponível — enriquecimento opcional);
  3. Palavras-chave no objeto contratual (regex sem acento, com pesos).

Também gera os "indícios técnicos para fiscalização" (ART/RRT, licenças,
certificações) exibidos no inspetor de contrato.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

AREA_TODAS = "Todas"
AREA_CIVIL = "Engenharia Civil / Obras Públicas"
AREA_AGRO = "Agronomia / Meio Ambiente"
AREA_GEO = "Geociências / Topografia / Georreferenciamento"
AREA_ELETRICA = "Engenharia Elétrica / Mecânica"
AREA_PROJETOS = "Projetos, Laudos e Consultoria"
AREA_NAO_TECNICA = "Não técnica"

AREAS_FISCALIZACAO: List[str] = [AREA_TODAS, AREA_CIVIL, AREA_AGRO, AREA_GEO, AREA_ELETRICA, AREA_PROJETOS]


def _sem_acento(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


# ---------------------------------------------------------------------------
# Palavras-chave por área: (padrão regex sem acento, peso)
# ---------------------------------------------------------------------------
PALAVRAS_CHAVE: Dict[str, List[Tuple[str, int]]] = {
    AREA_CIVIL: [
        (r"(?<!mao de )\bobras?\b", 3), (r"\bconstru(cao|coes|ir)\b", 3), (r"\breforma", 3), (r"\bamplia(cao|coes)\b", 3),
        (r"\bpavimenta", 4), (r"\brecapeamento", 4), (r"\btapa[- ]?buraco", 3), (r"\basfalt", 3),
        (r"\bcbuq\b", 4), (r"\bdrenagem", 4), (r"\bgalerias? pluvia", 4), (r"\bmeio[- ]fio", 3),
        (r"\bsarjeta", 3), (r"\bpontes?\b", 4), (r"\bviaduto", 4), (r"\bbueiro", 3), (r"\bcalcada", 2),
        (r"\bcascalhamento", 3), (r"\bpatrolamento", 2), (r"\bterraplenagem", 4), (r"\brevitaliza", 2),
        (r"\besgotamento sanitario", 4), (r"\brede de (agua|esgoto)", 4), (r"\bsaneamento", 3),
        (r"\bedifica", 3), (r"\bunidade basica de saude|\bubs\b", 2), (r"\bescola\b", 1), (r"\bcreche", 1),
        (r"\bquadra (poliesportiva|coberta)", 3), (r"\bcobertura metalica", 3), (r"\bestrutura metalica", 3),
        (r"\balvenaria", 3), (r"\bconcreto", 3), (r"\bmanutencao predial", 3), (r"\bhabitaciona", 3),
        (r"\bservicos? de engenharia", 4), (r"\bempreitada", 3), (r"\bestrada vicinal|\bestradas vicinais", 4),
        (r"\bpaisagismo", 1), (r"\bcontencao|\bmuro de arrimo", 3),
    ],
    AREA_AGRO: [
        (r"\bagronom", 4), (r"\bagricol", 3), (r"\bflorest", 3), (r"\breflorestamento", 4),
        (r"\barboriza", 3), (r"\bpoda\b|\bpodas\b", 2), (r"\bsupressao (de )?vegeta", 4), (r"\brecuperacao de areas? degradad", 4),
        (r"\bprad\b", 4), (r"\blicenciamento ambiental", 4), (r"\bestudo de impacto ambiental|\beia\b|\brima\b", 4),
        (r"\bmeio ambiente\b", 2), (r"\bambiental", 2), (r"\bresiduos solidos", 3), (r"\baterro sanitario", 4),
        (r"\bcorrecao de solo|\bcalcario", 3), (r"\bpatrulha mecanizada", 3), (r"\bmecanizacao agricola", 3),
        (r"\bassistencia tecnica rural|\bater\b", 4), (r"\bdefensivos?|\bagrotoxic", 3), (r"\bviveiro", 2),
        (r"\bmudas?\b", 1), (r"\birrigacao", 3), (r"\bconservacao (do )?solo", 4), (r"\bcurvas? de nivel", 4),
        (r"\bmicrobacia", 3), (r"\bpiscicultura|\baquicultura", 2), (r"\bzootecn", 2),
    ],
    AREA_GEO: [
        (r"\bgeorreferenc", 5), (r"\btopograf", 5), (r"\blevantamento planialtimetric", 5), (r"\bplanialtimetr", 5),
        (r"\bcartograf", 5), (r"\baerolevantamento", 5), (r"\baerofotogram", 5), (r"\bortofoto", 5),
        (r"\bdrone|\bvant\b|\brpa\b", 3), (r"\bgeolog", 5), (r"\bgeotecn", 5), (r"\bsondage", 4),
        (r"\bspt\b", 3), (r"\bpocos? (artesian|tubular)", 4), (r"\bperfuracao de poco", 4), (r"\bhidrogeolog", 5),
        (r"\bcadastro (tecnico )?multifinalitario|\bcadastro imobiliario", 4), (r"\bgeoprocessamento", 5),
        (r"\bsig\b|\bwebgis|\bsistema de informac(ao|oes) geografica", 4), (r"\bregulariza(cao)? fundiaria|\breurb\b", 4),
        (r"\bloteamento", 2), (r"\bdemarcacao", 3), (r"\bbatimetri", 5), (r"\bgnss|\bgps geodesico", 4),
        (r"\bmapeamento", 3), (r"\bcar\b|\bcadastro ambiental rural", 3),
    ],
    AREA_ELETRICA: [
        (r"\beletric", 2), (r"\biluminacao publica", 5), (r"\bluminaria", 3), (r"\bled\b", 2),
        (r"\bsubestac", 5), (r"\brede de (media|baixa|alta) tensao", 5), (r"\bsistema fotovoltaic|\bfotovoltaic|\busina solar", 5),
        (r"\bgerador", 2), (r"\bspda\b|\bpara[- ]?raios", 4), (r"\bclimatiza", 3), (r"\bar[- ]condicionado", 2),
        (r"\belevador", 4), (r"\bplataforma elevatoria", 3), (r"\bmecanic", 2), (r"\bcaldeira", 4),
        (r"\bbomba(s)? (submersa|centrifuga)|\bconjunto motobomba", 3), (r"\bautomacao", 3), (r"\bcabeamento estruturado", 2),
        (r"\bprevencao (e combate )?(a )?incendio|\bppci\b|\bhidrante", 4), (r"\bseguranca do trabalho|\bpgr\b|\bpcmso\b|\bltcat\b|\bnr[- ]?\d{1,2}\b", 3),
        (r"\btelecomunica", 2), (r"\bsemaforo|\bsemaforica", 3),
    ],
    AREA_PROJETOS: [
        (r"\bprojeto(s)? (basico|executivo|arquitetonic|estrutural|complementar|eletrico|hidrossanitari)", 5),
        (r"\belaboracao de projeto", 5), (r"\blaudos?\b", 4), (r"\bpericia", 3), (r"\bvistoria tecnica", 4),
        (r"\bconsultoria (tecnica )?(em|de) engenharia|\bconsultoria ambiental", 4), (r"\bassessoria tecnica (em|de) engenharia", 3), (r"\bgerenciamento de obra", 5),
        (r"\bfiscalizacao de obra|\bsupervisao de obra", 5), (r"\borcamento(s)? de obra|\bplanilha orcamentaria", 4),
        (r"\bestudo(s)? de viabilidade", 3), (r"\bplano diretor", 3), (r"\bplano municipal de saneamento", 4),
        (r"\bavaliacao de imove", 3), (r"\binspecao predial", 4), (r"\bas[- ]built", 4), (r"\bbim\b", 3),
    ],
}

# Termos que indicam claramente objeto NÃO técnico (reduzem falso positivo)
TERMOS_EXCLUSAO: List[str] = [
    r"\bgeneros alimenticios", r"\bmerenda", r"\bmedicamento", r"\bmaterial (de )?expediente", r"\bcombustive",
    r"\bpneus?\b", r"\blocacao de veiculo", r"\bmaterial (de )?limpeza", r"\buniformes?\b", r"\bshows?\b",
    r"\bpassagens? aerea", r"\bcestas? basica", r"\bmaterial didatico", r"\bfardamento",
    r"\baquisi\w* (de )?(materia|pecas?|equipamento|maquin|veicul|trator|retroescavadeira|caminh|ferramenta|tubos?)",
    r"\bmateriais? de consumo", r"\blocacao de (imovel|software|sistema)", r"\bsoftware", r"\bmao de obra terceirizada", r"\bpublicidade", r"\bdivulgacao",
]

# Categorias PNCP que indicam fornecimento de bens/locação (exigem evidência mais forte)
CATEGORIAS_PNCP_FORNECIMENTO = {"compras", "locacao imoveis", "alienacao de bens moveis/imoveis"}
PENALIDADE_FORNECIMENTO = 4

# CNAEs (divisão/grupo/subclasse — prefixo) associados a cada área
CNAES_POR_AREA: Dict[str, List[str]] = {
    AREA_CIVIL: ["41", "42", "431", "432", "433", "439", "7112"],  # construção, infraestrutura, eng.
    AREA_ELETRICA: ["4321", "4322", "4329", "3313", "3314", "3321", "7112", "7490103"],
    AREA_AGRO: ["01", "02", "016", "0161", "0220", "3811", "3821", "3900", "7490103", "7210"],
    AREA_GEO: ["7119701", "7119702", "7119703", "7119704", "7119799", "0990", "4399105", "7420"],
    AREA_PROJETOS: ["7111", "7112", "7119", "7120", "7490"],
}

CATEGORIAS_PNCP_ENGENHARIA = {"obras", "servicos de engenharia"}

LIMIAR_PONTUACAO = 3


@dataclass
class Classificacao:
    tecnico: bool
    area: str
    pontuacao: int
    areas_secundarias: List[str] = field(default_factory=list)
    termos: List[str] = field(default_factory=list)
    motivo: str = ""


def _pontuar(texto_norm: str) -> Dict[str, Tuple[int, List[str]]]:
    resultado: Dict[str, Tuple[int, List[str]]] = {}
    for area, padroes in PALAVRAS_CHAVE.items():
        total, termos = 0, []
        for padrao, peso in padroes:
            m = re.search(padrao, texto_norm)
            if m:
                total += peso
                termos.append(m.group(0).strip())
        if total:
            resultado[area] = (total, termos)
    return resultado


def classificar(
    objeto: str,
    categoria_pncp: Optional[str] = None,
    cnae: Optional[str] = None,
) -> Classificacao:
    """Classifica um contrato a partir do objeto, categoria PNCP e CNAE."""
    texto = _sem_acento(objeto)
    pontos = _pontuar(texto)
    motivos: List[str] = []

    cat = _sem_acento(categoria_pncp or "")
    if cat in CATEGORIAS_PNCP_ENGENHARIA:
        bonus_area = AREA_CIVIL
        # serviços de engenharia de projeto/geo/elétrica devem cair na área específica
        if pontos:
            bonus_area = max(pontos.items(), key=lambda kv: kv[1][0])[0]
        p, t = pontos.get(bonus_area, (0, []))
        pontos[bonus_area] = (p + 6, t + [f"categoria PNCP: {categoria_pncp}"])
        motivos.append(f"Categoria PNCP '{categoria_pncp}'")

    cnae_digitos = re.sub(r"\D", "", cnae or "")
    if cnae_digitos:
        for area, prefixos in CNAES_POR_AREA.items():
            if any(cnae_digitos.startswith(p) for p in prefixos):
                p, t = pontos.get(area, (0, []))
                pontos[area] = (p + 3, t + [f"CNAE {cnae_digitos}"])
                motivos.append(f"CNAE {cnae_digitos}")
                break

    penalidade = 0
    if cat not in CATEGORIAS_PNCP_ENGENHARIA:
        if any(re.search(p, texto) for p in TERMOS_EXCLUSAO):
            penalidade += 4
        if cat in CATEGORIAS_PNCP_FORNECIMENTO:
            penalidade += PENALIDADE_FORNECIMENTO
    if penalidade:
        pontos = {a: (v[0] - penalidade, v[1]) for a, v in pontos.items()}

    if not pontos:
        return Classificacao(False, AREA_NAO_TECNICA, 0, motivo="Sem indícios técnicos")

    ordenado = sorted(pontos.items(), key=lambda kv: kv[1][0], reverse=True)
    area, (pontuacao, termos) = ordenado[0]
    secundarias = [a for a, (p, _) in ordenado[1:] if p >= LIMIAR_PONTUACAO]
    tecnico = pontuacao >= LIMIAR_PONTUACAO
    if termos:
        motivos.append("Termos: " + ", ".join(dict.fromkeys(termos)))
    return Classificacao(
        tecnico=tecnico,
        area=area if tecnico else AREA_NAO_TECNICA,
        pontuacao=pontuacao,
        areas_secundarias=secundarias,
        termos=list(dict.fromkeys(termos)),
        motivo="; ".join(motivos),
    )


def pertence_a_area(area_contrato: str, secundarias: Iterable[str], area_filtro: str) -> bool:
    if area_filtro in (None, "", AREA_TODAS):
        return area_contrato != AREA_NAO_TECNICA
    return area_contrato == area_filtro or area_filtro in (secundarias or [])


# ---------------------------------------------------------------------------
# Indícios técnicos para fiscalização (CREA-MS / Lei 5.194/66 / Lei 6.496/77)
# ---------------------------------------------------------------------------
_INDICIOS_BASE = {
    AREA_CIVIL: [
        "ART de execução da obra registrada no CREA-MS (Lei 6.496/77) pelo responsável técnico da contratada.",
        "ART/RRT de projeto (arquitetônico, estrutural, complementares) vinculada ao processo licitatório.",
        "ART de fiscalização em nome do fiscal técnico designado pela prefeitura.",
        "Placa de obra com identificação dos responsáveis técnicos (Lei 5.194/66, art. 16).",
        "Diário de obra / Livro de ordem atualizado (Resolução CONFEA 1.094/2017).",
    ],
    AREA_AGRO: [
        "ART de execução/assistência técnica do Engenheiro Agrônomo ou Florestal responsável.",
        "Verificar licença ambiental (IMASUL) ou dispensa, quando aplicável ao objeto.",
        "Receituário agronômico para aplicação de defensivos, quando houver.",
        "ART de elaboração de PRAD/estudo ambiental, se previsto no objeto.",
    ],
    AREA_GEO: [
        "ART de levantamento topográfico/georreferenciamento pelo profissional habilitado.",
        "Georreferenciamento de imóvel rural: certificação no SIGEF/INCRA (Lei 10.267/2001).",
        "Aerolevantamento: verificar inscrição/autorização junto ao Ministério da Defesa (Decreto 2.278/97).",
        "Sondagens/geologia: ART do geólogo ou engenheiro geotécnico responsável pelo laudo.",
    ],
    AREA_ELETRICA: [
        "ART de execução de instalações elétricas/mecânicas pelo engenheiro eletricista/mecânico.",
        "Projeto aprovado junto à concessionária de energia (iluminação, subestações, fotovoltaico).",
        "ART de manutenção para elevadores, climatização (PMOC – Lei 13.589/2018) e SPDA.",
        "Prevenção de incêndio: projeto aprovado no Corpo de Bombeiros Militar de MS.",
    ],
    AREA_PROJETOS: [
        "ART de elaboração de projeto/laudo/consultoria por profissional registrado.",
        "Conferir se a pessoa jurídica contratada possui registro ativo no CREA-MS.",
        "Laudos e pareceres devem conter identificação e número da ART do signatário.",
    ],
}


def indicios_fiscalizacao(contrato: Dict) -> List[str]:
    """Gera lista de pontos de atenção para o fiscal a partir do contrato."""
    area = contrato.get("area") or AREA_NAO_TECNICA
    itens: List[str] = list(_INDICIOS_BASE.get(area, []))
    for sec in contrato.get("areas_secundarias") or []:
        for item in _INDICIOS_BASE.get(sec, [])[:1]:
            if item not in itens:
                itens.append(item)

    valor = contrato.get("valor_global") or 0
    if valor >= 1_500_000:
        itens.append("⚠️ Obra de grande porte (≥ R$ 1,5 mi): priorizar vistoria in loco e conferir medições.")
    if contrato.get("status_contrato") == "Não publicado no portal":
        itens.append("⚠️ Instrumento contratual não localizado no PNCP — solicitar cópia ao órgão.")
    if contrato.get("status_os") != "Documento localizado":
        itens.append("⚠️ Ordem de Serviço não localizada como anexo: verificar data real de início dos serviços.")
    if contrato.get("situacao") == "Paralisado / Suspenso":
        itens.append("⚠️ Contrato com indício de paralisação/suspensão: verificar responsabilidade técnica no período.")
    saldo = contrato.get("saldo_a_empenhar")
    if saldo is not None and valor and saldo > 0.5 * valor and contrato.get("situacao") == "Concluído":
        itens.append("⚠️ Vigência encerrada com mais de 50% do valor sem empenho identificado.")
    if not itens:
        itens.append("Objeto sem atribuição técnica evidente — avaliar necessidade de ART caso a caso.")
    return itens
