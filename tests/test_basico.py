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
    res = cc.coletar_contratos([MUNICIPIOS["DOURADOS"], MUNICIPIOS["DOURADOS"]], 2026)  # Dourados é Betha
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


REG_FIORILLI = {
    "CODIGO": "1090/26", "ANO": "2026", "LICIT": "CONCORRÊNCIA ELETRÔNICA", "PROCLIC": "000029/26",
    "MODALI": "OBRA CONCORRÊNCIA EL", "NUMLICMOD": "0005/26", "FORNECEDOR": "EMPRESA TESTE ENGENHARIA LTDA",
    "VALCON": "4825527,58", "DTASSI": "09/01/2026 00:00:00", "VIGENI": "09/01/2026 00:00:00",
    "VIGENF": "09/01/2099 00:00:00", "VENCIMENTO_ATUAL": "09/01/2099 00:00:00",
    "OBJETO_COMPLETO": "Construção do Centro de Atenção Psicossocial", "ENTIDADE": "PREFEITURA",
    "TIPOCOOBRA": "11", "CONTRATONUM": "000011", "EMPENHADOANT": "0", "EMPENHADO": "1000000",
    "LIQUIDADOANT": "0", "LIQUIDADO": "250000,5", "SALDOEMPENHAR": "3825527,58", "EMPRESA": "1",
    "INSMF": "12.345.678/0001-90", "DTANULA": "", "DTENCERRAMENTO": "",
}


def test_portais_da_planilha():
    from config.regioes_ms import PORTAIS_TRANSPARENCIA
    assert len(PORTAIS_TRANSPARENCIA) == 79 and set(PORTAIS_TRANSPARENCIA) == set(MUNICIPIOS)
    assert sum(1 for s, _ in PORTAIS_TRANSPARENCIA.values() if s == "FIORILLI") == 39
    assert cc.base_api_fiorilli(MUNICIPIOS["COXIM"].url_portal) == "http://pmcoxim.rcmsuporte.com.br:8079/transparencia"
    assert MUNICIPIOS["RIO VERDE DE MATO GROSSO"].url_portal.startswith("https://transparencia.betha.cloud/#/")


def test_normalizacao_fiorilli():
    p = cc.normalizar_contrato_fiorilli(REG_FIORILLI, MUNICIPIOS["DOURADOS"])
    assert p["valor_global"] == 4825527.58 and p["valor_empenhado"] == 1000000.0
    assert p["valor_liquidado"] == 250000.5 and p["saldo_a_empenhar"] == 3825527.58
    assert p["numero_contrato"] == "11/2026" and p["cnpj_fornecedor"] == "12.345.678/0001-90"
    assert p["area"] == AREA_CIVIL and p["status_empenho"] == cc.STATUS_DOC_PORTAL


def test_fusao_sem_duplicidade():
    mun = MUNICIPIOS["DOURADOS"]
    pncp = cc.normalizar_contrato_pncp(BRUTO, mun)
    todos = [pncp]
    igual = cc.normalizar_contrato_fiorilli(REG_FIORILLI, mun)
    repetido = cc.normalizar_contrato_fiorilli({**REG_FIORILLI, "EMPRESA": "9"}, mun)  # mesmo contrato, outra entidade
    so_portal = cc.normalizar_contrato_fiorilli({**REG_FIORILLI, "CODIGO": "2000/26", "CONTRATONUM": "000500",
                                                 "INSMF": "98.765.432/0001-10", "VALCON": "100000"}, mun)
    vinc, novos, desc = cc.mesclar_portal(todos, [igual, repetido, so_portal], mun)
    assert (vinc, novos, desc) == (1, 1, 1)
    assert len(todos) == 2
    assert pncp["valor_empenhado"] == 1000000.0 and pncp["fonte"].startswith("PNCP + ")
    assert pncp["url_contrato"].startswith("https://pncp.gov.br")  # documento do PNCP preservado


def test_fusao_nao_casa_mesmo_cnpj_sem_outro_criterio():
    mun = MUNICIPIOS["DOURADOS"]
    todos = [cc.normalizar_contrato_pncp(BRUTO, mun)]
    outro = cc.normalizar_contrato_fiorilli({**REG_FIORILLI, "CONTRATONUM": "000777", "CODIGO": "0777/26",
                                             "VALCON": "1500", "DTASSI": "01/06/2026 00:00:00"}, mun)
    assert cc.mesclar_portal(todos, [outro], mun) == (0, 1, 0)
    assert len(todos) == 2


def test_dedup_mesmo_contrato_em_dois_orgaos():
    mun = MUNICIPIOS["IVINHEMA"]
    a = cc.normalizar_contrato_pncp(BRUTO, mun)
    b = cc.normalizar_contrato_pncp({**BRUTO, "orgaoEntidade": {"cnpj": "11112312000103", "razaoSocial": "FUNDO"},
                                     "numeroContratoEmpenho": "000011", "sequencialContrato": 10,
                                     "numeroControlePNCP": "b-2-10/2026"}, mun)
    assert len(cc.deduplicar([a, b])) == 1


def test_classificador_sem_falso_positivo_de_boilerplate():
    assert not classificar("Divulgação e publicação dos atos oficiais, conforme Estudo Técnico Preliminar").tecnico
    assert not classificar("Assessoria e consultoria técnica à Secretaria de Cultura e Esporte").tecnico


def test_enriquecimento_preserva_link_do_portal():
    mun = MUNICIPIOS["DOURADOS"]
    c = cc.normalizar_contrato_pncp(BRUTO, mun)
    cc.mesclar_portal([c], [cc.normalizar_contrato_fiorilli(REG_FIORILLI, mun)], mun)

    class Vazio(cc.ClientePNCP):
        def arquivos(self, *a): return [{"url": "https://x/1", "titulo": "Contrato", "tipoDocumentoNome": "Contrato"}]
        def termos(self, *a): return []
        def compra(self, *a): return None

    cc.enriquecer_contrato(c, Vazio())
    assert c["status_empenho"] == cc.STATUS_DOC_PORTAL and c["status_contrato"] == cc.STATUS_DOC_OK
