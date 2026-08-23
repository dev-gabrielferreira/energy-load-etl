"""Fixtures sinteticas pequenas.

Cada caso montado aqui foi visto no dado real do ONS antes de virar teste. As datas de
horario de verao sao as verdadeiras, porque testar contra data inventada nao provaria
que o codigo conversa certo com o banco de fusos.
"""

from __future__ import annotations

import pandas as pd
import pytest

from energy_load_etl import extract

COLUNAS = ["id_subsistema", "nom_subsistema", "din_instante", "val_cargaenergiahomwmed"]

# Transicoes reais do horario de verao brasileiro usadas nos testes.
ENTRADA_DST_2005 = "2005-10-16"  # 00:00 nao existiu, e o arquivo de 2005 nem traz a linha
ENTRADA_DST_2018 = "2018-11-04"  # 00:00 nao existiu, mas o arquivo de 2018 traz a linha vazia
VOLTA_DST_2018 = "2018-02-17"  # 23:00 aconteceu duas vezes, e so uma foi gravada


def montar_cru(linhas: list[tuple], ano: int = 2018) -> pd.DataFrame:
    """Monta o DataFrame no formato que sai de extract.ler_ano: texto puro e rastreio."""
    df = pd.DataFrame(linhas, columns=COLUNAS, dtype=str)
    df["ano"] = ano
    df["arquivo_origem"] = f"CURVA_CARGA_{ano}.csv"
    df["linha_origem"] = df.index + 2
    return df


def horas(
    dia: str,
    subsistema: str = "SE",
    valor: float = 20000.0,
    pular: tuple[int, ...] = (),
    vazias: tuple[int, ...] = (),
) -> list[tuple]:
    """Gera as linhas de um dia, uma por hora.

    `pular` omite a linha (formato dos anos antigos), `vazias` mantem a linha com o
    campo em branco (formato dos anos 2014 a 2018). Os dois casos existem no ONS.
    """
    linhas = []
    for h in range(24):
        if h in pular:
            continue
        bruto = None if h in vazias else f"{valor + h * 10:.2f}"
        linhas.append((subsistema, "SUDESTE", f"{dia} {h:02d}:00:00", bruto))
    return linhas


def preparar(linhas: list[tuple], ano: int = 2018) -> pd.DataFrame:
    """Leva o cru ate o ponto em que as validacoes de linha rodam."""
    return extract.localizar_fuso(extract.converter_tipos(montar_cru(linhas, ano=ano)))


@pytest.fixture
def cru():
    return montar_cru


@pytest.fixture
def dia():
    return horas
