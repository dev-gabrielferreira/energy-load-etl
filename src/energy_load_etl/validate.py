"""Validacoes V1 a V6. O que falha nao some: sai etiquetado com regra, motivo e origem.

Toda validacao de linha tem a mesma forma, (df_ok, df_rejeitados), para poderem ser
encadeadas em qualquer ordem sem cada uma precisar saber da anterior.
"""

from __future__ import annotations

import logging

import pandas as pd

from . import config

logger = logging.getLogger(__name__)

# Colunas do relatorio de rejeitados. As tres primeiras respondem "onde estava isso
# no arquivo original", que e' o que torna o relatorio investigavel.
COLUNAS_REJEICAO = (
    "ano",
    "arquivo_origem",
    "linha_origem",
    "id_subsistema",
    "din_instante",
    "val_cargaenergiahomwmed",
    "regra",
    "motivo",
)

COLUNAS_RASTREIO = ("ano", "arquivo_origem", "linha_origem")

# A V4 nao rejeita linha: ausencia nao tem linha para rejeitar. Ela reporta buracos,
# que precisam de um schema proprio, sem arquivo nem linha de origem.
COLUNAS_BURACO = ("ano", "id_subsistema", "din_instante_local", "regra", "motivo")


def rejeicoes_vazias() -> pd.DataFrame:
    """DataFrame vazio com o schema de rejeicao, para concatenar sem caso especial."""
    return pd.DataFrame(columns=list(COLUNAS_REJEICAO))


def _separar(
    df: pd.DataFrame, ruins: pd.Series, regra: str, motivo: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parte o DataFrame em aprovados e rejeitados, etiquetando os rejeitados."""
    if not ruins.any():
        return df, rejeicoes_vazias()

    rejeitados = df[ruins].copy()
    rejeitados["regra"] = regra
    rejeitados["motivo"] = motivo
    return df[~ruins].copy(), rejeitados[list(COLUNAS_REJEICAO)]


def v1_schema(df: pd.DataFrame) -> str | None:
    """Confere as colunas do contrato. Devolve o motivo da falha, ou None se passou.

    Unica validacao de arquivo inteiro: se o layout mudou, nao ha linha boa para
    salvar, e continuar seria adivinhar qual coluna virou qual.
    """
    encontradas = tuple(c for c in df.columns if c not in COLUNAS_RASTREIO)

    if set(encontradas) != set(config.COLUNAS_CONTRATO):
        faltando = set(config.COLUNAS_CONTRATO) - set(encontradas)
        sobrando = set(encontradas) - set(config.COLUNAS_CONTRATO)
        return f"colunas faltando: {sorted(faltando)}, colunas a mais: {sorted(sobrando)}"

    # Ordem diferente nao quebra nada, porque o pandas le por nome. Mas e' sinal de
    # mexida na fonte, e sinal de mexida na fonte a gente quer ver.
    if encontradas != config.COLUNAS_CONTRATO:
        logger.warning("ordem das colunas mudou: %s", encontradas)

    return None


def v2_subsistema(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """id_subsistema tem que estar no conjunto conhecido do SIN."""
    ruins = ~df["id_subsistema"].isin(config.SUBSISTEMAS_VALIDOS)
    return _separar(df, ruins, "V2", "subsistema_desconhecido")


def instante_inexistente(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tira as horas que nunca existiram no relogio brasileiro.

    Roda antes da faixa fisica de proposito: na entrada do horario de verao o Sul vem
    com 0E-8, e rejeitar isso por "carga zero" daria o diagnostico errado. O problema
    nao e' o valor, e' o instante.
    """
    ruins = df["din_instante_local"].isna()
    return _separar(df, ruins, "FUSO", "instante_inexistente")


def v5_valor_ausente(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Medicao vazia e' ausencia de dado, nao dado. Motivo proprio, separado da faixa."""
    ruins = df["val_cargaenergiahomwmed"].isna()
    return _separar(df, ruins, "V5", "valor_ausente")


def v3_unicidade(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Um subsistema nao pode ter duas medicoes para o mesmo instante.

    Compara pelo instante localizado, nao pelo texto: e' o instante que e' unico.
    Mantem a primeira ocorrencia por ser a ordem em que o ONS gravou.
    """
    ruins = df.duplicated(subset=["id_subsistema", "din_instante_local"], keep="first")
    return _separar(df, ruins, "V3", "duplicata")


def v5_faixa_fisica(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carga fora do que e' fisicamente possivel num sistema interligado em operacao."""
    valores = df["val_cargaenergiahomwmed"]
    ruins = (valores <= config.CARGA_MIN_MWMED) | (valores >= config.CARGA_MAX_MWMED)
    return _separar(df, ruins, "V5", "fora_de_faixa")


def v4_continuidade(df: pd.DataFrame) -> pd.DataFrame:
    """Horas que existiram no relogio local e nao chegaram, por subsistema.

    Nao conta linhas: pede a grade de instantes reais ao zoneinfo e subtrai o que veio.
    Contar quebraria, porque existe linha que nao e' hora (a fantasma da entrada do
    horario de verao) e hora que nao tem linha (a repetida, na volta).

    A janela sai do proprio dado, do primeiro ao ultimo instante do ano somando todos
    os subsistemas, e nao do calendario. Assim o ano em andamento nao acusa buraco pelo
    que ainda nao aconteceu, e um subsistema que perdeu um dia aparece porque os outros
    tres esticam a janela.
    """
    if df.empty:
        return pd.DataFrame(columns=list(COLUNAS_BURACO))

    instantes_do_ano = pd.DatetimeIndex(df["din_instante_local"])
    grade = pd.date_range(
        instantes_do_ano.min(), instantes_do_ano.max(), freq="h", tz=config.FUSO
    )

    buracos = []
    for subsistema, grupo in df.groupby("id_subsistema", observed=True):
        faltantes = grade.difference(pd.DatetimeIndex(grupo["din_instante_local"]))
        if len(faltantes):
            buracos.append(
                pd.DataFrame(
                    {
                        "ano": grupo["ano"].iloc[0],
                        "id_subsistema": subsistema,
                        "din_instante_local": faltantes,
                        "regra": "V4",
                        "motivo": "hora_faltante",
                    }
                )
            )

    if not buracos:
        return pd.DataFrame(columns=list(COLUNAS_BURACO))
    return pd.concat(buracos, ignore_index=True)[list(COLUNAS_BURACO)]


def v6_salto(df: pd.DataFrame) -> pd.DataFrame:
    """Marca saltos atipicos entre horas consecutivas. Marca, nao rejeita.

    Unica regra de alerta das seis: o valor esta correto, o que fugiu do padrao foi o
    que aconteceu naquela hora. No historico brasileiro ela acha apagao nacional, e
    marcado nao quer dizer errado, quer dizer que merece olhar humano.

    Exige os dois criterios do config.LIMITE_SALTO ao mesmo tempo.
    """
    if df.empty:
        return df

    pedacos = []
    for subsistema, grupo in df.groupby("id_subsistema", observed=True):
        grupo = grupo.sort_values("din_instante_local").copy()
        anterior = grupo["val_cargaenergiahomwmed"].shift()

        grupo["salto_mwmed"] = grupo["val_cargaenergiahomwmed"] - anterior
        grupo["salto_pct"] = grupo["salto_mwmed"].abs() / anterior * 100

        # Depois de um buraco a diferenca nao e' salto de uma hora, e' a soma de varias
        # horas que ninguem mediu. Comparar isso com o limiar acusaria degrau inventado.
        consecutiva = grupo["din_instante_local"].diff() == pd.Timedelta(hours=1)

        limite = config.LIMITE_SALTO.get(subsistema)
        if limite is None:
            # Subsistema desconhecido nao chega aqui, a V2 barra antes. Se chegar, nao
            # temos limiar medido para ele, e inventar um seria pior que nao marcar.
            grupo["salto_suspeito"] = False
        else:
            grupo["salto_suspeito"] = (
                consecutiva
                & (grupo["salto_mwmed"].abs() >= limite["piso_mwmed"])
                & (grupo["salto_pct"] >= limite["relativo_pct"])
            )
        pedacos.append(grupo)

    return pd.concat(pedacos).sort_index()
