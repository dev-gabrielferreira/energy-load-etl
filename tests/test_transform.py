"""Testes das features de calendario e da grade de horas do relogio local."""

from __future__ import annotations

import pandas as pd

from energy_load_etl import transform
from tests.conftest import ENTRADA_DST_2018, VOLTA_DST_2018, horas, preparar

# --- grade_local: quantas horas o dia teve de verdade -------------------------


def grade_do_dia(dia: str) -> pd.DatetimeIndex:
    """So as horas do dia pedido, recortadas de uma janela que comeca no dia anterior.

    A janela nao comeca a' meia-noite do proprio dia de proposito: na entrada do
    horario de verao essa meia-noite nao existe, e pedir a grade a partir dela seria
    pedir para o pandas localizar um instante que nunca aconteceu.
    """
    alvo = pd.Timestamp(dia)
    grade = transform.grade_local(alvo - pd.Timedelta(days=1), alvo + pd.Timedelta(days=2))
    return grade[grade.date == alvo.date()]


def test_grade_de_dia_normal_tem_24_horas():
    assert len(grade_do_dia("2018-06-01")) == 24


def test_grade_encolhe_na_entrada_do_horario_de_verao():
    """04/11/2018: o relogio pulou de 00:00 para 01:00, entao o dia teve 23 horas."""
    dia = grade_do_dia(ENTRADA_DST_2018)
    assert len(dia) == 23
    assert 0 not in dia.hour


def test_grade_estica_na_volta_do_horario_de_verao():
    """17/02/2018: as 23:00 aconteceram duas vezes, entao o dia teve 25 horas.

    O ONS gravou so uma delas, e e' dai que sai a hora que a V4 acusa como faltante
    todo ano de 2000 a 2019.
    """
    dia = grade_do_dia(VOLTA_DST_2018)
    assert len(dia) == 25
    assert list(dia.hour).count(23) == 2


# --- calendario ---------------------------------------------------------------


def calendario(dia: str, ano: int = 2018) -> pd.DataFrame:
    return transform.adicionar_calendario(preparar(horas(dia), ano=ano))


def test_dia_util_nao_e_fim_de_semana_nem_feriado():
    df = calendario("2018-06-01")  # sexta comum
    assert df["dia_semana"].eq(4).all()
    assert not df["fim_de_semana"].any()
    assert not df["feriado"].any()
    assert df["nome_feriado"].eq("").all()


def test_sabado_e_domingo_sao_fim_de_semana():
    for dia, esperado in (("2018-06-02", 5), ("2018-06-03", 6)):
        df = calendario(dia)
        assert df["dia_semana"].eq(esperado).all()
        assert df["fim_de_semana"].all()


def test_feriado_nacional_fixo():
    df = calendario("2018-09-07")
    assert df["feriado"].all()
    assert df["nome_feriado"].eq("Independência do Brasil").all()


def test_feriado_movel_carnaval():
    """Carnaval nao e' feriado por lei federal, mas a carga cai nele como em feriado."""
    df = calendario("2018-02-13")
    assert df["feriado"].all()
    assert "Carnaval" in df["nome_feriado"].iloc[0]


def test_feriado_movel_muda_de_data_entre_anos():
    """Se a data do Carnaval fosse fixa no codigo, 2019 quebraria aqui."""
    assert calendario("2019-03-05", ano=2019)["feriado"].all()
    assert not calendario("2019-02-13", ano=2019)["feriado"].any()


def test_hora_e_mes_saem_do_instante_local():
    df = calendario("2018-06-01")
    assert list(df["hora"]) == list(range(24))
    assert df["mes"].eq(6).all()


def test_data_e_o_dia_local():
    df = calendario("2018-06-01")
    assert df["data"].eq(pd.Timestamp("2018-06-01").date()).all()


# --- estacao ------------------------------------------------------------------


def test_estacoes_nas_bordas():
    casos = (
        ("2018-12-20", "primavera"),
        ("2018-12-21", "verao"),
        ("2018-01-15", "verao"),
        ("2018-03-21", "outono"),
        ("2018-06-21", "inverno"),
        ("2018-09-23", "primavera"),
    )
    for dia, esperada in casos:
        assert calendario(dia)["estacao"].eq(esperada).all(), dia


# --- schema de saida ----------------------------------------------------------


def test_selecionar_colunas_finais_corta_o_rastreio():
    from energy_load_etl import validate

    df = validate.v6_salto(calendario("2018-06-01"))
    final = transform.selecionar_colunas_finais(df)

    assert list(final.columns) == list(transform.COLUNAS_PROCESSADAS)
    assert "din_instante" not in final.columns
    assert "linha_origem" not in final.columns


def test_vazio_processado_tem_o_schema_completo():
    vazio = transform.vazio_processado()
    assert len(vazio) == 0
    assert list(vazio.columns) == list(transform.COLUNAS_PROCESSADAS)
