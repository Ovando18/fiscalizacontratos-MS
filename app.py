"""
FiscalizaObras-MS — Painel de inteligência e fiscalização de contratos públicos
de Engenharia, Agronomia e Geociências nos municípios de Mato Grosso do Sul.

Execução local:  streamlit run app.py
"""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import streamlit as st

from config.regioes_ms import (
    FISCAIS_FIXOS,
    MUNICIPIOS,
    OPCAO_TODOS_REGIAO,
    REGIOES,
    Municipio,
)
from scrapers.coletor_contratos import (
    SITUACOES,
    STATUS_DOC_AUSENTE,
    STATUS_DOC_OK,
    coletar_contratos,
)
from utils.classificador_tecnico import AREAS_FISCALIZACAO, pertence_a_area, indicios_fiscalizacao
from utils.exportador_excel import gerar_planilha

logging.getLogger("urllib3").setLevel(logging.ERROR)  # retries transitórios do PNCP

AZUL = "#004B87"
VERDE = "#007A33"
OURO = "#F2A900"
CACHE_TTL_SEGUNDOS = 6 * 3600
EXERCICIO_ATUAL = date.today().year

st.set_page_config(
    page_title="FiscalizaObras-MS",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Identidade visual — Mato Grosso do Sul (sóbria e institucional)
# ---------------------------------------------------------------------------
st.markdown(
    f"""
<style>
:root {{
  --azul-ms: {AZUL}; --verde-pantanal: {VERDE}; --ouro: {OURO};
  --fundo: #F5F7FA; --cartao: #FFFFFF; --borda: #DCE3EC; --texto: #1F2A37; --texto-2: #5B6776;
}}
#MainMenu, footer {{ visibility: hidden; }}
[data-testid="stToolbar"] {{ display: none; }}
header[data-testid="stHeader"] {{ background: transparent; height: 2.5rem; }}
.stApp {{ background: var(--fundo); color: var(--texto); }}
.block-container {{ padding-top: 2.2rem; padding-bottom: 2rem; max-width: 1500px; }}
h1, h2, h3, h4 {{ color: var(--azul-ms); }}

section[data-testid="stSidebar"] {{ background: #FFFFFF; border-right: 1px solid var(--borda); }}
section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {{ color: var(--azul-ms); }}

.fo-header {{
  background: var(--azul-ms); color: #fff; border-radius: 10px; padding: 18px 24px;
  border-bottom: 3px solid var(--ouro); margin-bottom: 18px;
  display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap;
}}
.fo-header h1 {{ color: #fff; font-size: 1.55rem; margin: 0; line-height: 1.25; }}
.fo-header p {{ margin: 4px 0 0; opacity: .88; font-size: .92rem; }}
.fo-header .fo-selo {{ font-size: .78rem; border: 1px solid rgba(255,255,255,.45); border-radius: 999px;
  padding: 4px 12px; white-space: nowrap; }}

.fo-bloco {{ border: 1px solid var(--borda); border-left: 4px solid var(--azul-ms); border-radius: 8px;
  padding: 10px 12px 4px; margin-bottom: 12px; background: #FBFCFE; }}
.fo-bloco.fixo {{ border-left-color: var(--verde-pantanal); }}
.fo-bloco-titulo {{ font-weight: 700; color: var(--azul-ms); font-size: .9rem; margin-bottom: 4px; }}
.fo-bloco.fixo .fo-bloco-titulo {{ color: var(--verde-pantanal); }}

.fo-kpi {{ background: var(--cartao); border: 1px solid var(--borda); border-top: 3px solid var(--azul-ms);
  border-radius: 10px; padding: 14px 16px; height: 100%; }}
.fo-kpi.verde {{ border-top-color: var(--verde-pantanal); }}
.fo-kpi .rotulo {{ color: var(--texto-2); font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; }}
.fo-kpi .valor {{ color: var(--texto); font-size: 1.55rem; font-weight: 700; margin-top: 4px;
  font-variant-numeric: tabular-nums; }}
.fo-kpi .nota {{ color: var(--texto-2); font-size: .78rem; margin-top: 2px; }}

.fo-secao {{ color: var(--azul-ms); font-weight: 700; font-size: 1.1rem; margin: 18px 0 8px;
  padding-bottom: 6px; border-bottom: 1px solid var(--borda); }}
.fo-cartao {{ background: var(--cartao); border: 1px solid var(--borda); border-radius: 10px; padding: 16px 18px; }}
.fo-grade {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px 22px; }}
.fo-campo .k {{ color: var(--texto-2); font-size: .74rem; text-transform: uppercase; letter-spacing: .03em; }}
.fo-campo .v {{ color: var(--texto); font-size: .95rem; font-weight: 600; word-break: break-word; }}
.fo-badge {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600; }}
.fo-badge.vigente {{ background: #E6F2EA; color: var(--verde-pantanal); }}
.fo-badge.paralisado {{ background: #FFF4D6; color: #8A5A00; }}
.fo-badge.concluido {{ background: #EEF1F5; color: #4A5563; }}
.fo-doc {{ font-size: .8rem; color: var(--texto-2); margin-top: 4px; }}
.fo-doc.ok {{ color: var(--verde-pantanal); }}
.fo-doc.ausente {{ color: #B00020; }}
.fo-alerta {{ border-left: 3px solid var(--ouro); background: #FFFBEF; padding: 8px 12px; border-radius: 6px;
  font-size: .88rem; margin: 6px 0; }}
.fo-indicio {{ border-left: 3px solid var(--verde-pantanal); background: #F3F9F5; padding: 7px 12px;
  border-radius: 6px; font-size: .88rem; margin: 5px 0; }}
.fo-indicio.atencao {{ border-left-color: var(--ouro); background: #FFFBEF; }}

.stButton > button[kind="primary"], .stDownloadButton > button {{
  background: var(--azul-ms); border-color: var(--azul-ms); color: #fff; }}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button:hover {{
  background: #003A6A; border-color: #003A6A; color: #fff; }}
.stLinkButton a {{ border-color: var(--azul-ms) !important; color: var(--azul-ms) !important; font-weight: 600; }}
.stLinkButton a:hover {{ background: var(--azul-ms) !important; color: #fff !important; }}
@media (max-width: 640px) {{ .fo-header h1 {{ font-size: 1.2rem; }} .fo-kpi .valor {{ font-size: 1.25rem; }} }}
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------
def brl(v: Optional[float]) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/d"
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def brl_compacto(v: float) -> str:
    if v >= 1e9:
        return f"R$ {v / 1e9:,.2f} bi".replace(".", ",")
    if v >= 1e6:
        return f"R$ {v / 1e6:,.2f} mi".replace(".", ",")
    return brl(v)


def dt(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return "—"
    if isinstance(v, (date, datetime, pd.Timestamp)):
        return v.strftime("%d/%m/%Y")
    return str(v)


def esc(v: Any) -> str:
    return html.escape(str(v if v not in (None, "") else "—"))


# ---------------------------------------------------------------------------
# Cache compartilhado (entre sessões) com TTL — permite barra de progresso real
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _cache_coletas() -> Dict[tuple, tuple]:
    return {}


def executar_coleta(municipios: List[Municipio], exercicio: int, incluir_nao_tecnicos: bool, usar_cnae: bool):
    chave = (tuple(sorted(m.nome for m in municipios)), exercicio, incluir_nao_tecnicos, usar_cnae)
    cache = _cache_coletas()
    hit = cache.get(chave)
    if hit and time.time() - hit[0] < CACHE_TTL_SEGUNDOS:
        return hit[1], datetime.fromtimestamp(hit[0])

    barra = st.progress(0.0, text="Iniciando consulta ao PNCP…")

    def progresso(frac: float, msg: str) -> None:
        barra.progress(min(max(frac, 0.0), 1.0), text=msg)

    resultado = coletar_contratos(
        municipios, exercicio, incluir_nao_tecnicos=incluir_nao_tecnicos,
        enriquecer_cnae_fornecedor=usar_cnae, progresso=progresso,
    )
    barra.empty()
    agora = time.time()
    cache[chave] = (agora, resultado)
    return resultado, datetime.fromtimestamp(agora)


# ---------------------------------------------------------------------------
# Cabeçalho
# ---------------------------------------------------------------------------
st.markdown(
    """
<div class="fo-header">
  <div>
    <h1>🏗️ FiscalizaObras-MS</h1>
    <p>Inteligência para fiscalização de contratos de Engenharia, Agronomia e Geociências
       nos municípios de Mato Grosso do Sul</p>
  </div>
  <span class="fo-selo">Fonte oficial: PNCP • Lei 14.133/2021</span>
</div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Barra lateral — seleção geográfica e filtros
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🗺️ Seleção Geográfica")

    # Bloco A — Fiscais Fixos
    st.markdown('<div class="fo-bloco fixo"><div class="fo-bloco-titulo">'
                '📍 Bloco A — Municípios com Fiscais Fixos</div></div>', unsafe_allow_html=True)
    fixos_sel = st.multiselect(
        "Município(s) com fiscal fixo",
        options=FISCAIS_FIXOS,
        default=[],
        placeholder="Selecione um ou mais municípios",
        help="Pesquisa individual e separada, fora da numeração das regiões.",
    )

    # Bloco B — Regiões numeradas
    st.markdown('<div class="fo-bloco"><div class="fo-bloco-titulo">'
                '🧭 Bloco B — Pesquisa por Região (1 a 18)</div></div>', unsafe_allow_html=True)
    regiao_sel = st.selectbox(
        "Número da Região",
        options=list(REGIOES.keys()),
        index=None,
        format_func=lambda n: f"Região {n:02d} — {len(REGIOES[n])} municípios",
        placeholder="Selecione a região (1 a 18)",
    )
    municipios_regiao_sel: List[str] = []
    if regiao_sel is not None:
        nomes_regiao = REGIOES[regiao_sel]
        escolha = st.multiselect(
            f"Municípios da Região {regiao_sel:02d}",
            options=[OPCAO_TODOS_REGIAO] + nomes_regiao,
            default=[OPCAO_TODOS_REGIAO],
            key=f"mun_regiao_{regiao_sel}",
        )
        if OPCAO_TODOS_REGIAO in escolha or not escolha:
            municipios_regiao_sel = list(nomes_regiao)
        else:
            municipios_regiao_sel = [n for n in nomes_regiao if n in escolha]
        st.caption("Abrange: " + ", ".join(n.title() for n in municipios_regiao_sel))

    st.markdown("## 🎛️ Filtros")
    exercicio = st.number_input(
        "Exercício Financeiro", min_value=2021, max_value=EXERCICIO_ATUAL, value=EXERCICIO_ATUAL, step=1,
        help="O PNCP é obrigatório desde a Lei 14.133/2021; padrão: exercício atual.",
    )
    area_sel = st.selectbox("Área de Fiscalização", AREAS_FISCALIZACAO, index=0)
    c1, c2 = st.columns(2)
    valor_min = c1.number_input("Valor mín. (R$)", min_value=0.0, value=0.0, step=50_000.0, format="%.2f")
    valor_max = c2.number_input("Valor máx. (R$)", min_value=0.0, value=0.0, step=50_000.0, format="%.2f",
                                help="0 = sem limite superior")
    situacao_sel = st.selectbox("Status / Situação", SITUACOES, index=0)
    busca = st.text_input(
        "Busca textual (Objeto, Empresa ou CNPJ)",
        placeholder='ex.: pavimentação, drenagem, ponte, 12.345.678/0001-90',
    )
    with st.expander("⚙️ Opções avançadas"):
        incluir_nao_tecnicos = st.checkbox(
            "Incluir contratos sem atribuição técnica", value=False,
            help="Mostra também compras e serviços comuns (útil para auditoria ampla).",
        )
        usar_cnae = st.checkbox(
            "Refinar classificação pelo CNAE da contratada (BrasilAPI)", value=False,
            help="Faz uma consulta por CNPJ; deixa a pesquisa mais lenta.",
        )

    pesquisar = st.button("🔎 Pesquisar contratos", type="primary", width="stretch")
    st.caption("Dados públicos do Portal Nacional de Contratações Públicas (PNCP), "
               "complementados pelos portais municipais configurados.")

# Municípios efetivamente selecionados (sem duplicidade, mantendo ordem)
nomes_selecionados = list(dict.fromkeys(fixos_sel + municipios_regiao_sel))
municipios_selecionados = [MUNICIPIOS[n] for n in nomes_selecionados]

if pesquisar:
    if not municipios_selecionados:
        st.warning("Selecione ao menos um município no **Bloco A** (Fiscais Fixos) ou uma região no **Bloco B**.")
    else:
        try:
            resultado, quando = executar_coleta(municipios_selecionados, int(exercicio),
                                                incluir_nao_tecnicos, usar_cnae)
            st.session_state["resultado"] = resultado
            st.session_state["consulta"] = {
                "municipios": nomes_selecionados, "exercicio": int(exercicio), "quando": quando,
            }
        except Exception as exc:  # noqa: BLE001
            st.error(f"Não foi possível concluir a consulta ao PNCP: {exc}. Tente novamente em instantes.")

resultado = st.session_state.get("resultado")
consulta = st.session_state.get("consulta")

if resultado is None:
    st.markdown('<div class="fo-secao">Como usar</div>', unsafe_allow_html=True)
    col_a, col_b, col_c = st.columns(3)
    col_a.markdown('<div class="fo-cartao"><b>1. Onde fiscalizar</b><br>Escolha municípios com '
                   '<b>Fiscal Fixo</b> (Bloco A) e/ou uma <b>Região</b> de 1 a 18 (Bloco B).</div>',
                   unsafe_allow_html=True)
    col_b.markdown('<div class="fo-cartao"><b>2. O que procurar</b><br>Refine por área técnica, faixa de '
                   'valor, situação do contrato ou termos como <i>pavimentação</i> ou um CNPJ.</div>',
                   unsafe_allow_html=True)
    col_c.markdown('<div class="fo-cartao"><b>3. Agir</b><br>Abra Contrato, Ordem de Serviço e Empenho, '
                   'consulte os indícios de ART e exporte a planilha <b>.xlsx</b>.</div>',
                   unsafe_allow_html=True)
    st.info("A primeira consulta de um conjunto de municípios pode levar alguns minutos — a API do PNCP é lenta. "
            "Consultas repetidas usam cache por 6 horas.")
    st.stop()

# ---------------------------------------------------------------------------
# Aplicação dos filtros sobre o resultado coletado
# ---------------------------------------------------------------------------
if consulta and (set(consulta["municipios"]) != set(nomes_selecionados)
                or consulta["exercicio"] != int(exercicio)):
    st.markdown('<div class="fo-alerta">A seleção geográfica ou o exercício mudou. '
                'Clique em <b>🔎 Pesquisar contratos</b> para atualizar os dados.</div>', unsafe_allow_html=True)

contratos: List[Dict[str, Any]] = resultado.contratos
termo = (busca or "").strip().lower()
termo_digitos = re.sub(r"\D", "", termo)


def passa_filtros(c: Dict[str, Any]) -> bool:
    if area_sel != "Todas" or not incluir_nao_tecnicos:
        if not pertence_a_area(c["area"], c["areas_secundarias"], area_sel):
            return False
    v = c.get("valor_global") or 0
    if v < valor_min or (valor_max > 0 and v > valor_max):
        return False
    if situacao_sel != "Todos" and c.get("situacao") != situacao_sel:
        return False
    if termo:
        alvo = f"{c['objeto']} {c['fornecedor']} {c['orgao']} {c['numero_contrato']} {c['processo']}".lower()
        cnpj_ok = len(termo_digitos) >= 5 and termo_digitos in re.sub(r"\D", "", c["cnpj_fornecedor"])
        if termo not in alvo and not cnpj_ok:
            return False
    return True


filtrados = [c for c in contratos if passa_filtros(c)]

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
total_global = sum(c["valor_global"] or 0 for c in filtrados)
emp_vals = [c["valor_empenhado"] for c in filtrados if c.get("valor_empenhado") is not None]
total_emp = sum(emp_vals)
mun_ativos = {c["municipio"] for c in filtrados if c["situacao"] != "Concluído"}

st.markdown(
    f'<div class="fo-secao">Resumo Executivo — Exercício {consulta["exercicio"]}'
    f'<span style="float:right;font-weight:400;font-size:.8rem;color:#5B6776">'
    f'Atualizado em {consulta["quando"]:%d/%m/%Y %H:%M}</span></div>',
    unsafe_allow_html=True,
)
k1, k2, k3, k4 = st.columns(4)
k1.markdown(f'<div class="fo-kpi"><div class="rotulo">Contratos encontrados</div>'
            f'<div class="valor">{len(filtrados):,}</div>'
            f'<div class="nota">de {resultado.total_bruto:,} publicados no PNCP</div></div>'.replace(",", "."),
            unsafe_allow_html=True)
k2.markdown(f'<div class="fo-kpi"><div class="rotulo">Valor global contratado</div>'
            f'<div class="valor">{brl_compacto(total_global)}</div>'
            f'<div class="nota">{brl(total_global)}</div></div>', unsafe_allow_html=True)
k3.markdown(f'<div class="fo-kpi verde"><div class="rotulo">Total empenhado</div>'
            f'<div class="valor">{brl_compacto(total_emp) if emp_vals else "n/d"}</div>'
            f'<div class="nota">{len(emp_vals)} com empenho no PNCP</div></div>',
            unsafe_allow_html=True)
k4.markdown(f'<div class="fo-kpi verde"><div class="rotulo">Municípios com obras ativas</div>'
            f'<div class="valor">{len(mun_ativos)}</div>'
            f'<div class="nota">de {len(consulta["municipios"])} pesquisado(s)</div></div>',
            unsafe_allow_html=True)

if resultado.municipios_sem_orgao:
    st.markdown(
        '<div class="fo-alerta">Sem publicações municipais no PNCP para o exercício: '
        + ", ".join(n.title() for n in sorted(resultado.municipios_sem_orgao))
        + '. Consulte o portal da transparência local.</div>', unsafe_allow_html=True)
if resultado.avisos:
    with st.expander(f"ℹ️ Avisos da coleta ({len(resultado.avisos)})"):
        for a in resultado.avisos:
            st.write("• " + a)

if not filtrados:
    st.info("Nenhum contrato atende aos filtros. Experimente ampliar a faixa de valor, a área ou a situação.")
    st.stop()

# ---------------------------------------------------------------------------
# Gráficos (série única, cor institucional)
# ---------------------------------------------------------------------------
df = pd.DataFrame(filtrados)
g1, g2 = st.columns(2)
por_mun = (df.groupby("municipio", as_index=False)["valor_global"].sum()
           .sort_values("valor_global", ascending=True).tail(15))
por_mun["rotulo"] = por_mun["valor_global"].map(brl)
fig1 = px.bar(por_mun, x="valor_global", y="municipio", orientation="h",
              custom_data=["rotulo"], title="Valor global contratado por município")
fig1.update_traces(marker_color=AZUL, hovertemplate="<b>%{y}</b><br>%{customdata[0]}<extra></extra>")
por_area = df.groupby("area", as_index=False).agg(qtd=("id", "count")).sort_values("qtd")
fig2 = px.bar(por_area, x="qtd", y="area", orientation="h", title="Contratos por área de fiscalização")
fig2.update_traces(marker_color=VERDE, hovertemplate="<b>%{y}</b><br>%{x} contrato(s)<extra></extra>")
for fig in (fig1, fig2):
    fig.update_layout(
        height=max(260, 34 * len(fig.data[0].y) + 90), margin=dict(l=8, r=16, t=48, b=8),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", font=dict(color="#1F2A37"),
        title_font=dict(color=AZUL, size=15), xaxis_title=None, yaxis_title=None, bargap=0.35,
    )
    fig.update_xaxes(gridcolor="#EEF1F5", zeroline=False)
fig1.update_xaxes(tickprefix="R$ ", tickformat="~s")
g1.plotly_chart(fig1, width="stretch", config={"displayModeBar": False})
g2.plotly_chart(fig2, width="stretch", config={"displayModeBar": False})

# ---------------------------------------------------------------------------
# Tabela interativa
# ---------------------------------------------------------------------------
st.markdown('<div class="fo-secao">Contratos</div>', unsafe_allow_html=True)
tabela = pd.DataFrame({
    "Município": df["municipio"],
    "Região": df["regiao"],
    "Nº Contrato": df["numero_contrato"],
    "Contratada": df["fornecedor"],
    "CNPJ": df["cnpj_fornecedor"],
    "Objeto": df["objeto"],
    "Área": df["area"],
    "Situação": df["situacao"],
    "Valor Global (R$)": df["valor_global"],
    "Empenhado (R$)": df["valor_empenhado"],
    "Assinatura": pd.to_datetime(df["data_assinatura"], errors="coerce"),
    "Vigência até": pd.to_datetime(df["vigencia_fim"], errors="coerce"),
    "Contrato": df["url_contrato"],
    "Ordem de Serviço": df["url_os"],
    "Empenho": df["url_empenho"],
    "Modalidade": df["modalidade"],
    "Processo": df["processo"],
})
st.dataframe(
    tabela,
    width="stretch",
    hide_index=True,
    height=min(560, 38 * (len(tabela) + 1) + 4),
    column_config={
        "Objeto": st.column_config.TextColumn(width="large"),
        "Valor Global (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Empenhado (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Assinatura": st.column_config.DateColumn(format="DD/MM/YYYY"),
        "Vigência até": st.column_config.DateColumn(format="DD/MM/YYYY"),
        "Contrato": st.column_config.LinkColumn(display_text="📄 Abrir"),
        "Ordem de Serviço": st.column_config.LinkColumn(display_text="📋 Abrir"),
        "Empenho": st.column_config.LinkColumn(display_text="💰 Abrir"),
    },
)
st.caption("Quando o anexo não está publicado, o link abre a página de detalhamento do contrato no PNCP. "
           "O status de cada anexo aparece no Inspetor e na planilha.")

filtros_export = {
    "Exercício": consulta["exercicio"],
    "Fiscais Fixos": fixos_sel or "—",
    "Região": f"{regiao_sel:02d}" if regiao_sel else "—",
    "Municípios": consulta["municipios"],
    "Área": area_sel,
    "Valor mín. (R$)": brl(valor_min),
    "Valor máx. (R$)": brl(valor_max) if valor_max else "sem limite",
    "Situação": situacao_sel,
    "Busca textual": busca or "—",
}
st.download_button(
    "📥 Exportar para Excel (.xlsx)",
    data=gerar_planilha(filtrados, filtros_export, resultado.avisos),
    file_name=f"FiscalizaObras-MS_{consulta['exercicio']}_{datetime.now():%Y%m%d_%H%M}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# ---------------------------------------------------------------------------
# Inspetor de contrato específico
# ---------------------------------------------------------------------------
st.markdown('<div class="fo-secao">🔍 Inspetor de Contrato</div>', unsafe_allow_html=True)
opcoes = {c["id"]: c for c in filtrados}
sel_id = st.selectbox(
    "Escolha um contrato para o detalhamento técnico",
    options=list(opcoes.keys()),
    format_func=lambda i: (f"{opcoes[i]['municipio'].title()} • Nº {opcoes[i]['numero_contrato']} • "
                           f"{opcoes[i]['fornecedor'][:40]} • {brl(opcoes[i]['valor_global'])}"),
)
c = opcoes[sel_id]
classe_sit = {"Vigente / Em Execução": "vigente", "Paralisado / Suspenso": "paralisado"}.get(c["situacao"], "concluido")


def campo(k: str, v: Any) -> str:
    return f'<div class="fo-campo"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>'


saldo = c.get("saldo_a_empenhar")
st.markdown(
    f"""
<div class="fo-cartao">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px">
    <div style="font-weight:700;color:{AZUL};font-size:1.05rem">Contrato nº {esc(c['numero_contrato'])} —
      {esc(c['municipio'].title())} <span style="color:#5B6776;font-weight:400">({esc(c['regiao'])})</span></div>
    <span class="fo-badge {classe_sit}">{esc(c['situacao'])}</span>
  </div>
  <div style="margin-bottom:12px"><div class="fo-campo"><div class="k">Objeto</div>
    <div class="v" style="font-weight:500">{esc(c['objeto'])}</div></div></div>
  <div class="fo-grade">
    {campo("Órgão contratante", c['orgao'])}
    {campo("CNPJ do órgão", c['cnpj_orgao'])}
    {campo("Contratada", c['fornecedor'])}
    {campo("CNPJ da contratada", c['cnpj_fornecedor'])}
    {campo("Processo licitatório", c['processo'])}
    {campo("Modalidade", c['modalidade'] or 'n/d')}
    {campo("Instrumento", c['tipo_instrumento'])}
    {campo("Área de fiscalização", c['area'])}
    {campo("Valor global", brl(c['valor_global']))}
    {campo("Valor empenhado", brl(c['valor_empenhado']))}
    {campo("Saldo a empenhar", brl(saldo) if saldo is not None else 'n/d (empenhos não publicados)')}
    {campo("Data de assinatura", dt(c['data_assinatura']))}
    {campo("Vigência", f"{dt(c['vigencia_inicio'])} a {dt(c['vigencia_fim'])}")}
    {campo("Termos aditivos", len(c.get('termos_aditivos') or []))}
    {campo("Nº controle PNCP", c['numero_controle_pncp'])}
    {campo("Fonte", c['fonte'])}
  </div>
</div>
""",
    unsafe_allow_html=True,
)

st.write("")
b1, b2, b3 = st.columns(3)
for col, chave, rotulo in ((b1, "contrato", "📄 Baixar/Abrir Contrato"),
                           (b2, "os", "📋 Baixar/Abrir Ordem de Serviço"),
                           (b3, "empenho", "💰 Baixar/Abrir Empenho(s)")):
    status = c[f"status_{chave}"]
    classe = "ok" if status == STATUS_DOC_OK else ("ausente" if status == STATUS_DOC_AUSENTE else "")
    col.link_button(rotulo, c[f"url_{chave}"], width="stretch")
    col.markdown(f'<div class="fo-doc {classe}">Status: {esc(status)}</div>', unsafe_allow_html=True)

d1, d2 = st.columns([3, 2])
with d1:
    st.markdown('<div class="fo-secao">Indícios técnicos para fiscalização</div>', unsafe_allow_html=True)
    for item in indicios_fiscalizacao(c):
        classe = "atencao" if item.startswith("⚠️") else ""
        st.markdown(f'<div class="fo-indicio {classe}">{esc(item)}</div>', unsafe_allow_html=True)
    if c.get("motivo_classificacao"):
        st.caption("Critério da classificação: " + c["motivo_classificacao"])
with d2:
    st.markdown('<div class="fo-secao">Documentos e empenhos</div>', unsafe_allow_html=True)
    docs = c.get("documentos") or []
    if docs:
        for d in docs:
            st.markdown(f"- [{esc(d.get('titulo') or d.get('tipo'))}]({d['url']}) — *{esc(d.get('tipo'))}*")
    else:
        st.caption("Nenhum anexo publicado no PNCP para este contrato.")
    for e in c.get("empenhos") or []:
        valor = f" — {brl(e['valor'])}" if e.get("valor") is not None else ""
        st.markdown(f"- 💰 [{esc(e['descricao'])}]({e['url']}){valor}")
    for t in c.get("termos_aditivos") or []:
        st.markdown(f"- 📝 Termo {esc(t['numero'])} ({dt(t['assinatura'])}): {esc((t['objeto'] or '')[:160])}")
    st.link_button("🔗 Página do contrato no PNCP", c["url_pagina"], width="stretch")
    st.link_button(f"🏛️ Site oficial de {c['municipio'].title()}", c["url_portal_municipal"],
                   width="stretch")
