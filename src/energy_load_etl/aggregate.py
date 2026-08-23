"""Agregacoes diaria e mensal por subsistema.

Toda linha de agregado diz de quantas horas ela e' feita e de quantas deveria ser.
Sem isso, a media de um dia que perdeu seis horas parece tao solida quanto a de um dia
inteiro, e quem le o numero nao tem como saber a diferenca.
"""

from __future__ import annotations

import pandas as pd

from . import transform

COLUNAS_DIARIO = (
    "ano",
    "mes",
    "data",
    "id_subsistema",
    "carga_media_mwmed",
    "carga_min_mwmed",
    "carga_max_mwmed",
    "hora_pico",
    "energia_mwh",
    "horas_presentes",
    "horas_esperadas",
    "completo",
)

COLUNAS_MENSAL = (
    "ano",
    "mes",
    "id_subsistema",
    "carga_media_mwmed",
    "carga_min_mwmed",
    "carga_max_mwmed",
    "energia_mwh",
    "horas_presentes",
    "horas_esperadas",
    "completo",
)

# mean, min, max e sum saem todos da mesma coluna, e size conta as horas que chegaram.
_MEDIDAS = {
    "carga_media_mwmed": ("val_cargaenergiahomwmed", "mean"),
    "carga_min_mwmed": ("val_cargaenergiahomwmed", "min"),
    "carga_max_mwmed": ("val_cargaenergiahomwmed", "max"),
    # Cada linha vale uma hora, entao somar MWmed da' MWh direto. So e' comparavel
    # entre periodos quando `completo` e' verdadeiro: hora que faltou nao entra na soma.
    "energia_mwh": ("val_cargaenergiahomwmed", "sum"),
    "horas_presentes": ("val_cargaenergiahomwmed", "size"),
}


def _grade_do_periodo(df: pd.DataFrame) -> pd.Series:
    """As horas reais dos dias que o dado cobre, do primeiro ao ultimo, dias inteiros.

    Janela diferente da que a V4 usa, e de proposito. A V4 pergunta "faltou medicao?" e
    para isso a janela para no ultimo instante observado, senao o ano em andamento
    acusaria como buraco o que ainda nao aconteceu. Aqui a pergunta e' outra, "esse dia
    esta inteiro?", e ela so tem resposta com o dia inteiro na mao: sem isso o ultimo
    dia do ano corrente sairia como completo por so ter sido medido pela metade.

    A folga de um dia de cada lado existe porque pedir "meia-noite deste dia" quebraria
    na entrada do horario de verao, quando essa meia-noite nao existiu.
    """
    instantes = pd.DatetimeIndex(df["din_instante_local"])
    folga = pd.Timedelta(days=1)
    grade = transform.grade_local(instantes.min() - folga, instantes.max() + folga)
    dentro = (grade.date >= instantes.min().date()) & (grade.date <= instantes.max().date())
    return pd.Series(grade[dentro])


def _horas_esperadas_por_dia(df: pd.DataFrame) -> pd.Series:
    """Quantas horas cada dia teve no relogio local. Nunca 24 por decreto.

    Dia de entrada do horario de verao devolve 23 e dia da volta devolve 25. Como o
    formato do ONS nao tem onde guardar a hora repetida, o dia da volta chega com 24 e
    sai marcado como incompleto: e' o mesmo fato que a V4 reporta como hora faltante.
    """
    grade = _grade_do_periodo(df)
    return grade.groupby(grade.dt.date.rename("data")).size()


def _horas_esperadas_por_mes(df: pd.DataFrame) -> pd.Series:
    """Mesma ideia da grade diaria, com a chave em (ano, mes)."""
    grade = _grade_do_periodo(df)
    return grade.groupby([grade.dt.year.rename("ano"), grade.dt.month.rename("mes")]).size()


def _todos_os_periodos(periodos: pd.DataFrame, subsistemas: list[str]) -> pd.DataFrame:
    """Produto de periodos por subsistemas, o esqueleto que o agregado preenche.

    Existe por causa dos dias em que ninguem mediu nada: sem linha nenhuma, o groupby
    nao cria grupo e o dia sumiria do agregado em silencio. Sao tres no historico
    (01/12/2013, 01/02/2014 e 09/04/2015), e some-los faria o grafico ligar a vespera
    no dia seguinte como se nada tivesse acontecido.
    """
    return periodos.merge(pd.DataFrame({"id_subsistema": subsistemas}), how="cross")


def diario(df: pd.DataFrame) -> pd.DataFrame:
    """Um registro por dia de calendario e subsistema, com a completude declarada."""
    if df.empty:
        return pd.DataFrame(columns=list(COLUNAS_DIARIO))

    chave = ["id_subsistema", "data"]
    medidas = df.groupby(chave, observed=True).agg(**_MEDIDAS).reset_index()

    # A hora do pico nao sai de agg: e' a hora da linha de carga maxima, nao uma
    # estatistica da coluna. O merge protege contra a ordem dos grupos mudar.
    linhas_de_pico = df.loc[
        df.groupby(chave, observed=True)["val_cargaenergiahomwmed"].idxmax(),
        [*chave, "hora"],
    ].rename(columns={"hora": "hora_pico"})
    medidas = medidas.merge(linhas_de_pico, on=chave, how="left")

    esperadas = _horas_esperadas_por_dia(df)
    esqueleto = _todos_os_periodos(
        esperadas.index.to_frame(index=False), sorted(df["id_subsistema"].unique())
    )
    agregado = esqueleto.merge(medidas, on=chave, how="left")

    datas = pd.to_datetime(agregado["data"])
    agregado["ano"] = datas.dt.year
    agregado["mes"] = datas.dt.month
    agregado["hora_pico"] = agregado["hora_pico"].astype("Int64")
    agregado = _declarar_completude(agregado, agregado["data"].map(esperadas))

    return agregado[list(COLUNAS_DIARIO)].sort_values(["data", "id_subsistema"], ignore_index=True)


def mensal(df: pd.DataFrame) -> pd.DataFrame:
    """Um registro por mes e subsistema.

    Calculado do horario, nao do diario. Media de medias diarias daria o mesmo peso a
    um dia inteiro e a um dia com seis horas medidas, e o mes sairia torto sem ninguem
    perceber.
    """
    if df.empty:
        return pd.DataFrame(columns=list(COLUNAS_MENSAL))

    chave = ["id_subsistema", "ano", "mes"]
    medidas = df.groupby(chave, observed=True).agg(**_MEDIDAS).reset_index()

    esperadas = _horas_esperadas_por_mes(df)
    esqueleto = _todos_os_periodos(
        esperadas.index.to_frame(index=False), sorted(df["id_subsistema"].unique())
    )
    agregado = esqueleto.merge(medidas, on=chave, how="left")
    agregado = _declarar_completude(
        agregado, pd.MultiIndex.from_frame(agregado[["ano", "mes"]]).map(esperadas)
    )

    return agregado[list(COLUNAS_MENSAL)].sort_values(
        ["ano", "mes", "id_subsistema"], ignore_index=True
    )


def _declarar_completude(agregado: pd.DataFrame, esperadas) -> pd.DataFrame:
    """Fecha o agregado com as tres colunas que dizem de que ele e' feito.

    horas_presentes vira zero onde nao houve medicao nenhuma, e as medidas ficam nulas
    de proposito: media de coisa nenhuma nao e' zero, e' ausencia.
    """
    agregado["horas_presentes"] = agregado["horas_presentes"].fillna(0).astype("int64")
    agregado["horas_esperadas"] = pd.Series(esperadas, index=agregado.index).astype("int64")
    agregado["completo"] = agregado["horas_presentes"] == agregado["horas_esperadas"]
    return agregado
