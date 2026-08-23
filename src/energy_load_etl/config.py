"""Constantes do pipeline em um lugar so: fonte, caminhos e limiares de validacao."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# --- Fonte: Curva de Carga Horaria do ONS ---

URL_CURVA_CARGA = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com"
    "/dataset/curva-carga-ho/CURVA_CARGA_{ano}.csv"
)

ANO_INICIO = 2000

# Calculado, e nao fixo, para o pipeline enxergar o ano novo sem alguem editar o
# codigo em janeiro. O arquivo do ano corrente pode ainda nao existir no S3 no
# comeco do ano, e o extract trata esse 404 como ausencia esperada.
ANO_FIM = date.today().year

ANOS = range(ANO_INICIO, ANO_FIM + 1)

CSV_SEPARADOR = ";"
CSV_ENCODING = "utf-8"

# Ordem exata do dicionario de dados do ONS. A V1 compara contra isto.
COLUNAS_CONTRATO = (
    "id_subsistema",
    "nom_subsistema",
    "din_instante",
    "val_cargaenergiahomwmed",
)

TIMEOUT_SEGUNDOS = 30


# --- Caminhos ---

RAIZ_PROJETO = Path(__file__).resolve().parents[2]

# String vazia no .env cai no fallback, entao copiar o .env.example sem editar funciona.
DATA_DIR = Path(os.getenv("DATA_DIR") or RAIZ_PROJETO / "data")

RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REJECTED_DIR = DATA_DIR / "rejected"

# Guarda ETag e tamanho de cada CSV baixado, para o extract decidir re-download
# sem puxar o arquivo inteiro.
MANIFESTO = RAW_DIR / "_manifest.json"


# --- Validacao ---

FUSO = "America/Sao_Paulo"


# --- Dashboard ---

# Para onde o link de volta do topo aponta. Fica no .env porque muda por ambiente: na
# maquina do Gabriel nao ha portfolio nenhum rodando, e na VPS ha. Vazio esconde o link
# em vez de deixar um botao que nao leva a lugar algum.
PORTFOLIO_URL = os.getenv("PORTFOLIO_URL", "").strip()
PORTFOLIO_NOME = os.getenv("PORTFOLIO_NOME", "Portfólio").strip()

SUBSISTEMAS_VALIDOS = frozenset({"N", "NE", "S", "SE"})

# V5, faixa fisica. Carga zero ou negativa nao existe num sistema interligado em
# operacao. O teto de 120 GWmed fica bem acima do recorde do SIN (cerca de 103 GW
# em 2024), entao ele pega absurdo de digitacao ou de unidade, nao pico real.
CARGA_MIN_MWMED = 0.0
CARGA_MAX_MWMED = 120_000.0

# V6, salto entre horas consecutivas. Dois criterios ao mesmo tempo, porque cada um
# sozinho falha de um jeito diferente:
#   - So absoluto erode conforme o sistema cresce. 5.780 MWmed eram 16,5% do pico do
#     SE em 2000 e sao 9,9% hoje, entao o mesmo numero fica mais sensivel a cada ano.
#   - So relativo dispara por nada quando a carga base e' pequena. A recuperacao depois
#     do apagao de 2018 no NE marca 409%, saindo de uma carga residual de 665 MWmed.
# Medidos no historico 2000-2026: percentil 99,9 do salto relativo e percentil 99 do
# absoluto, arredondados. Marcam cerca de 0,09% das horas, uns 34 casos por ano, e
# pegam os apagoes de 2009, 2013 e 2018. Ver docs/decisions.md.
LIMITE_SALTO = {
    "N": {"relativo_pct": 15.0, "piso_mwmed": 400.0},
    "NE": {"relativo_pct": 24.0, "piso_mwmed": 1150.0},
    "S": {"relativo_pct": 27.5, "piso_mwmed": 1530.0},
    "SE": {"relativo_pct": 20.5, "piso_mwmed": 3850.0},
}


def criar_pastas() -> None:
    """Cria a arvore de data/ quando o pipeline roda, ja que data/ nao vai para o git."""
    for pasta in (RAW_DIR, PROCESSED_DIR, REJECTED_DIR):
        pasta.mkdir(parents=True, exist_ok=True)
