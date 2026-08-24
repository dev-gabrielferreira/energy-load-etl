"""Testes das validacoes. Cada caso aqui foi observado no historico real do ONS."""

from __future__ import annotations

import pandas as pd
import pytest

from energy_load_etl import validate
from tests.conftest import (
    ENTRADA_DST_2005,
    ENTRADA_DST_2018,
    VOLTA_DST_2018,
    horas,
    montar_cru,
    preparar,
)

# --- V1: schema ---------------------------------------------------------------


def test_v1_aceita_o_contrato():
    assert validate.v1_schema(montar_cru(horas("2018-06-01"))) is None


def test_v1_bloqueia_coluna_faltando():
    df = montar_cru(horas("2018-06-01")).drop(columns=["nom_subsistema"])
    erro = validate.v1_schema(df)
    assert erro is not None and "nom_subsistema" in erro


def test_v1_bloqueia_coluna_renomeada():
    df = montar_cru(horas("2018-06-01")).rename(columns={"val_cargaenergiahomwmed": "val_carga"})
    erro = validate.v1_schema(df)
    assert erro is not None and "val_carga" in erro


def test_v1_aceita_ordem_trocada():
    """Ordem diferente nao quebra leitura por nome, entao avisa mas nao bloqueia."""
    df = montar_cru(horas("2018-06-01"))
    trocada = df[["din_instante", "id_subsistema", "val_cargaenergiahomwmed", "nom_subsistema",
                  "ano", "arquivo_origem", "linha_origem"]]
    assert validate.v1_schema(trocada) is None


# --- V2: subsistema -----------------------------------------------------------


def test_v2_rejeita_subsistema_desconhecido():
    linhas = horas("2018-06-01") + [("XX", "NOVO", "2018-06-01 00:00:00", "1000.00")]
    ok, rejeitados = validate.v2_subsistema(preparar(linhas))
    assert len(ok) == 24
    assert len(rejeitados) == 1
    assert rejeitados.iloc[0]["motivo"] == "subsistema_desconhecido"


def test_v2_rejeitado_carrega_a_linha_de_origem():
    """O relatorio so serve se der para achar a linha no arquivo original."""
    linhas = horas("2018-06-01") + [("XX", "NOVO", "2018-06-01 00:00:00", "1000.00")]
    _, rejeitados = validate.v2_subsistema(preparar(linhas))
    assert rejeitados.iloc[0]["linha_origem"] == 26  # 24 horas + cabecalho + base 1


# --- Horario de verao ---------------------------------------------------------


def test_entrada_do_dst_no_formato_antigo_nao_gera_rejeicao():
    """2005 e anteriores omitem a linha da hora que nao existiu. Nada a rejeitar."""
    linhas = horas("2005-10-15", valor=15000) + horas(ENTRADA_DST_2005, valor=15000, pular=(0,))
    df = preparar(linhas, ano=2005)
    ok, rejeitados = validate.instante_inexistente(df)
    assert len(rejeitados) == 0
    assert len(ok) == 47


def test_entrada_do_dst_no_formato_novo_rejeita_a_linha_fantasma():
    """2014 a 2018 trazem a linha da hora inexistente com o campo vazio."""
    linhas = horas(ENTRADA_DST_2018, vazias=(0,))
    df = preparar(linhas)
    ok, rejeitados = validate.instante_inexistente(df)
    assert len(rejeitados) == 1
    assert rejeitados.iloc[0]["motivo"] == "instante_inexistente"
    assert len(ok) == 23


def test_fuso_roda_antes_da_faixa_fisica():
    """O Sul veio com 0E-8 na hora inexistente de 2018. Rejeitar por carga zero seria
    dar o diagnostico errado: o problema nao e' o valor, e' o instante."""
    linhas = [("S", "SUL", f"{ENTRADA_DST_2018} 00:00:00", "0E-8")]
    df = preparar(linhas)

    _, por_fuso = validate.instante_inexistente(df)
    assert len(por_fuso) == 1
    assert por_fuso.iloc[0]["motivo"] == "instante_inexistente"
    assert por_fuso.iloc[0]["val_cargaenergiahomwmed"] == 0.0


def test_hora_ambigua_e_marcada_sem_ser_rejeitada():
    """A hora que aconteceu duas vezes na volta do DST e' dado bom, so precisa de marca."""
    df = preparar(horas(VOLTA_DST_2018))
    ambiguas = df[df["hora_ambigua"]]
    assert len(ambiguas) == 1
    assert ambiguas.iloc[0]["din_instante"].hour == 23

    ok, rejeitados = validate.instante_inexistente(df)
    assert len(rejeitados) == 0
    assert len(ok) == 24


def test_hora_ambigua_fica_com_a_primeira_ocorrencia():
    """ambiguous=True mantem 22:00 e 23:00 consecutivas em UTC, sem degrau artificial."""
    df = preparar(horas(VOLTA_DST_2018)).sort_values("din_instante")
    em_utc = df["din_instante_local"].dt.tz_convert("UTC")
    saltos = em_utc.diff().dropna()
    assert (saltos == pd.Timedelta(hours=1)).all()


# --- V3: unicidade ------------------------------------------------------------


def test_v3_rejeita_duplicata_mantendo_a_primeira():
    linhas = horas("2018-06-01") + [("SE", "SUDESTE", "2018-06-01 05:00:00", "99999.00")]
    ok, rejeitados = validate.v3_unicidade(preparar(linhas))
    assert len(rejeitados) == 1
    assert rejeitados.iloc[0]["motivo"] == "duplicata"
    assert 99999.0 not in set(ok["val_cargaenergiahomwmed"])


def test_v3_nao_confunde_subsistemas_diferentes():
    linhas = horas("2018-06-01", subsistema="SE") + horas("2018-06-01", subsistema="S")
    ok, rejeitados = validate.v3_unicidade(preparar(linhas))
    assert len(rejeitados) == 0
    assert len(ok) == 48


# --- V4: continuidade ---------------------------------------------------------


def test_v4_nao_acusa_buraco_em_dia_completo():
    assert len(validate.v4_continuidade(preparar(horas("2018-06-01")))) == 0


def test_v4_acha_hora_faltante_no_meio_do_dia():
    df = preparar(horas("2018-06-01", pular=(10,)))
    buracos = validate.v4_continuidade(df)
    assert len(buracos) == 1
    assert buracos.iloc[0]["din_instante_local"].hour == 10
    assert buracos.iloc[0]["motivo"] == "hora_faltante"


def test_v4_nao_acusa_a_hora_que_nunca_existiu():
    """O teste que quebraria qualquer validacao de 24 linhas por dia."""
    linhas = horas("2005-10-15", valor=15000) + horas(ENTRADA_DST_2005, valor=15000, pular=(0,))
    buracos = validate.v4_continuidade(preparar(linhas, ano=2005))
    assert len(buracos) == 0


def test_v4_acusa_a_hora_repetida_que_o_ons_perde():
    """Na volta do DST as 23:00 acontecem duas vezes e o ONS grava uma. Falta uma hora."""
    linhas = horas(VOLTA_DST_2018) + horas("2018-02-18")
    buracos = validate.v4_continuidade(preparar(linhas))
    assert len(buracos) == 1
    faltante = buracos.iloc[0]["din_instante_local"]
    assert faltante.hour == 23
    assert faltante.utcoffset().total_seconds() / 3600 == -3  # a ocorrencia do horario padrao


def test_v4_reporta_por_subsistema():
    linhas = horas("2018-06-01", subsistema="SE") + horas("2018-06-01", subsistema="S", pular=(7,))
    buracos = validate.v4_continuidade(preparar(linhas))
    assert len(buracos) == 1
    assert buracos.iloc[0]["id_subsistema"] == "S"


# --- V5: valor ausente e faixa fisica -----------------------------------------


def test_v5_rejeita_valor_ausente():
    """O 01/12/2013 inteiro veio assim: linha presente, medicao em branco."""
    df = preparar(horas("2013-12-01", vazias=tuple(range(24))), ano=2013)
    ok, rejeitados = validate.v5_valor_ausente(df)
    assert len(rejeitados) == 24
    assert len(ok) == 0
    assert set(rejeitados["motivo"]) == {"valor_ausente"}


@pytest.mark.parametrize("valor", ["0.00", "-500.00", "120000.00", "999999.00"])
def test_v5_rejeita_fora_da_faixa_fisica(valor):
    linhas = [("SE", "SUDESTE", "2018-06-01 00:00:00", valor)]
    _, rejeitados = validate.v5_faixa_fisica(preparar(linhas))
    assert len(rejeitados) == 1
    assert rejeitados.iloc[0]["motivo"] == "fora_de_faixa"


def test_v5_aceita_o_recorde_do_sistema():
    """O teto existe para pegar absurdo, nao para derrubar recorde novo."""
    linhas = [("SE", "SUDESTE", "2018-06-01 00:00:00", "103000.00")]
    ok, rejeitados = validate.v5_faixa_fisica(preparar(linhas))
    assert len(rejeitados) == 0
    assert len(ok) == 1


# --- V6: salto ----------------------------------------------------------------


def test_v6_marca_salto_que_passa_dos_dois_criterios():
    """SE exige 20,5% e 3.850 MWmed ao mesmo tempo. 20.000 -> 26.000 passa nos dois."""
    linhas = [
        ("SE", "SUDESTE", "2018-06-01 00:00:00", "20000.00"),
        ("SE", "SUDESTE", "2018-06-01 01:00:00", "26000.00"),
    ]
    df = validate.v6_salto(preparar(linhas))
    assert df["salto_suspeito"].sum() == 1


def test_v6_nao_marca_salto_grande_em_valor_mas_pequeno_em_proporcao():
    """5.000 MWmed sobre 50.000 e' 10%, abaixo do relativo. O AND segura."""
    linhas = [
        ("SE", "SUDESTE", "2018-06-01 00:00:00", "50000.00"),
        ("SE", "SUDESTE", "2018-06-01 01:00:00", "55000.00"),
    ]
    df = validate.v6_salto(preparar(linhas))
    assert df["salto_suspeito"].sum() == 0


def test_v6_nao_marca_salto_grande_em_proporcao_mas_pequeno_em_valor():
    """Dobrar de 1.000 para 2.000 e' 100%, mas 1.000 MWmed nao chega ao piso do SE."""
    linhas = [
        ("SE", "SUDESTE", "2018-06-01 00:00:00", "1000.00"),
        ("SE", "SUDESTE", "2018-06-01 01:00:00", "2000.00"),
    ]
    df = validate.v6_salto(preparar(linhas))
    assert df["salto_suspeito"].sum() == 0


def test_v6_ignora_o_par_que_atravessa_um_buraco():
    """Depois de um buraco a diferenca nao e' salto de uma hora, e' a soma de varias.
    Sem esse cuidado, a V6 acusaria degrau inventado onde a V4 ja reportou ausencia."""
    linhas = [
        ("SE", "SUDESTE", "2018-06-01 00:00:00", "20000.00"),
        ("SE", "SUDESTE", "2018-06-01 06:00:00", "40000.00"),
    ]
    df = validate.v6_salto(preparar(linhas))
    assert df["salto_suspeito"].sum() == 0


def test_v6_marca_o_apagao_de_2009():
    """Caso real: o SE caiu de 37.406 para 18.137 MWmed em uma hora."""
    linhas = [
        ("SE", "SUDESTE", "2009-11-10 21:00:00", "37405.80"),
        ("SE", "SUDESTE", "2009-11-10 22:00:00", "18136.92"),
    ]
    df = validate.v6_salto(preparar(linhas, ano=2009))
    marcada = df[df["salto_suspeito"]]
    assert len(marcada) == 1
    assert marcada.iloc[0]["salto_mwmed"] < -19000


# --- V7: reconciliacao API x arquivo ------------------------------------------
#
# A V7 nao tem vencedor, e isso e' conclusao e nao omissao: a API conta geracao
# distribuida e o arquivo anual nao, entao as duas divergem por construcao. O que ela
# marca sem ambiguidade e' cobertura, que nao depende de limiar nenhum.


def _fonte(instantes, valores, subsistema="SE", completo=True):
    """Monta uma das duas pontas da V7, no formato minimo que ela consome."""
    df = pd.DataFrame(
        {
            "id_subsistema": subsistema,
            "din_instante_local": pd.to_datetime(instantes).tz_localize(
                "America/Sao_Paulo", ambiguous=True
            ),
            "val_cargaenergiahomwmed": valores,
        }
    )
    df["completo"] = completo
    return df


HORAS_DE_TESTE = ["2026-06-01 12:00", "2026-06-01 13:00", "2026-06-01 14:00"]


def test_v7_marca_confere_quando_a_divergencia_esta_na_faixa():
    """+5% as 12h no SE esta dentro do que a geracao distribuida explica."""
    arquivo = _fonte(HORAS_DE_TESTE, [20000.0, 20000.0, 20000.0])
    api = _fonte(HORAS_DE_TESTE, [21000.0, 21000.0, 21000.0])
    rec = validate.v7_reconciliacao(arquivo, api)
    assert set(rec["motivo"]) == {"confere"}
    assert rec["divergencia_pct"].round(1).tolist() == [5.0, 5.0, 5.0]


def test_v7_marca_atipica_acima_da_faixa():
    arquivo = _fonte(HORAS_DE_TESTE, [20000.0, 20000.0, 20000.0])
    api = _fonte(HORAS_DE_TESTE, [21000.0, 30000.0, 21000.0])  # +50% as 13h
    rec = validate.v7_reconciliacao(arquivo, api)
    atipicas = rec[rec["motivo"] == "divergencia_atipica"]
    assert len(atipicas) == 1
    assert atipicas.iloc[0]["din_instante_local"].hour == 13


def test_v7_usa_faixa_diferente_por_hora_do_dia():
    """A mesma divergencia e' normal ao meio-dia e atipica de madrugada.

    E' o que separa a regra de medir o sol: com faixa unica por subsistema, 100% das
    marcacoes cairiam entre 7h e 14h.
    """
    horas_ = ["2026-06-01 03:00", "2026-06-01 13:00"]
    arquivo = _fonte(horas_, [20000.0, 20000.0])
    api = _fonte(horas_, [22400.0, 22400.0])  # +12% nas duas
    rec = validate.v7_reconciliacao(arquivo, api).set_index("hora")
    assert rec.loc[3, "motivo"] == "divergencia_atipica"  # faixa das 03h no SE vai ate 7,5%
    assert rec.loc[13, "motivo"] == "confere"  # a das 13h vai ate 15,9%


def test_v7_nao_marca_hora_incompleta():
    """Media de meia hora contra media de uma hora acusaria divergencia nossa, nao do dado."""
    arquivo = _fonte(HORAS_DE_TESTE, [20000.0, 20000.0, 20000.0])
    api = _fonte(HORAS_DE_TESTE, [21000.0, 30000.0, 21000.0], completo=False)
    rec = validate.v7_reconciliacao(arquivo, api)
    assert "divergencia_atipica" not in set(rec["motivo"])


def test_v7_acha_a_hora_que_so_a_api_tem():
    """A volta do horario de verao: o arquivo guardou uma das 23:00, a API guardou as duas."""
    # As duas fontes seguem ate 00:00 do dia seguinte, senao a hora recuperada cairia na
    # borda da sobreposicao e o recorte a excluiria antes da comparacao.
    arquivo = pd.DataFrame(
        {
            "id_subsistema": "SE",
            "din_instante_local": pd.to_datetime(
                ["2018-02-17 22:00", "2018-02-17 23:00", "2018-02-18 00:00"]
            ).tz_localize("America/Sao_Paulo", ambiguous=[True, True, True]),
            "val_cargaenergiahomwmed": [40000.0, 38000.0, 37000.0],
        }
    )
    api = pd.DataFrame(
        {
            "id_subsistema": "SE",
            "din_instante_local": pd.to_datetime(
                ["2018-02-17 22:00", "2018-02-17 23:00", "2018-02-17 23:00", "2018-02-18 00:00"]
            ).tz_localize("America/Sao_Paulo", ambiguous=[True, True, False, True]),
            "val_cargaenergiahomwmed": [40100.0, 38100.0, 37800.0, 37100.0],
            "completo": True,
        }
    )
    rec = validate.v7_reconciliacao(arquivo, api)
    so_na_api = rec[rec["motivo"] == "so_na_api"]
    assert len(so_na_api) == 1
    recuperada = so_na_api.iloc[0]
    assert recuperada["din_instante_local"].utcoffset().total_seconds() / 3600 == -3
    assert recuperada["val_api"] == 37800.0
    assert pd.isna(recuperada["val_arquivo"])


def test_v7_acha_a_hora_que_so_o_arquivo_tem():
    """O buraco precisa estar no meio: a hora do arquivo que a API perdeu no caminho."""
    arquivo = _fonte(HORAS_DE_TESTE, [20000.0, 20000.0, 20000.0])
    api = _fonte([HORAS_DE_TESTE[0], HORAS_DE_TESTE[2]], [21000.0, 21000.0])
    rec = validate.v7_reconciliacao(arquivo, api)
    so_no_arquivo = rec[rec["motivo"] == "so_no_arquivo"]
    assert len(so_no_arquivo) == 1
    assert so_no_arquivo.iloc[0]["din_instante_local"].hour == 13


def test_v7_ignora_a_ponta_que_so_uma_fonte_alcanca():
    """Comportamento de borda, deliberado: a sobreposicao recorta antes de comparar.

    A API e' uns dias mais fresca que o arquivo anual. Sem este recorte, toda execucao
    acusaria como "so na API" as horas que o ONS simplesmente ainda nao publicou, e o
    relatorio de cobertura viraria ruido diario. O preco e' que buraco exatamente na
    ponta nao aparece aqui; quem cuida disso e' a conferencia de cobertura do cliente,
    que compara com a janela pedida e nao com a outra fonte.
    """
    arquivo = _fonte(HORAS_DE_TESTE, [20000.0, 20000.0, 20000.0])
    api = _fonte(HORAS_DE_TESTE[:2], [21000.0, 21000.0])
    rec = validate.v7_reconciliacao(arquivo, api)
    assert len(rec) == 2
    assert "so_no_arquivo" not in set(rec["motivo"])


def test_v7_compara_so_a_sobreposicao():
    """Sem o recorte, as 26 horas do arquivo anteriores a' API virariam ruido no relatorio."""
    arquivo = _fonte(
        ["2020-01-01 00:00", "2026-06-01 12:00", "2026-06-01 13:00"], [20000.0] * 3
    )
    api = _fonte(["2026-06-01 12:00", "2026-06-01 13:00"], [21000.0, 21000.0])
    rec = validate.v7_reconciliacao(arquivo, api)
    assert len(rec) == 2
    assert "so_no_arquivo" not in set(rec["motivo"])


def test_v7_sem_sobreposicao_devolve_tabela_vazia():
    arquivo = _fonte(["2020-01-01 00:00"], [20000.0])
    api = _fonte(["2026-06-01 12:00"], [21000.0])
    assert len(validate.v7_reconciliacao(arquivo, api)) == 0
