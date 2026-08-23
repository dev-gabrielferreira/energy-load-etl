"""Testes do exercicio da V4. Rode com: uv run pytest exercicios/ -v

Os quatro primeiros sao os casos que qualquer implementacao razoavel acerta.
Os dois ultimos sao os do horario de verao, e sao o motivo do exercicio existir.
"""

from __future__ import annotations

import pandas as pd
import pytest

from energy_load_etl import extract
from exercicio_v4 import v4_continuidade

FUSO = "America/Sao_Paulo"


def preparar(linhas, ano=2018):
    """Monta o DataFrame no estado em que a V4 recebe: validado e com fuso aplicado."""
    df = pd.DataFrame(
        linhas,
        columns=["id_subsistema", "nom_subsistema", "din_instante", "val_cargaenergiahomwmed"],
        dtype=str,
    )
    df["ano"] = ano
    df["arquivo_origem"] = f"CURVA_CARGA_{ano}.csv"
    df["linha_origem"] = df.index + 2
    pronto = extract.localizar_fuso(extract.converter_tipos(df))
    return pronto[pronto["din_instante_local"].notna()].copy()


def horas(dia, subsistema="SE", pular=()):
    return [
        (subsistema, "SUDESTE", f"{dia} {h:02d}:00:00", f"{20000 + h * 10:.2f}")
        for h in range(24)
        if h not in pular
    ]


def test_dia_completo_nao_tem_buraco():
    assert len(v4_continuidade(preparar(horas("2018-06-01")))) == 0


def test_hora_faltante_no_meio_do_dia():
    buracos = v4_continuidade(preparar(horas("2018-06-01", pular=(10,))))
    assert len(buracos) == 1
    assert buracos.iloc[0]["din_instante_local"].hour == 10


def test_schema_da_saida():
    buracos = v4_continuidade(preparar(horas("2018-06-01", pular=(10,))))
    assert list(buracos.columns) == ["ano", "id_subsistema", "din_instante_local", "regra", "motivo"]
    assert buracos.iloc[0]["regra"] == "V4"
    assert buracos.iloc[0]["motivo"] == "hora_faltante"
    assert buracos.iloc[0]["ano"] == 2018


def test_cada_subsistema_por_conta_propria():
    """O S perdeu a hora 7. O SE esta completo. So o S deve aparecer."""
    linhas = horas("2018-06-01", subsistema="SE") + horas("2018-06-01", subsistema="S", pular=(7,))
    buracos = v4_continuidade(preparar(linhas))
    assert len(buracos) == 1
    assert buracos.iloc[0]["id_subsistema"] == "S"


def test_hora_que_nunca_existiu_nao_e_buraco():
    """16/10/2005: o relogio pulou de 00:00 para 01:00, entao a hora 0 nao existiu.
    O arquivo de 2005 nem traz essa linha, e isso esta certo. Nao ha buraco aqui."""
    linhas = horas("2005-10-15") + horas("2005-10-16", pular=(0,))
    assert len(v4_continuidade(preparar(linhas, ano=2005))) == 0


def test_hora_repetida_que_o_ons_perde_e_buraco():
    """18/02/2018: o relogio voltou de 00:00 para 23:00, entao as 23:00 do dia 17
    aconteceram duas vezes, com cargas diferentes. O arquivo tem so uma linha 23:00,
    logo uma hora real de medicao esta faltando."""
    linhas = horas("2018-02-17") + horas("2018-02-18")
    buracos = v4_continuidade(preparar(linhas))
    assert len(buracos) == 1
    faltante = buracos.iloc[0]["din_instante_local"]
    assert faltante.hour == 23
    assert faltante.utcoffset().total_seconds() / 3600 == -3
