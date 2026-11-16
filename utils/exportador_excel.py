"""
Exportador Excel (.xlsx) estilizado — FiscalizaObras-MS.

Abas geradas:
  * Contratos            — tabela completa com hiperlinks (=HYPERLINK) para
                           Contrato, Ordem de Serviço e Empenho;
  * Resumo por Município — quantidade e valores agregados;
  * Resumo por Área      — distribuição por área de fiscalização;
  * Parâmetros           — filtros usados, data da extração e fontes.
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

AZUL_MS = "004B87"
VERDE_PANTANAL = "007A33"
AMARELO_OURO = "F2A900"
CINZA_BORDA = "DCE3EC"
CINZA_ZEBRA = "F5F7FA"

FMT_MOEDA = '_-"R$" * #,##0.00_-;-"R$" * #,##0.00_-;_-"R$" * "-"??_-;_-@_-'
FMT_DATA = "DD/MM/YYYY"

_borda = Side(style="thin", color=CINZA_BORDA)
BORDA = Border(left=_borda, right=_borda, top=_borda, bottom=_borda)
FONTE_CAB = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
PREENCH_CAB = PatternFill("solid", fgColor=AZUL_MS)
PREENCH_ZEBRA = PatternFill("solid", fgColor=CINZA_ZEBRA)
FONTE_LINK = Font(name="Calibri", color="0563C1", underline="single")

# (chave, título, tipo, largura máx.)
COLUNAS: List[Tuple[str, str, str, int]] = [
    ("municipio", "Município", "texto", 26),
    ("regiao", "Região / Fiscal", "texto", 16),
    ("codigo_ibge", "Cód. IBGE", "texto", 10),
    ("orgao", "Órgão Contratante", "texto", 40),
    ("numero_contrato", "Nº Contrato/Ano", "texto", 16),
    ("processo", "Processo Licitatório", "texto", 30),
    ("modalidade", "Modalidade", "texto", 26),
    ("fornecedor", "Contratada (Razão Social)", "texto", 45),
    ("cnpj_fornecedor", "CNPJ Contratada", "texto", 20),
    ("objeto", "Objeto", "longo", 80),
    ("area", "Área de Fiscalização", "texto", 34),
    ("situacao", "Situação", "texto", 22),
    ("valor_global", "Valor Global (R$)", "moeda", 20),
    ("valor_empenhado", "Valor Empenhado (R$)", "moeda", 20),
    ("saldo_a_empenhar", "Saldo a Empenhar (R$)", "moeda", 20),
    ("data_assinatura", "Data Assinatura", "data", 14),
    ("vigencia_inicio", "Vigência Início", "data", 14),
    ("vigencia_fim", "Vigência Término", "data", 14),
    ("url_contrato", "Contrato", "link", 14),
    ("status_contrato", "Status Contrato", "texto", 30),
    ("url_os", "Ordem de Serviço", "link", 16),
    ("status_os", "Status OS", "texto", 30),
    ("url_empenho", "Empenho", "link", 14),
    ("status_empenho", "Status Empenho", "texto", 30),
    ("url_pagina", "Página do Contrato", "link", 16),
    ("numero_controle_pncp", "Nº Controle PNCP", "texto", 30),
    ("fonte", "Fonte", "texto", 14),
]

ROTULO_LINK = {
    "url_contrato": "📄 Abrir Contrato",
    "url_os": "📋 Abrir OS",
    "url_empenho": "💰 Abrir Empenho",
    "url_pagina": "🔗 Página",
}


def _valor_celula(v: Any) -> Any:
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return v


def _escrever_cabecalho(ws: Worksheet, titulos: Iterable[str], linha: int) -> None:
    for col, titulo in enumerate(titulos, 1):
        cel = ws.cell(row=linha, column=col, value=titulo)
        cel.font, cel.fill, cel.border = FONTE_CAB, PREENCH_CAB, BORDA
        cel.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[linha].height = 32


def _faixa_titulo(ws: Worksheet, titulo: str, subtitulo: str, n_colunas: int) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(n_colunas, 2))
    c = ws.cell(row=1, column=1, value=titulo)
    c.font = Font(bold=True, size=14, color=AZUL_MS)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(n_colunas, 2))
    s = ws.cell(row=2, column=1, value=subtitulo)
    s.font = Font(italic=True, size=10, color="555555")
    # filete amarelo-ouro sutil
    for col in range(1, max(n_colunas, 2) + 1):
        ws.cell(row=3, column=col).fill = PatternFill("solid", fgColor=AMARELO_OURO)
    ws.row_dimensions[3].height = 3


def _ajustar_larguras(ws: Worksheet, maximos: Dict[int, int], linha_ini: int) -> None:
    for col_idx in range(1, ws.max_column + 1):
        letra = get_column_letter(col_idx)
        maior = 8
        for (cel,) in ws.iter_rows(min_row=linha_ini, min_col=col_idx, max_col=col_idx):
            v = cel.value
            if v is None:
                continue
            if isinstance(v, str) and v.startswith("=HYPERLINK"):
                comp = 18
            elif isinstance(v, (int, float)):
                comp = len(f"{v:,.2f}") + 6
            elif isinstance(v, datetime):
                comp = 11
            else:
                comp = max(len(p) for p in str(v).split("\n"))
            maior = max(maior, comp)
        ws.column_dimensions[letra].width = min(maior + 2, maximos.get(col_idx, 60))


def _link(cel, url: Optional[str], rotulo: str) -> None:
    if not url:
        cel.value = "—"
        return
    url = str(url)
    # HYPERLINK aceita até 255 caracteres por argumento; acima disso, usa hyperlink nativo
    if len(url) <= 250 and '"' not in url:
        cel.value = f'=HYPERLINK("{url}","{rotulo}")'
    else:
        cel.value = rotulo
        cel.hyperlink = url
    cel.font = FONTE_LINK


def _aba_contratos(wb: Workbook, contratos: List[Dict[str, Any]], subtitulo: str) -> None:
    ws = wb.active
    ws.title = "Contratos"
    _faixa_titulo(ws, "FiscalizaObras-MS — Contratos de Engenharia, Agronomia e Geociências", subtitulo, len(COLUNAS))
    linha_cab = 5
    _escrever_cabecalho(ws, [c[1] for c in COLUNAS], linha_cab)

    for i, contrato in enumerate(contratos):
        lin = linha_cab + 1 + i
        for col, (chave, _, tipo, _) in enumerate(COLUNAS, 1):
            cel = ws.cell(row=lin, column=col)
            v = contrato.get(chave)
            if tipo == "link":
                _link(cel, v, ROTULO_LINK.get(chave, "Abrir"))
            else:
                cel.value = _valor_celula(v) if v not in (None, "") else (None if tipo == "moeda" else "")
            if tipo == "moeda":
                cel.number_format = FMT_MOEDA
            elif tipo == "data":
                cel.number_format = FMT_DATA
                cel.alignment = Alignment(horizontal="center")
            elif tipo == "longo":
                cel.alignment = Alignment(wrap_text=True, vertical="top")
            cel.border = BORDA
            if i % 2 == 1:
                cel.fill = PREENCH_ZEBRA
            if chave == "situacao" and v:
                cor = VERDE_PANTANAL if v.startswith("Vigente") else ("B26B00" if "Paralis" in v else "555555")
                cel.font = Font(bold=True, color=cor)
            if chave.startswith("status_") and v and "Não publicado" in str(v):
                cel.font = Font(color="B00020")

    ultima = linha_cab + len(contratos)
    if contratos:
        # linha de totais com fórmulas
        tot = ultima + 1
        ws.cell(row=tot, column=1, value="TOTAL").font = Font(bold=True, color=AZUL_MS)
        for col, (chave, _, tipo, _) in enumerate(COLUNAS, 1):
            if tipo == "moeda":
                letra = get_column_letter(col)
                cel = ws.cell(row=tot, column=col, value=f"=SUBTOTAL(9,{letra}{linha_cab + 1}:{letra}{ultima})")
                cel.number_format, cel.font = FMT_MOEDA, Font(bold=True, color=AZUL_MS)
                cel.border = Border(top=Side(style="medium", color=AZUL_MS))
        ws.auto_filter.ref = f"A{linha_cab}:{get_column_letter(len(COLUNAS))}{ultima}"
    ws.freeze_panes = ws.cell(row=linha_cab + 1, column=2)
    _ajustar_larguras(ws, {i + 1: c[3] for i, c in enumerate(COLUNAS)}, linha_cab)
    for lin in range(linha_cab + 1, ultima + 1):
        ws.row_dimensions[lin].height = 45


def _agrupar(contratos: List[Dict[str, Any]], chave: str) -> List[Tuple[str, int, float, float]]:
    grupos: Dict[str, List[float]] = {}
    for c in contratos:
        g = grupos.setdefault(c.get(chave) or "—", [0, 0.0, 0.0])
        g[0] += 1
        g[1] += c.get("valor_global") or 0.0
        g[2] += c.get("valor_empenhado") or 0.0
    return sorted(((k, int(v[0]), v[1], v[2]) for k, v in grupos.items()), key=lambda t: t[2], reverse=True)


def _aba_resumo(wb: Workbook, titulo_aba: str, rotulo: str, linhas: List[Tuple[str, int, float, float]],
                subtitulo: str) -> None:
    ws = wb.create_sheet(titulo_aba)
    _faixa_titulo(ws, f"Resumo por {rotulo}", subtitulo, 5)
    cab = 5
    _escrever_cabecalho(ws, [rotulo, "Qtde. Contratos", "Valor Global (R$)", "Valor Empenhado (R$)", "% do Total"], cab)
    for i, (nome, qtd, vg, ve) in enumerate(linhas):
        lin = cab + 1 + i
        valores = [nome, qtd, vg, ve or None, None]
        for col, v in enumerate(valores, 1):
            cel = ws.cell(row=lin, column=col, value=v)
            cel.border = BORDA
            if i % 2:
                cel.fill = PREENCH_ZEBRA
        ws.cell(row=lin, column=3).number_format = FMT_MOEDA
        ws.cell(row=lin, column=4).number_format = FMT_MOEDA
    fim = cab + len(linhas)
    tot = fim + 1
    ws.cell(row=tot, column=1, value="TOTAL").font = Font(bold=True, color=AZUL_MS)
    for col, fmt in ((2, "0"), (3, FMT_MOEDA), (4, FMT_MOEDA)):
        letra = get_column_letter(col)
        cel = ws.cell(row=tot, column=col, value=f"=SUM({letra}{cab + 1}:{letra}{fim})" if linhas else 0)
        cel.number_format, cel.font = fmt, Font(bold=True, color=AZUL_MS)
    for lin in range(cab + 1, fim + 1):
        cel = ws.cell(row=lin, column=5, value=f"=IF($C${tot}=0,0,C{lin}/$C${tot})")
        cel.number_format, cel.border = "0.0%", BORDA
    ws.freeze_panes = f"A{cab + 1}"
    _ajustar_larguras(ws, {1: 48, 2: 16, 3: 22, 4: 22, 5: 12}, cab)


def _aba_parametros(wb: Workbook, filtros: Dict[str, Any], avisos: List[str]) -> None:
    ws = wb.create_sheet("Parâmetros")
    _faixa_titulo(ws, "Parâmetros da Consulta", "Rastreabilidade da extração", 2)
    linhas = [("Gerado em", datetime.now().strftime("%d/%m/%Y %H:%M"))]
    linhas += [(str(k), ", ".join(map(str, v)) if isinstance(v, (list, tuple, set)) else str(v)) for k, v in filtros.items()]
    linhas += [
        ("Fonte primária", "PNCP — Portal Nacional de Contratações Públicas (https://pncp.gov.br)"),
        ("Fontes complementares", "Portais da Transparência municipais (quando configurados)"),
        ("Observação", "Links com status 'Disponível na página do contrato' abrem o detalhamento no PNCP, "
                       "onde o documento deve ser localizado manualmente."),
    ]
    for aviso in avisos:
        linhas.append(("Aviso", aviso))
    _escrever_cabecalho(ws, ["Parâmetro", "Valor"], 5)
    for i, (k, v) in enumerate(linhas):
        a = ws.cell(row=6 + i, column=1, value=k)
        b = ws.cell(row=6 + i, column=2, value=v)
        a.font = Font(bold=True)
        b.alignment = Alignment(wrap_text=True, vertical="top")
        a.border = b.border = BORDA
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 110


def gerar_planilha(
    contratos: List[Dict[str, Any]],
    filtros: Optional[Dict[str, Any]] = None,
    avisos: Optional[List[str]] = None,
) -> bytes:
    """Gera o arquivo .xlsx em memória e devolve os bytes."""
    filtros = filtros or {}
    subtitulo = (
        f"Exercício {filtros.get('Exercício', '')} • {len(contratos)} contrato(s) • "
        f"extraído em {datetime.now():%d/%m/%Y %H:%M} • Fonte: PNCP"
    )
    wb = Workbook()
    _aba_contratos(wb, contratos, subtitulo)
    _aba_resumo(wb, "Resumo por Município", "Município", _agrupar(contratos, "municipio"), subtitulo)
    _aba_resumo(wb, "Resumo por Área", "Área de Fiscalização", _agrupar(contratos, "area"), subtitulo)
    _aba_parametros(wb, filtros, avisos or [])
    wb.properties.title = "FiscalizaObras-MS — Contratos"
    wb.properties.creator = "FiscalizaObras-MS"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
