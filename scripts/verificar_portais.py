"""
Verifica quais URLs de portais municipais configuradas respondem.

Uso:  python scripts/verificar_portais.py
Saída: tabela com município, URL, status HTTP e URL final (após redirecionamentos).
Use o resultado para preencher PORTAIS_CONFIRMADOS em config/regioes_ms.py.
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.regioes_ms import MUNICIPIOS  # noqa: E402


def checar(m):
    try:
        r = requests.get(m.url_portal, timeout=15, allow_redirects=True,
                         headers={"User-Agent": "FiscalizaObras-MS/1.0"})
        return m.nome, m.url_portal, r.status_code, r.url
    except requests.RequestException as exc:
        return m.nome, m.url_portal, "ERRO", type(exc).__name__


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=10) as ex:
        linhas = sorted(ex.map(checar, MUNICIPIOS.values()))
    for nome, url, status, final in linhas:
        print(f"{nome:28} {status!s:6} {url}  ->  {final}")
