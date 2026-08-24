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
VERIFICADA = "verificada"
DIARIO = "diario"
MENSAL = "mensal"
QUALIDADE = "qualidade"
RECONCILIACAO = "reconciliacao"
QUALIDADE_API = "qualidade_api"


def pasta_ano(ano: int) -> Path:
    return config.PROCESSED_DIR / HORARIO / f"ano={ano}"


def _escrever_particoes(df: pd.DataFrame, raiz: Path) -> list[Path]:
    """Grava um DataFrame em pastas `ano=/id_subsistema=`, um arquivo por particao.

    A particao sai do proprio dado, e nao de um parametro. Assim nao existe a
    possibilidade de o valor da coluna e o nome da pasta discordarem, que e' um defeito
    que so' aparece na leitura e sem nada apontando a causa.
    """
    escritos = []
    for (ano, subsistema), grupo in df.groupby(["ano", "id_subsistema"], observed=True):
        destino = raiz / f"ano={ano}" / f"id_subsistema={subsistema}" / NOME_ARQUIVO
        destino.parent.mkdir(parents=True, exist_ok=True)

        # ano e id_subsistema saem de dentro do arquivo: ja estao no caminho, e quem
        # le a pasta raiz recebe as duas colunas de volta pelo padrao Hive.
        grupo.drop(columns=["ano", "id_subsistema"]).to_parquet(destino, index=False)
        escritos.append(destino)
    return escritos


def escrever_horario(df: pd.DataFrame, ano: int) -> list[Path]:
    """Grava as horas de um ano, uma pasta por subsistema.

    Apaga a pasta do ano antes de escrever. Assim reprocessar da' o mesmo resultado, e
    subsistema que sumiu da fonte nao fica para tras fingindo que ainda existe.
    """
    destino_ano = pasta_ano(ano)
    if destino_ano.exists():
        shutil.rmtree(destino_ano)

    escritos = _escrever_particoes(df, config.PROCESSED_DIR / HORARIO)
    logger.info("%s: %s particoes escritas em %s", ano, len(escritos), destino_ano)
    return escritos


def escrever_verificada(df: pd.DataFrame) -> list[Path]:
    """Grava a camada semi-horaria da API, particionada como a horaria.

    Apaga a tabela inteira antes de escrever, e nao so' as particoes que vao ser
    reescritas. E' proposital: esta tabela e' uma janela movel dos ultimos dias, nao um
    historico que cresce. O que ela contem e' sempre o resultado da ultima busca, o que
    torna a escrita idempotente e deixa claro para quem le' que a cobertura dela e' a da
    janela pedida, nem mais nem menos.

    Se um dia a gente quiser acumular a serie da API, isto aqui vira leitura do que ja'
    existe mais merge por (subsistema, instante). E' uma decisao diferente, com custo
    diferente, e ela nao esta tomada.
    """
    raiz = config.PROCESSED_DIR / VERIFICADA
    if raiz.exists():
        shutil.rmtree(raiz)

    escritos = _escrever_particoes(df, raiz)
    logger.info("verificada: %s linhas em %s particoes", len(df), len(escritos))
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
    return _ler_particionado(config.PROCESSED_DIR / HORARIO, anos, subsistemas)


def ler_verificada(
    anos: list[int] | None = None, subsistemas: list[str] | None = None
) -> pd.DataFrame:
    """Le a camada semi-horaria da API, com os mesmos filtros de particao da horaria."""
    return _ler_particionado(config.PROCESSED_DIR / VERIFICADA, anos, subsistemas)


def _ler_particionado(
    raiz: Path, anos: list[int] | None = None, subsistemas: list[str] | None = None
) -> pd.DataFrame:
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
