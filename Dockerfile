# Imagem unica para os dois servicos: o dashboard e o pipeline rodam do mesmo codigo,
# so mudando o comando. Duas imagens seriam duas coisas para manter em sincronia.
FROM python:3.12-slim

# O uv vem da imagem oficial dele, com versao fixa. `latest` num build de producao
# quer dizer que a imagem de amanha pode ser diferente da de hoje sem ninguem pedir.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

WORKDIR /app

# O banco de fusos horarios nao vem na imagem slim, e sem ele o zoneinfo nao conhece
# America/Sao_Paulo. Este projeto inteiro depende disso: e' o zoneinfo que responde
# quais horas existiram em cada dia, e sem ele o pipeline morre na primeira linha que
# tenta localizar um instante. Nao e' detalhe de conforto, e' dependencia de verdade.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Sao_Paulo

# As dependencias entram antes do codigo de proposito: elas mudam raramente, e assim o
# docker reaproveita esta camada em toda alteracao de codigo.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY README.md ./
COPY src/ ./src/
COPY dashboard/ ./dashboard/
COPY scripts/ ./scripts/
COPY .streamlit/ ./.streamlit/
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Usuario sem privilegio: se alguem escapar do processo, escapa para um usuario que nao
# pode fazer nada.
#
# O /dados e' criado aqui, vazio, so para carregar o dono certo. Volume nomeado nasce
# com as permissoes do diretorio que existe na imagem naquele caminho; sem este mkdir
# ele nasceria de root e o pipeline, que roda como energia, nao conseguiria escrever.
RUN useradd --create-home --uid 10001 energia \
    && mkdir -p /dados \
    && chown -R energia:energia /app /dados
USER energia
ENV HOME=/home/energia

EXPOSE 8501

# O proprio Streamlit responde por este endereco, entao o healthcheck testa a aplicacao
# de verdade, nao so se a porta abriu.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "dashboard/app.py"]
