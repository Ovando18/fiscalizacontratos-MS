"""Testes offline (sem rede) da base geográfica, classificador, coletor e exportador."""

import sys
from datetime import date
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import load_workbook  # noqa: E402

from config.regioes_ms import FISCAIS_FIXOS, MUNICIPIOS, REGIOES, obter_municipio, validar_base  # noqa: E402
from scrapers import coletor_contratos as cc  # noqa: E402
from utils.classificador_tecnico import (  # noqa: E402
    AREA_AGRO, AREA_CIVIL, AREA_GEO, AREA_NAO_TECNICA, classificar, indicios_fiscalizacao,
)
from utils.exportador_excel import gerar_planilha  # noqa: E402


def test_base_geografica_integra():
    assert validar_base() == []
    assert len(MUNICIPIOS) == 79
    assert len(REGIOES) == 18
    assert all(MUNICIPIOS[n].fiscal_fixo for n in FISCAIS_FIXOS)
    assert obter_municipio("tres lagoas").codigo_ibge == "5008305"
    assert MUNICIPIOS["DOURADOS"].codigo_ibge == "5003702"
    assert MUNICIPIOS["ANGÉLICA"].rotulo_regiao == "Região 01"


def test_classificador_areas():
    assert classificar("Pavimentação asfáltica e drenagem de águas pluviais").area == AREA_CIVIL
    assert classificar("Serviço de georreferenciamento de imóveis rurais").area == AREA_GEO
    assert classificar("Recuperação de áreas degradadas e reflorestamento").area == AREA_AGRO
    assert classificar("Aquisição de gêneros alimentícios para merenda").area == AREA_NAO_TECNICA
    assert classificar("Construção do CAPS", "Obras").tecnico


BRUTO = {
    "numeroControlePncpCompra": "03155926000144-1-000135/2025",
    "orgaoEntidade": {"cnpj": "03155926000144", "razaoSocial": "MUNICIPIO DE DOURADOS", "esferaId": "M"},
    "anoContrato": 2026, "sequencialContrato": 2, "numeroContratoEmpenho": "11",
    "tipoContrato": {"id": 1, "nome": "Contrato (termo inicial)"},
    "categoriaProcesso": {"id": 7, "nome": "Obras"},
    "objetoContrato": "Construção do Centro de Atenção Psicossocial no Município de Dourados-MS.",
    "valorGlobal": 4825527.58, "dataAssinatura": "2026-01-09",
    "dataVigenciaInicio": "2026-01-09", "dataVigenciaFim": "2099-01-09",
    "niFornecedor": "12345678000190", "nomeRazaoSocialFornecedor": "EMPRESA TESTE ENGENHARIA LTDA",
    "numeroControlePNCP": "03155926000144-2-000002/2026", "processo": "101/2025",
}


def test_normalizacao_e_enriquecimento(monkeypatch):
    mun = MUNICIPIOS["DOURADOS"]
    c = cc.normalizar_contrato_pncp(BRUTO, mun)
    assert c["cnpj_fornecedor"] == "12.345.678/0001-90"
    assert c["numero_contrato"] == "11/2026"
    assert c["situacao"] == cc.SITUACAO_VIGENTE
    assert c["area"] == AREA_CIVIL

    class Fake(cc.ClientePNCP):
        def arquivos(self, *a):
            return [{"url": "https://x/arq/1", "titulo": "Contrato 11", "tipoDocumentoNome": "Contrato"},
                    {"url": "https://x/arq/2", "titulo": "Ordem de Serviço 01", "tipoDocumentoNome": "Outros"}]

        def termos(self, *a):
            return [{"numeroTermoContrato": "1/2026", "objetoTermoContrato": "Suspensão temporária da obra",
                     "dataVigenciaFim": None}]

        def compra(self, *a):
            return {"modalidadeNome": "Concorrência - Eletrônica", "numeroCompra": "CE 10", "anoCompra": 2025}

    cc.enriquecer_contrato(c, Fake())
    assert c["status_contrato"] == cc.STATUS_DOC_OK and c["url_contrato"].endswith("/1")
    assert c["status_os"] == cc.STATUS_DOC_OK and c["url_os"].endswith("/2")
    assert c["status_empenho"] == cc.STATUS_DOC_PAGINA and c["url_empenho"] == c["url_pagina"]
    assert c["situacao"] == cc.SITUACAO_PARALISADO
    assert c["modalidade"] == "Concorrência - Eletrônica"

    emp = cc.normalizar_contrato_pncp({**BRUTO, "sequencialContrato": 9, "valorGlobal": 1000.0,
                                       "tipoContrato": {"nome": "Empenho"},
                                       "numeroControlePNCP": "x-2-000009/2026"}, mun)
    cc.vincular_empenhos([c], [c, emp])
    assert c["valor_empenhado"] == 1000.0 and c["status_empenho"] == cc.STATUS_DOC_OK
    assert indicios_fiscalizacao(c)


def test_coleta_orquestrada_sem_rede(monkeypatch):
    monkeypatch.setattr(cc.ClientePNCP, "descobrir_orgaos",
                        lambda self, m, e: [cc.OrgaoMunicipal("03155926000144", "MUNICIPIO DE DOURADOS", m.nome)])
    monkeypatch.setattr(cc.ClientePNCP, "contratos_do_orgao", lambda self, cnpj, e: [BRUTO])
    monkeypatch.setattr(cc.ClientePNCP, "arquivos", lambda self, *a: [])
    monkeypatch.setattr(cc.ClientePNCP, "termos", lambda self, *a: [])
    monkeypatch.setattr(cc.ClientePNCP, "compra", lambda self, *a: None)
    res = cc.coletar_contratos([MUNICIPIOS["DOURADOS"]], 2026)
    assert len(res.contratos) == 1
    c = res.contratos[0]
    assert c["status_contrato"] == cc.STATUS_DOC_AUSENTE and c["url_contrato"].startswith("https://pncp.gov.br/app/")


def test_planilha_excel():
    c = cc.normalizar_contrato_pncp(BRUTO, MUNICIPIOS["DOURADOS"])
    c["valor_empenhado"] = 1000.0
    dados = gerar_planilha([c], {"Exercício": 2026}, ["aviso teste"])
    wb = load_workbook(BytesIO(dados))
    assert wb.sheetnames == ["Contratos", "Resumo por Município", "Resumo por Área", "Parâmetros"]
    ws = wb["Contratos"]
    cab = [cel.value for cel in ws[5]]
    col_contrato = cab.index("Contrato") + 1
    assert str(ws.cell(row=6, column=col_contrato).value).startswith('=HYPERLINK("https://pncp.gov.br/app/')
    col_valor = cab.index("Valor Global (R$)") + 1
    assert '"R$"' in ws.cell(row=6, column=col_valor).number_format
    assert ws.cell(row=6, column=cab.index("Data Assinatura") + 1).value.date() == date(2026, 1, 9)


def test_deduplicacao():
    mun = MUNICIPIOS["IVINHEMA"]
    a = cc.normalizar_contrato_pncp({**BRUTO, "numeroContratoEmpenho": "000064", "sequencialContrato": 52,
                                     "numeroControlePNCP": "a-2-52/2026"}, mun)
    b = cc.normalizar_contrato_pncp({**BRUTO, "numeroContratoEmpenho": "64", "sequencialContrato": 53,
                                     "numeroControlePNCP": "a-2-53/2026"}, mun)
    res = cc.deduplicar([a, b])
    assert len(res) == 1 and res[0]["_seq"] == 53
