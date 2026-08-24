"""Features de calendario e a grade de horas do relogio local.

Duas responsabilidades que andam juntas. A grade responde "quantas horas esse dia
teve de verdade", e e' a mesma pergunta que a V4 faz para achar buraco e que a
agregacao faz para saber se a media do dia esta completa. Uma implementacao so,
porque duas divergiriam.
"""

from __future__ import annotations

from collections.abc import Iterable

import holidays
import pandas as pd
from holidays.constants import OPTIONAL, PUBLIC

from . import config

# O que sai do pipeline para o Parquet, nesta ordem.
#
# Fora daqui ficam din_instante (naive, redundante com o localizado) e o par
# arquivo_origem/linha_origem, que serve ao relatorio de rejeitados e nao a' camada
# processada. Quem precisar voltar ao CSV bruto acha a linha pelo par
# (id_subsistema, din_instante_local).
COLUNAS_PROCESSADAS = (
    "id_subsistema",
    "din_instante_local",
    "val_cargaenergiahomwmed",
    "ano",
    "mes",
    "data",
    "hora",
    "dia_semana",
    "fim_de_semana",
    "feriado",
    "nome_feriado",
    "estacao",
    "hora_ambigua",
    "salto_mwmed",
    "salto_pct",
    "salto_suspeito",
)

# Estacoes do hemisferio sul pelos limites usuais, em MMDD. O solsticio anda um ou
# dois dias entre anos, e essa precisao nao muda carga de energia: o que se quer aqui
# e' agrupar por clima, nao marcar efemeride.
INICIO_OUTONO = 321
INICIO_INVERNO = 621
INICIO_PRIMAVERA = 923
INICIO_VERAO = 1221


def grade_local(inicio, fim, freq: str = "h") -> pd.DatetimeIndex:
    """Todos os instantes que existiram no relogio brasileiro entre dois pontos.

    Um dia de entrada do horario de verao devolve 23 horas, um da volta devolve 25, e
    nenhuma data de horario de verao aparece no codigo: quem sabe disso e' o zoneinfo.
    E' por isso que nada neste projeto conta linha para saber se falta hora.

    O passo e' parametro porque as duas fontes tem grao diferente: o arquivo anual e'
    horario e a API de Carga Verificada e' semi-horaria. A pergunta e' a mesma nos dois
    casos, entao a funcao e' uma so'. Duas implementacoes da mesma pergunta acabariam
    dando respostas diferentes sobre o mesmo dia, e ai' o relatorio de buracos de uma
    fonte contradiria o da outra.
    """
    return pd.date_range(inicio, fim, freq=freq, tz=config.FUSO)


def _tabela_feriados(anos: Iterable[int]) -> dict:
    """Feriados nacionais mais os pontos facultativos, por data.

    Inclui a categoria OPTIONAL de proposito. Carnaval e Corpus Christi nao sao
    feriado por lei federal, mas a carga cai neles como cai em feriado, e o criterio
    aqui e' o efeito no que a gente mede, nao a definicao juridica.
    """
    anos = sorted({int(a) for a in anos})
    if not anos:
        return {}
    return dict(holidays.Brazil(years=anos, categories=(PUBLIC, OPTIONAL)))


def _estacao(instantes: pd.Series) -> pd.Series:
    """Estacao do ano no hemisferio sul, a partir de mes e dia."""
    mes_dia = instantes.dt.month * 100 + instantes.dt.day

    # Verao e' o padrao porque e' a unica estacao que atravessa a virada do ano:
    # ela cobre tanto o comeco de janeiro quanto o fim de dezembro.
    estacoes = pd.Series("verao", index=instantes.index)
    estacoes[(mes_dia >= INICIO_OUTONO) & (mes_dia < INICIO_INVERNO)] = "outono"
    estacoes[(mes_dia >= INICIO_INVERNO) & (mes_dia < INICIO_PRIMAVERA)] = "inverno"
    estacoes[(mes_dia >= INICIO_PRIMAVERA) & (mes_dia < INICIO_VERAO)] = "primavera"
    return estacoes


def adicionar_calendario(df: pd.DataFrame) -> pd.DataFrame:
    """Deriva as colunas de calendario do instante localizado.

    Tudo sai de din_instante_local, nunca de din_instante: o naive nao sabe em que
    fuso esta, e "quinta-feira" e "18h" so significam algo no relogio local.
    """
    com_calendario = df.copy()
    local = df["din_instante_local"]

    com_calendario["data"] = local.dt.date
    com_calendario["mes"] = local.dt.month
    com_calendario["hora"] = local.dt.hour
    com_calendario["dia_semana"] = local.dt.dayofweek  # 0 = segunda
    com_calendario["fim_de_semana"] = com_calendario["dia_semana"] >= 5

    # String vazia em vez de NaN: coluna de texto com nulo obriga todo filtro a
    # lembrar do nulo, e "nao e' feriado" ja e' informacao completa.
    feriados = _tabela_feriados(local.dt.year.unique())
    com_calendario["nome_feriado"] = com_calendario["data"].map(feriados).fillna("")
    com_calendario["feriado"] = com_calendario["nome_feriado"] != ""

    com_calendario["estacao"] = _estacao(local)
    return com_calendario


def selecionar_colunas_finais(df: pd.DataFrame) -> pd.DataFrame:
    """Corta o DataFrame no schema do Parquet, na ordem de COLUNAS_PROCESSADAS."""
    return df[list(COLUNAS_PROCESSADAS)].copy()


def vazio_processado() -> pd.DataFrame:
    """DataFrame vazio no schema do processado, para o ano que a V1 bloqueou."""
    return pd.DataFrame(columns=list(COLUNAS_PROCESSADAS))
