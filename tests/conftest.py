"""Fixtures sinteticas pequenas.

Cada caso montado aqui foi visto no dado real do ONS antes de virar teste. As datas de
horario de verao sao as verdadeiras, porque testar contra data inventada nao provaria
que o codigo conversa certo com o banco de fusos.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from energy_load_etl import extract

COLUNAS = ["id_subsistema", "nom_subsistema", "din_instante", "val_cargaenergiahomwmed"]

# Transicoes reais do horario de verao brasileiro usadas nos testes.
ENTRADA_DST_2005 = "2005-10-16"  # 00:00 nao existiu, e o arquivo de 2005 nem traz a linha
ENTRADA_DST_2018 = "2018-11-04"  # 00:00 nao existiu, mas o arquivo de 2018 traz a linha vazia
VOLTA_DST_2018 = "2018-02-17"  # 23:00 aconteceu duas vezes, e so uma foi gravada


def montar_cru(linhas: list[tuple], ano: int = 2018) -> pd.DataFrame:
    """Monta o DataFrame no formato que sai de extract.ler_ano: texto puro e rastreio."""
    df = pd.DataFrame(linhas, columns=COLUNAS, dtype=str)
    df["ano"] = ano
    df["arquivo_origem"] = f"CURVA_CARGA_{ano}.csv"
    df["linha_origem"] = df.index + 2
    return df


def horas(
    dia: str,
    subsistema: str = "SE",
    valor: float = 20000.0,
    pular: tuple[int, ...] = (),
    vazias: tuple[int, ...] = (),
) -> list[tuple]:
    """Gera as linhas de um dia, uma por hora.

    `pular` omite a linha (formato dos anos antigos), `vazias` mantem a linha com o
    campo em branco (formato dos anos 2014 a 2018). Os dois casos existem no ONS.
    """
    linhas = []
    for h in range(24):
        if h in pular:
            continue
        bruto = None if h in vazias else f"{valor + h * 10:.2f}"
        linhas.append((subsistema, "SUDESTE", f"{dia} {h:02d}:00:00", bruto))
    return linhas


def preparar(linhas: list[tuple], ano: int = 2018) -> pd.DataFrame:
    """Leva o cru ate o ponto em que as validacoes de linha rodam."""
    return extract.localizar_fuso(extract.converter_tipos(montar_cru(linhas, ano=ano)))


@pytest.fixture
def cru():
    return montar_cru


@pytest.fixture
def dia():
    return horas


# --- Fonte 2: API de Carga Verificada -----------------------------------------

# Trecho verdadeiro do que a API devolve para 2018-06-01. Os dois campos sem valor
# nenhum sao os de geracao distribuida, que nao existia: e' JSON invalido, e o
# json.loads recusa antes do reparo. Copiado da resposta real, nao inventado.
CORPO_MALFORMADO = """[
          {
        "cod_areacarga": "SECO",
        "din_atualizacao":"2020-09-24T12:52:27.000Z",
        "dat_referencia": "2018-06-01",
        "din_referenciautc": "2018-06-01T03:30:00.000Z",
        "val_cargaglobal": 30392.07,
        "val_cargaglobalcons": 30392.07,
        "val_cargaglobalsmmgd": ,
        "val_cargasupervisionada": 30392.07,
        "val_carganaosupervisionada": 0,
        "val_cargammgd": ,
        "val_consistencia": 0
     }]"""

# As seis meias-horas em torno da volta do horario de verao de 2018, como a API as
# entrega. Repare que 01:00 e 02:00 UTC viram as duas ocorrencias das 23:00 locais, com
# cargas diferentes. O arquivo anual do ONS so' tem onde guardar a primeira.
VOLTA_DST_2018_API = [
    {"din_referenciautc": "2018-02-18T00:30:00.000Z", "val_cargaglobalcons": 41212.52},
    {"din_referenciautc": "2018-02-18T01:00:00.000Z", "val_cargaglobalcons": 40292.01},
    {"din_referenciautc": "2018-02-18T01:30:00.000Z", "val_cargaglobalcons": 39329.48},
    {"din_referenciautc": "2018-02-18T02:00:00.000Z", "val_cargaglobalcons": 38590.98},
    {"din_referenciautc": "2018-02-18T02:30:00.000Z", "val_cargaglobalcons": 38078.402},
    {"din_referenciautc": "2018-02-18T03:00:00.000Z", "val_cargaglobalcons": 37516.54},
]


def registro_api(utc: str, valor: float | None, area: str = "SECO", dia: str = "") -> dict:
    """Um registro da API com todos os campos que o cliente le'.

    `dia` e' o dat_referencia; vazio deduz do proprio carimbo, que basta fora das
    transicoes de horario de verao.
    """
    return {
        "cod_areacarga": area,
        "din_atualizacao": "2026-08-23T03:21:06.819Z",
        "dat_referencia": dia or utc[:10],
        "din_referenciautc": utc,
        "val_cargaglobal": valor,
        "val_cargaglobalcons": valor,
        "val_consistencia": 0,
    }


def meias_horas_api(dia: str, area: str = "SECO", valor: float = 20000.0) -> list[dict]:
    """As 48 meias-horas de um dia comum, no carimbo de fim de intervalo da API.

    Vai de 03:30 UTC (00:30 local) a 03:00 UTC do dia seguinte (meia-noite local). So'
    serve para dia sem transicao de horario de verao: nos dias de transicao a contagem
    muda, e ai' o certo e' usar o recorte real de VOLTA_DST_2018_API.
    """
    inicio = pd.Timestamp(f"{dia} 03:30", tz="UTC")
    return [
        registro_api(
            (inicio + pd.Timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:00.000Z"),
            valor + i * 10,
            area=area,
            dia=dia,
        )
        for i in range(48)
    ]


def corpo(registros: list[dict]) -> str:
    """Os registros como o texto que a API devolveria, para exercitar o caminho inteiro."""
    return json.dumps(registros)
