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
