"""Download dos CSVs anuais do ONS, com cache local e re-download quando a fonte muda.

O ONS revisa dados retroativamente, entao arquivo ja baixado nao e' garantia de
arquivo atual. Cada ano guarda ETag e tamanho no manifesto, e o download so
acontece quando a assinatura remota diverge da registrada.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from . import config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResultadoDownload:
    """Como um ano terminou: baixado, servido do cache, ausente na fonte ou com erro."""

    ano: int
    status: str
    detalhe: str = ""


def caminho_csv(ano: int) -> Path:
    return config.RAW_DIR / f"CURVA_CARGA_{ano}.csv"


def _ler_manifesto() -> dict:
    if not config.MANIFESTO.exists():
        return {}
    return json.loads(config.MANIFESTO.read_text(encoding="utf-8"))


def _gravar_manifesto(manifesto: dict) -> None:
    config.MANIFESTO.write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _assinatura_remota(url: str) -> dict | None:
    """Le ETag e tamanho por HEAD, sem baixar conteudo. None quando o ano nao existe la."""
    resposta = requests.head(url, timeout=config.TIMEOUT_SEGUNDOS)
    if resposta.status_code == 404:
        return None
    resposta.raise_for_status()
    return {
        "etag": resposta.headers.get("ETag", "").strip('"'),
        "tamanho": int(resposta.headers.get("Content-Length", 0)),
        "modificado_em": resposta.headers.get("Last-Modified", ""),
    }


def _baixar(url: str, destino: Path) -> None:
    """Grava em arquivo temporario e so entao renomeia.

    Download interrompido deixa um .parte truncado, nunca um CSV pela metade que a
    validacao leria como integro.
    """
    temporario = destino.parent / (destino.name + ".parte")
    with requests.get(url, timeout=config.TIMEOUT_SEGUNDOS, stream=True) as resposta:
        resposta.raise_for_status()
        with temporario.open("wb") as arquivo:
            for pedaco in resposta.iter_content(chunk_size=64 * 1024):
                arquivo.write(pedaco)
    os.replace(temporario, destino)


def baixar_ano(ano: int, forcar: bool = False) -> ResultadoDownload:
    """Baixa o CSV de um ano se a fonte mudou ou se ele nao existe localmente."""
    url = config.URL_CURVA_CARGA.format(ano=ano)
    destino = caminho_csv(ano)
    manifesto = _ler_manifesto()
    registro = manifesto.get(str(ano), {})

    try:
        remoto = _assinatura_remota(url)
    except requests.RequestException as erro:
        return ResultadoDownload(ano, "erro", f"HEAD falhou: {erro}")

    if remoto is None:
        return ResultadoDownload(ano, "ausente", "ainda nao publicado no ONS")

    # Confere o arquivo no disco tambem: manifesto sem CSV do lado e' cache mentiroso.
    if (
        not forcar
        and destino.exists()
        and registro.get("etag") == remoto["etag"]
        and registro.get("tamanho") == remoto["tamanho"]
    ):
        return ResultadoDownload(ano, "cache")

    try:
        _baixar(url, destino)
    except requests.RequestException as erro:
        return ResultadoDownload(ano, "erro", f"download falhou: {erro}")

    e_revisao = bool(registro) and registro.get("etag") != remoto["etag"]
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Sobrescrevemos o CSV, mas guardamos quando cada revisao aconteceu. Barato, e
    # e' a unica prova de que o ONS mexeu num ano depois de publicado.
    revisoes = list(registro.get("revisoes", []))
    if e_revisao:
        revisoes.append(
            {
                "etag_anterior": registro.get("etag"),
                "tamanho_anterior": registro.get("tamanho"),
                "substituido_em": agora,
            }
        )

    manifesto[str(ano)] = {
        "etag": remoto["etag"],
        "tamanho": remoto["tamanho"],
        "modificado_em": remoto["modificado_em"],
        "baixado_em": agora,
        "revisoes": revisoes,
    }
    _gravar_manifesto(manifesto)

    detalhe = "revisao do ONS" if e_revisao else f"{remoto['tamanho']} bytes"
    return ResultadoDownload(ano, "baixado", detalhe)


def baixar_todos(
    anos: list[int] | range | None = None, forcar: bool = False
) -> list[ResultadoDownload]:
    """Percorre os anos. Erro em um ano nao interrompe os demais."""
    config.criar_pastas()
    resultados = []
    for ano in anos if anos is not None else config.ANOS:
        resultado = baixar_ano(ano, forcar=forcar)
        logger.info("%s: %s %s", ano, resultado.status, resultado.detalhe)
        resultados.append(resultado)
    return resultados


def ler_ano(ano: int) -> pd.DataFrame:
    """Le o CSV de um ano como texto puro, sem inferir tipo nenhum.

    Deixar o pandas parsear data e numero aqui faria um valor corrompido explodir
    dentro do read_csv, e o que sobraria para reportar seria um traceback em vez do
    endereco da linha ruim. Convertido depois, cada problema vira linha rejeitada.
    """
    caminho = caminho_csv(ano)
    df = pd.read_csv(
        caminho,
        sep=config.CSV_SEPARADOR,
        encoding=config.CSV_ENCODING,
        dtype=str,
    )
    df["ano"] = ano
    df["arquivo_origem"] = caminho.name
    # +1 pelo cabecalho e +1 porque editor de texto conta a partir de 1, entao o
    # numero aqui e' o que voce digita no `sed -n Np` para achar a linha original.
    df["linha_origem"] = df.index + 2
    return df


def converter_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """Converte para os tipos do contrato. O que nao converte vira NaT/NaN, nao excecao."""
    # nom_subsistema sai aqui: e' derivavel do id e nao e' estavel entre anos (o SE
    # aparece como "SUDESTE" ate certo ano e "SUDESTE/CENTRO-OESTE" depois). Guardar
    # os dois seria convidar o dashboard a agrupar pelo campo errado.
    convertido = df.drop(columns=["nom_subsistema"]).copy()

    # Formato fixo em vez de inferencia: o ONS entrega sempre YYYY-MM-DD HH:MM:SS, e
    # qualquer coisa fora disso deve virar NaT para ser rejeitada, nao ser adivinhada.
    convertido["din_instante"] = pd.to_datetime(
        df["din_instante"], format="%Y-%m-%d %H:%M:%S", errors="coerce"
    )
    convertido["val_cargaenergiahomwmed"] = pd.to_numeric(
        df["val_cargaenergiahomwmed"], errors="coerce"
    )
    convertido["id_subsistema"] = df["id_subsistema"].str.strip()

    return convertido


def localizar_fuso(df: pd.DataFrame) -> pd.DataFrame:
    """Interpreta din_instante como hora local brasileira e anota os casos de horario de verao.

    Anota, nao rejeita: quem decide o destino de uma linha e' o validate. Aqui saem
    duas colunas novas, din_instante_local (NaT quando a hora nao existiu no relogio)
    e hora_ambigua (True na hora que aconteceu duas vezes na volta do horario de verao).
    """
    localizado = df.copy()
    naive = df["din_instante"]

    # Mesma hora lida das duas formas possiveis. Quando ela nao e' ambigua, as duas
    # apontam para o mesmo instante; quando e', diferem em exatamente uma hora. Assim o
    # codigo pergunta ao banco de fusos do sistema em vez de carregar datas de DST na mao.
    como_verao = naive.dt.tz_localize(config.FUSO, ambiguous=True, nonexistent="NaT")
    como_padrao = naive.dt.tz_localize(config.FUSO, ambiguous=False, nonexistent="NaT")

    # O notna() e' necessario porque NaT != NaT e' sempre True, e sem ele toda hora
    # inexistente seria marcada tambem como ambigua.
    localizado["hora_ambigua"] = (como_verao != como_padrao) & como_verao.notna()

    # ambiguous=True fica com a primeira ocorrencia, ainda no horario de verao, para
    # 22:00 e 23:00 seguirem consecutivas em UTC. Ver docs/decisions.md.
    localizado["din_instante_local"] = como_verao

    return localizado
