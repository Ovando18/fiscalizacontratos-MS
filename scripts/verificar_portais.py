"""
Verifica os Portais da Transparência configurados em config/regioes_ms.py.

Uso:  python scripts/verificar_portais.py [exercicio]

Para os portais Fiorilli SCPI, testa a API de Dados Abertos de contratos e
informa quantos contratos do exercício ela devolve. Para os demais, testa se a
página responde.
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.regioes_ms import MUNICIPIOS  # noqa: E402
from scrapers.coletor_contratos import CONECTORES  # noqa: E402

EXERCICIO = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year


def checar(m):
    try:
        if m.sistema in CONECTORES:
            regs = CONECTORES[m.sistema](m).buscar_contratos(EXERCICIO)
            return m.nome, m.sistema, "OK", f"{len(regs)} contrato(s) em {EXERCICIO} via API"
        r = requests.get(m.url_portal, timeout=20, headers={"User-Agent": "FiscalizaObras-MS/1.0"})
        return m.nome, m.sistema, r.status_code, "página (somente link)"
    except Exception as exc:  # noqa: BLE001
        return m.nome, m.sistema, "ERRO", type(exc).__name__


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=10) as ex:
        linhas = sorted(ex.map(checar, MUNICIPIOS.values()))
    for nome, sistema, status, info in linhas:
        print(f"{nome:28} {sistema:9} {status!s:5} {info}")
