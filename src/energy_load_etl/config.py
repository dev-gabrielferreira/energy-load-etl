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


# --- Fonte 2: API de Carga Verificada do ONS ---

URL_CARGA_VERIFICADA = "https://apicarga.ons.org.br/prd/cargaverificada"

# A API fala outro vocabulario: o subsistema que o arquivo chama de SE atende pelo
# codigo SECO. Pedir "SE" nao da' erro, devolve lista vazia, entao errar este mapa
# produz ausencia silenciosa em vez de excecao. E' por isso que ele e' explicito, e nao
# um .upper() ou um "se comeca com SE" espalhado pelo cliente.
AREAS_POR_SUBSISTEMA = {"N": "N", "NE": "NE", "S": "S", "SE": "SECO"}
SUBSISTEMAS_POR_AREA = {area: sub for sub, area in AREAS_POR_SUBSISTEMA.items()}

# A serie so existe a partir daqui. Antes disso a resposta vem vazia, identica a' de um
# parametro errado, entao a janela e' recusada localmente para os dois casos nao se
# confundirem no relatorio.
API_INICIO_SERIE = date(2016, 1, 1)

# Teto medido na fonte: uma resposta nunca traz mais de 4.944 registros, que sao 103
# dias de 48 meias-horas. Passando disso ela corta o FIM da janela e devolve HTTP 200
# sem avisar, ou seja, some justamente com os dias recentes que o modo incremental quer.
# 30 fica bem abaixo do teto, e mesmo assim a cobertura do que voltou e' conferida.
API_MAX_DIAS_POR_CHAMADA = 30

# Quantos dias para tras o modo incremental busca quando ninguem diz. O arquivo anual do
# ONS chega com alguns dias de atraso, entao 30 cobre a diferenca com folga e ainda sobra
# sobreposicao para a V7 reconciliar.
API_DIAS_PADRAO = 30

# Timeout mais curto que o dos CSVs, de proposito. La' o corpo tem dezenas de MB e demora
# mesmo; aqui a resposta de um mes nao chega a 1 MB e volta em cerca de 1 segundo, entao
# 15 ja' e' sintoma de problema, e esperar 30 so' atrasaria a primeira retentativa.
API_TIMEOUT_SEGUNDOS = 15

# Quatro tentativas com a espera dobrando (1s, 2s, 4s) somam 7 segundos de paciencia por
# janela. A API nao publica SLA nem limite de requisicoes, e o backoff protege os dois
# lados: nao insiste em cima de um servidor que ja' esta sofrendo, e sobrevive a uma
# instabilidade curta sem derrubar a execucao.
API_TENTATIVAS = 4
API_ESPERA_BASE_SEGUNDOS = 1.0


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


# V7, divergencia entre a API e o arquivo para a mesma hora.
#
# As duas fontes nao medem a mesma coisa. Medido em 35.040 horas de sobreposicao (um ano
# inteiro, agosto de 2025 a agosto de 2026), a API fica acima do arquivo em media 5,0% no
# SE, 4,3% no NE, 2,7% no S e 1,4% no N, e a diferenca tem forma de curva solar: minima de
# madrugada, maxima por volta das 13h. E' geracao distribuida, que o arquivo anual nao
# conta e a API conta, e por isso o desvio e' maior justamente onde ha' mais telhado com
# painel.
#
# Dai' o limiar ser por subsistema E por hora do dia. Uma faixa unica por subsistema
# marcaria o pico solar de todo dia: medi, e 100% das marcacoes caiam entre 7h e 14h.
# Com a faixa por hora, as marcacoes ficam uniformes ao longo do dia, que e' o sinal de
# que a regra parou de medir o sol e passou a medir anomalia.
#
# Percentis 0,5 e 99,5 de cada par (subsistema, hora), o mesmo metodo da V6. Repare que a
# curva do sol e' legivel na propria tabela: o teto do NE vai de 7,3% a' meia-noite a
# 24,7% as 11h.
LIMITE_DIVERGENCIA = {
    "N": (
        (-2.1, 6.9), (-2.2, 6.0), (-2.3, 6.3), (-2.3, 6.8),  # 00h a 03h
        (-2.3, 7.2), (-2.5, 6.7), (-3.1, 6.2), (-3.9, 11.0),  # 04h a 07h
        (-4.0, 13.7), (-3.6, 13.7), (-2.9, 17.7), (-2.2, 18.0),  # 08h a 11h
        (-1.5, 18.0), (-1.4, 18.8), (-0.8, 15.5), (-0.0, 11.9),  # 12h a 15h
        (-0.6, 10.7), (-1.3, 10.1), (-2.1, 8.8), (-2.1, 8.6),  # 16h a 19h
        (-2.1, 9.9), (-2.0, 10.2), (-2.0, 7.8), (-2.0, 5.8),  # 20h a 23h
    ),
    "NE": (
        (-3.0, 7.3), (-3.1, 7.4), (-3.1, 7.6), (-3.0, 8.1),  # 00h a 03h
        (-3.0, 8.1), (-3.6, 9.1), (-4.2, 9.4), (-2.4, 15.5),  # 04h a 07h
        (-3.0, 18.5), (-4.1, 21.7), (-2.5, 23.0), (-2.9, 24.7),  # 08h a 11h
        (-3.8, 24.2), (-2.6, 24.3), (-1.8, 20.5), (-0.2, 19.1),  # 12h a 15h
        (0.4, 15.3), (-2.8, 9.0), (-2.3, 7.5), (-1.5, 7.9),  # 16h a 19h
        (-1.3, 8.1), (-1.6, 7.9), (-2.6, 7.8), (-3.8, 8.2),  # 20h a 23h
    ),
    "S": (
        (-2.0, 9.8), (-2.1, 10.6), (-2.2, 11.1), (-2.2, 11.3),  # 00h a 03h
        (-2.3, 11.4), (-3.0, 11.1), (-3.9, 10.2), (-3.2, 8.3),  # 04h a 07h
        (-3.6, 10.3), (-4.4, 15.1), (-4.2, 20.1), (-3.8, 21.1),  # 08h a 11h
        (-3.3, 23.1), (-2.4, 23.2), (-0.9, 20.1), (-1.8, 18.4),  # 12h a 15h
        (-0.5, 15.2), (-0.8, 9.6), (-1.3, 7.1), (-1.7, 6.8),  # 16h a 19h
        (-1.8, 7.0), (-1.8, 7.2), (-1.9, 7.9), (-1.8, 8.7),  # 20h a 23h
    ),
    "SE": (
        (-0.1, 6.9), (-0.1, 7.2), (-0.1, 7.4), (-0.1, 7.5),  # 00h a 03h
        (-0.1, 7.5), (-0.3, 7.4), (-1.2, 6.4), (-1.3, 6.1),  # 04h a 07h
        (-1.3, 8.9), (-0.8, 11.9), (-0.1, 13.9), (-0.2, 15.2),  # 08h a 11h
        (0.9, 15.7), (2.0, 15.9), (2.2, 16.0), (1.8, 13.7),  # 12h a 15h
        (2.0, 10.7), (1.1, 7.5), (0.3, 5.5), (-0.2, 5.4),  # 16h a 19h
        (0.0, 5.4), (0.0, 5.6), (0.0, 5.9), (0.0, 6.3),  # 20h a 23h
    ),
}

# Quando a tabela acima foi medida, e quanto ela marcava no proprio dado da calibragem.
#
# Estao aqui porque esta regra envelhece, diferente das outras. A geracao distribuida
# cresce todo ano, entao a divergencia cresce junto, e uma faixa medida hoje fica apertada
# amanha. O relatorio compara a taxa de marcacao de cada execucao com a de referencia: se
# ela disparar, o diagnostico e' "a regua ficou velha", nao "o dado piorou". Uma regra
# calibrada que nao sabe dizer quando precisa ser remedida vira alarme que ninguem escuta.
V7_CALIBRADA_EM = (date(2025, 8, 21), date(2026, 8, 20))
V7_TAXA_CALIBRAGEM_PCT = 1.10


def criar_pastas() -> None:
    """Cria a arvore de data/ quando o pipeline roda, ja que data/ nao vai para o git."""
    for pasta in (RAW_DIR, PROCESSED_DIR, REJECTED_DIR):
        pasta.mkdir(parents=True, exist_ok=True)
