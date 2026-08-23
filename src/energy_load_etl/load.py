"""Escrita e leitura da camada processada, em Parquet particionado.

Particionado por ano e subsistema porque e' assim que o dashboard pergunta: quase toda
tela filtra por um ou pelos dois. Com a particao no caminho, o pyarrow abre so as
pastas pedidas e nem toca no resto dos 27 anos.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pandas as pd

from . import config

logger = logging.getLogger(__name__)

# Nome fixo, um arquivo por particao. O to_parquet(partition_cols=...) geraria nomes
# com UUID, e reprocessar um ano deixaria o arquivo antigo do lado do novo: o dado
# dobraria em silencio, que e' o pior tipo de defeito de pipeline.
NOME_ARQUIVO = "dados.parquet"

HORARIO = "horario"
DIARIO = "diario"
MENSAL = "mensal"
QUALIDADE = "qualidade"


def pasta_ano(ano: int) -> Path:
    return config.PROCESSED_DIR / HORARIO / f"ano={ano}"


def escrever_horario(df: pd.DataFrame, ano: int) -> list[Path]:
    """Grava as horas de um ano, uma pasta por subsistema.

    Apaga a pasta do ano antes de escrever. Assim reprocessar da' o mesmo resultado, e
    subsistema que sumiu da fonte nao fica para tras fingindo que ainda existe.
    """
    destino_ano = pasta_ano(ano)
    if destino_ano.exists():
        shutil.rmtree(destino_ano)

    escritos = []
    for subsistema, grupo in df.groupby("id_subsistema", observed=True):
        destino = destino_ano / f"id_subsistema={subsistema}" / NOME_ARQUIVO
        destino.parent.mkdir(parents=True, exist_ok=True)

        # ano e id_subsistema saem de dentro do arquivo: ja estao no caminho, e quem
        # le a pasta raiz recebe as duas colunas de volta pelo padrao Hive.
        grupo.drop(columns=["ano", "id_subsistema"]).to_parquet(destino, index=False)
        escritos.append(destino)

    logger.info("%s: %s particoes escritas em %s", ano, len(escritos), destino_ano)
    return escritos


def escrever_agregado(df: pd.DataFrame, nome: str) -> Path:
    """Grava um agregado num arquivo unico. Sao pequenos e ninguem filtra por pasta."""
    destino = config.PROCESSED_DIR / nome / NOME_ARQUIVO
    destino.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(destino, index=False)
    logger.info("%s: %s linhas escritas em %s", nome, len(df), destino)
    return destino


def ler_horario(
    anos: list[int] | None = None, subsistemas: list[str] | None = None
) -> pd.DataFrame:
    """Le a camada horaria, opcionalmente so as particoes pedidas.

    Os filtros viram poda de pasta no pyarrow, nao filtro de DataFrame: pedir um ano
    de um subsistema le um arquivo, nao os 108.
    """
    raiz = config.PROCESSED_DIR / HORARIO
    filtros = []
    if anos:
        filtros.append(("ano", "in", list(anos)))
    if subsistemas:
        filtros.append(("id_subsistema", "in", list(subsistemas)))

    df = pd.read_parquet(raiz, filters=filtros or None)

    # As colunas de particao voltam como categoria, porque o pyarrow le o caminho e nao
    # o conteudo. Desfazer isso aqui poupa surpresa em todo groupby la' na frente.
    df["ano"] = df["ano"].astype(int)
    df["id_subsistema"] = df["id_subsistema"].astype(str)
    return df


def ler_agregado(nome: str) -> pd.DataFrame:
    return pd.read_parquet(config.PROCESSED_DIR / nome / NOME_ARQUIVO)
