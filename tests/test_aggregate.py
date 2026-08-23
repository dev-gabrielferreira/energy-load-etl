"""Testes das agregacoes. O caso que importa e' o dia que nao tem 24 horas."""

from __future__ import annotations

import pandas as pd

from energy_load_etl import aggregate, transform, validate
from tests.conftest import ENTRADA_DST_2005, ENTRADA_DST_2018, VOLTA_DST_2018, horas, preparar


def processar(linhas: list[tuple], ano: int = 2018) -> pd.DataFrame:
    """Roda o pedaco do funil que a agregacao precisa: fuso, rejeicoes e calendario."""
    df = preparar(linhas, ano=ano)
    df, _ = validate.instante_inexistente(df)
    df, _ = validate.v5_valor_ausente(df)
    return transform.adicionar_calendario(df)


def um_dia(linhas: list[tuple], ano: int = 2018) -> pd.Series:
    return aggregate.diario(processar(linhas, ano=ano)).iloc[0]


# --- dia normal ---------------------------------------------------------------


def test_dia_normal_tem_24_horas_e_esta_completo():
    dia = um_dia(horas("2018-06-01", valor=1000.0))
    assert dia["horas_presentes"] == 24
    assert dia["horas_esperadas"] == 24
    assert dia["completo"]


def test_media_min_max_e_energia():
    """Valores de 1000 a 1230, de 10 em 10: media 1115, energia a soma das 24 horas."""
    dia = um_dia(horas("2018-06-01", valor=1000.0))
    assert dia["carga_min_mwmed"] == 1000.0
    assert dia["carga_max_mwmed"] == 1230.0
    assert dia["carga_media_mwmed"] == 1115.0
    assert dia["energia_mwh"] == 1115.0 * 24


def test_hora_pico_e_a_hora_da_carga_maxima():
    linhas = horas("2018-06-01", valor=1000.0)
    linhas[7] = ("SE", "SUDESTE", "2018-06-01 07:00:00", "99999.00")
    assert um_dia(linhas)["hora_pico"] == 7


# --- os dias que nao tem 24 horas ---------------------------------------------


def test_entrada_do_horario_de_verao_espera_23_horas():
    """04/11/2018: o ONS gravou a linha das 00:00 vazia, e ela cai antes de agregar."""
    dia = um_dia(horas(ENTRADA_DST_2018, vazias=(0,)))
    assert dia["horas_esperadas"] == 23
    assert dia["horas_presentes"] == 23
    assert dia["completo"]


def test_entrada_do_horario_de_verao_no_formato_antigo():
    """16/10/2005: nos anos antigos o ONS nem gravava a linha. Mesmo resultado."""
    dia = um_dia(horas(ENTRADA_DST_2005, pular=(0,)), ano=2005)
    assert dia["horas_esperadas"] == 23
    assert dia["horas_presentes"] == 23
    assert dia["completo"]


def test_volta_do_horario_de_verao_espera_25_e_fica_incompleto():
    """17/02/2018: as 23:00 aconteceram duas vezes e o formato do ONS so guarda uma.

    O dia chega com 24 linhas e parece inteiro. So a grade do fuso sabe que faltou uma
    medicao real, e e' a mesma hora que a V4 reporta como faltante.
    """
    dia = um_dia(horas(VOLTA_DST_2018))
    assert dia["horas_esperadas"] == 25
    assert dia["horas_presentes"] == 24
    assert not dia["completo"]


def test_dia_com_buraco_no_meio_fica_incompleto():
    dia = um_dia(horas("2018-06-01", pular=(10, 11, 12)))
    assert dia["horas_presentes"] == 21
    assert dia["horas_esperadas"] == 24
    assert not dia["completo"]


def test_dia_sem_medicao_nenhuma_aparece_com_zero_horas():
    """01/12/2013 e' assim no ONS: o dia existe, e ninguem mediu nada.

    Sem linha para agrupar, o groupby nao criaria grupo e o dia sumiria do agregado.
    O grafico ligaria a vespera no dia seguinte como se nada tivesse acontecido.
    """
    linhas = horas("2018-06-01") + horas("2018-06-02", vazias=tuple(range(24))) + horas("2018-06-03")
    dias = aggregate.diario(processar(linhas))

    ausente = dias[dias["data"] == pd.Timestamp("2018-06-02").date()].iloc[0]
    assert len(dias) == 3
    assert ausente["horas_presentes"] == 0
    assert ausente["horas_esperadas"] == 24
    assert not ausente["completo"]
    assert pd.isna(ausente["carga_media_mwmed"])


def test_dia_vazio_na_borda_da_janela_fica_de_fora():
    """Limite conhecido, fixado aqui para nao ser "consertado" por engano.

    A janela do agregado sai do proprio dado, do primeiro ao ultimo dia medido. Um dia
    vazio no meio aparece, porque a janela passa por cima dele; um dia vazio na ponta
    nao, porque nada indica que ele deveria existir. Vale para a V4 pelo mesmo motivo.
    Os tres dias vazios do historico do ONS estao todos no meio do ano.
    """
    linhas = horas("2018-06-01") + horas("2018-06-02", vazias=tuple(range(24)))
    dias = aggregate.diario(processar(linhas))
    assert len(dias) == 1
    assert dias["data"].iloc[0] == pd.Timestamp("2018-06-01").date()


def test_agregado_e_v4_concordam_sobre_o_mesmo_dia():
    """Se estas duas contas divergirem, o relatorio e o dashboard contam historias diferentes.

    Com o dia seguinte junto, como no arquivo anual de verdade: a V4 so enxerga a
    23:00 repetida porque o dado continua depois dela.
    """
    df = processar(horas(VOLTA_DST_2018) + horas("2018-02-18"))
    faltantes = len(validate.v4_continuidade(df))
    dia = aggregate.diario(df).iloc[0]
    assert faltantes == 1
    assert dia["horas_esperadas"] - dia["horas_presentes"] == faltantes


# --- mensal -------------------------------------------------------------------


def linhas_do_mes(dias: int, valor: float = 1000.0) -> list[tuple]:
    linhas = []
    for d in range(1, dias + 1):
        linhas += horas(f"2018-06-{d:02d}", valor=valor)
    return linhas


def test_mensal_soma_as_horas_do_mes():
    mes = aggregate.mensal(processar(linhas_do_mes(3))).iloc[0]
    assert mes["ano"] == 2018
    assert mes["mes"] == 6
    assert mes["horas_presentes"] == 72


def test_mensal_incompleto_quando_falta_hora():
    linhas = linhas_do_mes(3)
    del linhas[30]
    mes = aggregate.mensal(processar(linhas)).iloc[0]
    assert mes["horas_presentes"] == 71
    assert mes["horas_esperadas"] == 72
    assert not mes["completo"]


def test_mensal_sai_do_horario_e_nao_da_media_das_medias():
    """Um dia curto nao pode pesar igual a um dia inteiro na media do mes."""
    linhas = horas("2018-06-01", valor=1000.0)[:6] + horas("2018-06-02", valor=5000.0)
    df = processar(linhas)

    mes = aggregate.mensal(df).iloc[0]
    media_das_medias = aggregate.diario(df)["carga_media_mwmed"].mean()

    assert mes["carga_media_mwmed"] == df["val_cargaenergiahomwmed"].mean()
    assert mes["carga_media_mwmed"] != media_das_medias


def test_vazio_devolve_schema_sem_linha():
    assert list(aggregate.diario(pd.DataFrame()).columns) == list(aggregate.COLUNAS_DIARIO)
    assert list(aggregate.mensal(pd.DataFrame()).columns) == list(aggregate.COLUNAS_MENSAL)
