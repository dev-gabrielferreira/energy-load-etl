"""Dashboard da carga de energia do SIN.

Le exclusivamente `data/processed/`. Nunca abre o CSV bruto nem o relatorio de
rejeitados: o que o dashboard mostra e' o que passou pela validacao, e ate a tabela de
qualidade vem do Parquet, nao dos arquivos de rejeicao.

Comentarios e docstrings seguem a convencao do resto do codigo e vao sem acento. Os
textos que aparecem na tela sao acentuados, porque quem le e' gente.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from energy_load_etl import config, load

st.set_page_config(page_title="Carga de energia do Brasil", page_icon="⚡", layout="wide")

SUBSISTEMAS = ("N", "NE", "S", "SE")
NOMES = {"N": "Norte", "NE": "Nordeste", "S": "Sul", "SE": "Sudeste/Centro-Oeste"}
MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")

# Um conjunto de cores so, para os dois temas.
#
# A tentativa anterior trocava a paleta conforme o tema detectado, e nao funcionava:
# o Streamlit muda de tema sem re-executar o script, entao a deteccao chegava sempre
# atrasada e o grafico ficava com a superficie do tema errado. Estas quatro cores tem
# contraste suficiente tanto sobre fundo branco quanto sobre fundo quase preto, o que
# dispensa saber em qual dos dois a pessoa esta lendo.
CORES = {"N": "#2a78d6", "NE": "#eb6834", "S": "#1baf7a", "SE": "#eda100"}
CORES_DIA = {"Dia útil": "#2a78d6", "Fim de semana": "#eb6834", "Feriado": "#1baf7a"}

# Cinza de meio-termo e grade translucida: legiveis nos dois fundos pelo mesmo motivo.
# Este cinza foi procurado, nao escolhido a olho: e' o que maximiza o pior dos dois
# contrastes, 3,85 sobre o cartao claro e 3,81 sobre o escuro.
TINTA_EIXO = "#7d7d79"
GRADE = "rgba(125, 125, 121, 0.30)"

# Fundo do grafico por opacidade, e nao por cor absoluta. Um cinza com alfa baixo por
# cima do fundo da pagina clareia o tema escuro e escurece o tema claro, na medida certa
# nos dois, sem que o codigo precise saber em qual deles esta. A area de plotagem leva
# um pouco mais de tinta que a moldura, e e' isso que da' inicio e fim visiveis ao
# desenho. Tentativa anterior: pintar por CSS no cartao do Streamlit, que nao pegou
# porque esta versao nao expoe a classe onde o seletor mirava.
SUPERFICIE_CARTAO = "rgba(128, 128, 122, 0.06)"
SUPERFICIE_PLOTAGEM = "rgba(128, 128, 122, 0.13)"

# O tooltip tem superficie propria e sempre escura, entao aqui entram os tons da paleta
# calibrados para fundo escuro. E' o que permite escrever o nome de cada subsistema na
# cor da linha dele sem que amarelo sobre branco vire um borrao.
TOOLTIP_FUNDO = "#1f1f1e"
TOOLTIP_BORDA = "rgba(255, 255, 255, 0.18)"
CORES_TOOLTIP = {"N": "#5598e7", "NE": "#f07f52", "S": "#2ec98f", "SE": "#f0b437"}
CORES_TOOLTIP_DIA = {"Dia útil": "#5598e7", "Fim de semana": "#f07f52", "Feriado": "#2ec98f"}

# Escala sequencial de uma cor so: a magnitude vira opacidade, do quase invisivel ao
# azul cheio. Como e' a mesma cor variando alfa, "mais tinta e' mais carga" continua
# verdadeiro sobre qualquer fundo, sem precisar de uma versao por tema.
RAMPA = [
    [0.0, "rgba(57, 135, 229, 0.10)"],
    [0.25, "rgba(57, 135, 229, 0.34)"],
    [0.5, "rgba(57, 135, 229, 0.56)"],
    [0.75, "rgba(57, 135, 229, 0.78)"],
    [1.0, "rgba(57, 135, 229, 1.0)"],
]

# Metrica escolhida no filtro -> coluna do agregado, unidade, e se faz sentido somar os
# subsistemas. Maximo e minimo nao somam: o pico do Norte e o do Sul acontecem em horas
# diferentes, entao a soma dos dois nao e' pico de coisa nenhuma.
METRICAS = {
    "Carga média": ("carga_media_mwmed", "MWmed", True),
    "Carga máxima": ("carga_max_mwmed", "MWmed", False),
    "Carga mínima": ("carga_min_mwmed", "MWmed", False),
    "Energia": ("energia_mwh", "MWh", True),
}

SERIF = 'Georgia, "Iowan Old Style", "Times New Roman", serif'
SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif'


def dica(nome: str, unidade: str, cor: str) -> str:
    """Linha do tooltip escrita na cor da propria serie.

    O nome e o valor saem juntos e na mesma cor da linha, entao nao e' preciso conferir
    a legenda para saber de quem e' o numero que esta debaixo do cursor.
    """
    return (
        f'<span style="color:{cor}"><b>{nome}</b>   %{{y:,.0f}} {unidade}</span><extra></extra>'
    )


def aplicar_tipografia() -> None:
    """Tres niveis de texto, com fontes diferentes de proposito.

    Titulo em serif, subtitulo e corpo em sans. A troca de familia separa os niveis
    mais depressa que so mudar o tamanho, e o olho encontra a estrutura da pagina sem
    precisar ler nada.

    Nenhuma cor fixa aqui, so as variaveis do proprio Streamlit. Trocar de tema no menu
    nao re-executa o script, entao CSS com hex escrito na mao continuaria com a cor do
    tema anterior, e era isso que deixava o texto ilegivel depois da troca.
    """
    st.markdown(
        f"""
        <style>
        .stApp h1 {{
            font-family: {SERIF};
            font-weight: 700;
            font-size: 2.6rem;
            letter-spacing: -0.025em;
            line-height: 1.15;
            color: var(--text-color);
            margin-bottom: 0.2rem;
        }}
        .stApp h3 {{
            font-family: {SANS};
            font-weight: 600;
            font-size: 1.15rem;
            letter-spacing: -0.01em;
            color: var(--text-color);
            margin: 0.6rem 0 0.4rem 0;
        }}
        .stApp p, .stApp label {{
            font-family: {SANS};
        }}
        .abertura {{
            font-family: {SANS};
            font-size: 1.02rem;
            line-height: 1.65;
            color: var(--text-color);
            opacity: 0.85;
            max-width: 62ch;
            margin-bottom: 0.6rem;
        }}
        .nota {{
            background: var(--secondary-background-color);
            border-left: 3px solid var(--primary-color);
            border-radius: 10px;
            padding: 0.9rem 1.1rem;
            margin: 0.7rem 0 0.3rem 0;
            font-family: {SANS};
            font-size: 0.93rem;
            line-height: 1.65;
            color: var(--text-color);
            opacity: 0.92;
        }}
        .nota strong {{
            font-weight: 600;
        }}
        .termo {{
            font-family: {SANS};
            font-size: 0.93rem;
            line-height: 1.7;
            color: var(--text-color);
        }}
        .navbar {{
            display: flex;
            align-items: center;
            gap: 0.9rem;
            padding: 0 0 0.7rem 0;
            margin-bottom: 1.1rem;
            border-bottom: 1px solid var(--secondary-background-color);
            font-family: {SANS};
            font-size: 0.9rem;
        }}
        .navbar a {{
            color: var(--text-color);
            text-decoration: none;
            opacity: 0.75;
            transition: opacity 0.15s ease;
        }}
        .navbar a:hover {{
            opacity: 1;
            text-decoration: underline;
        }}
        .navbar .aqui {{
            color: var(--text-color);
            opacity: 0.45;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def nota(texto: str) -> None:
    """Texto explicativo dentro de um cartao, separado do grafico que ele comenta."""
    st.markdown(f'<div class="nota">{texto}</div>', unsafe_allow_html=True)


def navbar() -> None:
    """Caminho de volta para o portfolio, no topo da pagina.

    Sai do ar quando PORTFOLIO_URL nao esta configurada, que e' o caso na maquina de
    desenvolvimento: link que nao leva a lugar nenhum e' pior que a falta dele.
    """
    if not config.PORTFOLIO_URL:
        return

    st.markdown(
        f'<div class="navbar">'
        f'<a href="{config.PORTFOLIO_URL}">← {config.PORTFOLIO_NOME}</a>'
        f'<span class="aqui">/ Carga de energia do Brasil</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


# O prazo do cache existe por causa da producao: o pipeline reescreve o Parquet duas
# vezes por dia, e cache sem prazo deixaria o painel servindo o dado da hora em que o
# container subiu, para sempre.
VALIDADE_DO_CACHE = 30 * 60


@st.cache_data(ttl=VALIDADE_DO_CACHE)
def ler(nome: str) -> pd.DataFrame:
    return load.ler_agregado(nome)


@st.cache_data(ttl=VALIDADE_DO_CACHE)
def ler_horas(ano: int, subsistema: str) -> pd.DataFrame:
    """As 8.760 horas de um ano e um subsistema. O filtro vira poda de pasta no pyarrow."""
    return load.ler_horario(anos=[ano], subsistemas=[subsistema])


def tipo_de_dia(df: pd.DataFrame) -> pd.Series:
    """Dia util, fim de semana ou feriado.

    Feriado por ultimo de proposito: feriado que cai no domingo continua sendo feriado,
    e o que interessa aqui e' o comportamento da carga, nao a contagem de categorias.
    """
    tipo = pd.Series("Dia útil", index=df.index)
    tipo[df["fim_de_semana"]] = "Fim de semana"
    tipo[df["feriado"]] = "Feriado"
    return tipo


def primeiro_do_mes(df: pd.DataFrame) -> pd.Series:
    """Ano e mes viram data, que e' o que um eixo de tempo entende."""
    return pd.to_datetime(dict(year=df["ano"], month=df["mes"], day=1))


def rotular_fim(fig: go.Figure, altura: int) -> go.Figure:
    """Escreve o nome de cada serie no fim da linha, na cor dela.

    Assim a identidade nao depende so de achar a cor na legenda, que e' um vai e volta
    que o olho paga a cada leitura. Rotulos que ficariam colados sao afastados na
    vertical, porque dois nomes empilhados leem pior que rotulo nenhum.
    """
    pontos = []
    for trace in fig.data:
        if trace.y is None or not len(trace.y):
            continue
        pontos.append([trace.x[-1], float(trace.y[-1]), trace.name, trace.line.color])

    if len(pontos) < 2:
        return fig

    pontos.sort(key=lambda p: p[1])
    faixa = pontos[-1][1] - pontos[0][1] or 1
    folga = faixa * (17 / max(altura - 70, 1))  # 17 px convertidos para a escala do eixo
    for anterior, atual in zip(pontos, pontos[1:]):
        if atual[1] - anterior[1] < folga:
            atual[1] = anterior[1] + folga

    for x, y, nome, cor in pontos:
        fig.add_annotation(
            x=x,
            y=y,
            text=f"  {nome}",
            showarrow=False,
            xanchor="left",
            yanchor="middle",
            font=dict(color=cor, size=12),
        )
    return fig


def estilo(fig: go.Figure, altura: int = 380, rotular: bool = False) -> go.Figure:
    """Layout comum: superficie do cartao por baixo, grade discreta, crosshair e hover.

    O fundo fica transparente para o cartao do Streamlit aparecer atras. E' ele que
    responde ao tema, em CSS, e quem faz isso acerta sempre, porque nao depende de o
    Python ter adivinhado em qual tema a pagina esta sendo lida.
    """
    if rotular:
        rotular_fim(fig, altura)

    fig.update_layout(
        height=altura,
        # Espaco a direita para os rotulos de fim de linha, e no topo para a legenda.
        margin=dict(l=12, r=150 if rotular else 20, t=44, b=12),
        paper_bgcolor=SUPERFICIE_CARTAO,
        plot_bgcolor=SUPERFICIE_PLOTAGEM,
        font=dict(color=TINTA_EIXO, size=13, family=SANS),
        # Decimal com virgula e milhar com ponto, senao o tooltip mostra 3,313 MWmed
        # para tres mil e trezentos, que em portugues le como tres e pouco.
        separators=",.",
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=TOOLTIP_FUNDO,
            bordercolor=TOOLTIP_BORDA,
            font=dict(color="#f2f1ec", size=13, family=SANS),
        ),
        legend=dict(
            orientation="h", y=1.14, x=0, title=None, font=dict(color=TINTA_EIXO, size=12)
        ),
    )
    # A linha vertical que segue o cursor: em serie longa, ligar o ponto ao eixo de olho
    # e' onde a leitura erra.
    fig.update_xaxes(
        showgrid=False,
        linecolor=GRADE,
        tickcolor=GRADE,
        tickfont=dict(color=TINTA_EIXO),
        showspikes=True,
        spikecolor=TINTA_EIXO,
        spikethickness=1,
        spikedash="dot",
        spikemode="across",
    )
    fig.update_yaxes(
        gridcolor=GRADE,
        zeroline=False,
        tickfont=dict(color=TINTA_EIXO),
        title_font=dict(size=12, color=TINTA_EIXO),
    )
    return fig


def grafico(fig: go.Figure, altura: int = 380, rotular: bool = False, legenda: str = "") -> None:
    """Desenha o grafico dentro de um cartao, com a legenda dele junto.

    A borda separa um grafico do outro. Sem ela, dois graficos empilhados viram uma
    mancha continua e o olho nao sabe onde um assunto termina.
    """
    with st.container(border=True):
        st.plotly_chart(estilo(fig, altura, rotular), width="stretch")
        if legenda:
            st.caption(legenda)


def numero(valor: float) -> str:
    return f"{valor:,.0f}".replace(",", ".")


# Fundo translucido em vez de cor de texto: rgba com alfa baixo funciona igual sobre
# fundo claro e escuro, entao a tabela nao precisa saber em que tema esta sendo lida.
ALERTA = "rgba(227, 73, 72, 0.20)"
ATENCAO = "rgba(235, 104, 52, 0.20)"
HORAS_DE_HORARIO_DE_VERAO = 4


def pintar_qualidade(tabela: pd.DataFrame) -> pd.DataFrame:
    """Marca o ano que foge do normal, para o olho achar antes de ler.

    Quatro horas faltantes e' o esperado ate 2019, uma por subsistema, e nao merece
    alarme. Acima disso houve falha de coleta, que e' outra conversa.
    """
    cores = pd.DataFrame("", index=tabela.index, columns=tabela.columns)
    cores.loc[tabela["Rejeitadas"] > 0, "Rejeitadas"] = f"background-color: {ALERTA}"
    cores.loc[tabela["Horas faltantes"] > HORAS_DE_HORARIO_DE_VERAO, "Horas faltantes"] = (
        f"background-color: {ATENCAO}"
    )
    return cores


def media_anual(mensal: pd.DataFrame, ano: int) -> float:
    """Carga media do SIN num ano, em MWmed.

    Energia dividida pelas horas que foram medidas, e so entao somada entre os
    subsistemas. Media de medias mensais pesaria fevereiro igual a janeiro, e um mes
    que perdeu horas igual a um mes inteiro. E' para isso que o agregado carrega
    energia_mwh e horas_presentes lado a lado.
    """
    ano_escolhido = mensal[mensal["ano"] == ano].groupby("id_subsistema")
    return (ano_escolhido["energia_mwh"].sum() / ano_escolhido["horas_presentes"].sum()).sum()


# --- pagina -------------------------------------------------------------------

aplicar_tipografia()
navbar()

try:
    mensal = ler(load.MENSAL)
    diario = ler(load.DIARIO)
    qualidade = ler(load.QUALIDADE)
except FileNotFoundError:
    # Acontece de verdade na primeira subida em producao: o dashboard fica de pe' antes
    # de o pipeline terminar o primeiro processamento. Melhor dizer isso do que mostrar
    # um traceback para quem abriu o link.
    st.title("Carga de energia do Brasil")
    st.info(
        "Os dados ainda estão sendo processados. O pipeline baixa 26 anos de medições "
        "do ONS e leva alguns minutos na primeira execução. Recarregue a página em "
        "instantes."
    )
    st.stop()

st.title("Carga de energia do Brasil")
st.markdown(
    '<p class="abertura">Quanta eletricidade o país consumiu em cada hora dos últimos '
    "26 anos. A rede elétrica brasileira é operada como um sistema único, o "
    "<strong>Sistema Interligado Nacional (SIN)</strong>, dividido em quatro regiões "
    "chamadas subsistemas. São 933 mil medições publicadas pelo ONS, o operador da "
    "rede, conferidas uma a uma antes de chegarem aqui.</p>",
    unsafe_allow_html=True,
)

with st.expander("O que significa cada termo"):
    st.markdown(
        '<div class="termo">'
        "<strong>SIN (Sistema Interligado Nacional)</strong> é a rede que conecta quase "
        "toda a geração e o consumo de eletricidade do país. Como tudo está ligado, a "
        "energia gerada no Norte pode acender uma lâmpada no Sul.<br><br>"
        "<strong>Subsistema</strong> é cada uma das quatro regiões em que o SIN é "
        "dividido para operação: Norte, Nordeste, Sul e Sudeste/Centro-Oeste.<br><br>"
        "<strong>ONS (Operador Nacional do Sistema Elétrico)</strong> é quem coordena a "
        "operação da rede e publica estes dados abertamente.<br><br>"
        "<strong>Carga</strong> é o quanto está sendo consumido num dado momento, não o "
        "quanto poderia ser gerado.<br><br>"
        "<strong>MWmed (megawatt médio)</strong> é a potência média ao longo de um "
        "período. Uma hora a 1 MWmed consome 1 MWh de energia. É a unidade que o ONS "
        "usa porque permite comparar uma hora com um mês inteiro sem fazer conta.<br><br>"
        "<strong>MWh (megawatt-hora)</strong> é a quantidade de energia consumida, o que "
        "aparece na sua conta de luz em kWh. Um MWh são mil kWh.<br><br>"
        "<strong>Período completo</strong> é um dia ou mês em que todas as horas foram "
        "medidas. Quando falta alguma, o painel avisa em vez de fingir que o número "
        "está inteiro."
        "</div>",
        unsafe_allow_html=True,
    )

geral, explorar, subsistemas, perfil, sazonalidade, dado = st.tabs(
    [
        "Visão geral",
        "Explorar",
        "Subsistemas",
        "Perfil do dia",
        "Sazonalidade",
        "Qualidade do dado",
    ]
)

# --- visao geral --------------------------------------------------------------

with geral:
    pico = diario.loc[diario["carga_max_mwmed"].idxmax()]
    ultimo_ano = int(mensal["ano"].max())

    kpi = st.columns(4)
    kpi[0].metric(
        "Período coberto", f"{diario['ano'].min()} a {diario['ano'].max()}", border=True
    )
    kpi[1].metric(
        f"Carga média do SIN em {ultimo_ano}",
        f"{numero(media_anual(mensal, ultimo_ano))} MWmed",
        help=(
            "Toda a energia do ano dividida pelas horas que foram medidas, somando os "
            "quatro subsistemas. Somar as médias de cada mês daria um número doze "
            "vezes maior, e errado."
        ),
        border=True,
    )
    kpi[2].metric(
        f"Maior carga em uma hora ({pico['id_subsistema']})",
        f"{numero(pico['carga_max_mwmed'])} MWmed",
        help=(
            f"A hora de maior consumo de todo o histórico, em {pico['data']:%d/%m/%Y}, "
            f"no {NOMES[pico['id_subsistema']]}."
        ),
        border=True,
    )
    kpi[3].metric(
        "Dias medidos por inteiro",
        f"{diario['completo'].mean() * 100:.2f}%",
        help=(
            f"{int((~diario['completo']).sum())} dias ficaram incompletos, de "
            f"{len(diario)}. Quase todos por causa de uma única hora, a que o horário "
            "de verão apagava toda virada de fevereiro até 2019."
        ),
        border=True,
    )

    st.subheader("O consumo do país, mês a mês")
    sin = mensal.groupby(["ano", "mes"], as_index=False)["carga_media_mwmed"].sum()
    sin["periodo"] = primeiro_do_mes(sin)

    figura = go.Figure(
        go.Scatter(
            x=sin["periodo"],
            y=sin["carga_media_mwmed"],
            mode="lines",
            line=dict(color=CORES["SE"], width=2),
            name="Brasil",
            hovertemplate=dica("Brasil", "MWmed", CORES_TOOLTIP["SE"]),
        )
    )
    figura.update_xaxes(hoverformat="%m/%Y")
    figura.update_yaxes(title_text="MWmed")
    grafico(figura, legenda="Soma da carga média dos quatro subsistemas em cada mês.")

    nota(
        f"O consumo do país <strong>dobrou em 26 anos</strong>: saiu de "
        f"{numero(sin['carga_media_mwmed'].iloc[0])} MWmed em janeiro de 2000 e chegou a "
        f"{numero(sin['carga_media_mwmed'].iloc[-1])} MWmed no último mês medido. A "
        "queda visível em 2001 é o racionamento, e a de 2020 é a pandemia."
    )

# --- explorar -----------------------------------------------------------------

with explorar:
    st.subheader("Monte a sua própria visão")
    nota(
        "Escolha o período, os subsistemas e o que quer medir. A tabela com os números "
        "e o botão de baixar em CSV ficam no fim da página."
    )

    filtros = st.columns([2.4, 2.4, 1.6, 1.6])
    anos_limite = (int(diario["ano"].min()), int(diario["ano"].max()))
    periodo = filtros[0].slider("Período", *anos_limite, value=anos_limite)
    escolhidos_livre = filtros[1].multiselect(
        "Subsistemas",
        options=list(SUBSISTEMAS),
        default=list(SUBSISTEMAS),
        format_func=lambda s: NOMES[s],
        key="subs_livre",
    )
    granularidade = filtros[2].segmented_control(
        "Ver por", options=["Mês", "Dia"], default="Mês"
    )
    nome_metrica = filtros[3].selectbox("O que medir", options=list(METRICAS))

    coluna, unidade, pode_somar = METRICAS[nome_metrica]
    opcoes = st.columns([1.2, 1.4, 2.4])
    somar = opcoes[0].toggle("Somar tudo como SIN", value=False, disabled=not pode_somar)
    so_completos = opcoes[1].toggle("Só períodos completos", value=False)

    if not pode_somar:
        opcoes[2].caption(
            f"{nome_metrica} não pode ser somada entre subsistemas: o pico do Norte e o "
            "do Sul acontecem em horas diferentes."
        )

    base = (diario if granularidade == "Dia" else mensal).copy()
    base = base[base["ano"].between(*periodo) & base["id_subsistema"].isin(escolhidos_livre)]
    if so_completos:
        base = base[base["completo"]]

    base["periodo"] = (
        pd.to_datetime(base["data"]) if granularidade == "Dia" else primeiro_do_mes(base)
    )
    base = base.dropna(subset=[coluna])

    if base.empty:
        st.info("Nada para mostrar com esses filtros. Amplie o período ou marque um subsistema.")
    else:
        # Acima de uns milhares de pontos o SVG do plotly engasga, e o Scattergl desenha
        # o mesmo grafico na GPU. A troca e' so de classe, o resto do codigo e' igual.
        traco = go.Scattergl if len(base) > 4000 else go.Scatter

        figura = go.Figure()
        if somar:
            juntos = base.groupby("periodo", as_index=False)[coluna].sum()
            figura.add_trace(
                traco(
                    x=juntos["periodo"],
                    y=juntos[coluna],
                    mode="lines",
                    name="SIN",
                    line=dict(color=CORES["SE"], width=2),
                    hovertemplate=dica("Brasil", unidade, CORES_TOOLTIP["SE"]),
                )
            )
        else:
            for sub in SUBSISTEMAS:
                parte = base[base["id_subsistema"] == sub]
                if parte.empty:
                    continue
                figura.add_trace(
                    traco(
                        x=parte["periodo"],
                        y=parte[coluna],
                        mode="lines",
                        name=NOMES[sub],
                        line=dict(color=CORES[sub], width=2),
                        hovertemplate=dica(NOMES[sub], unidade, CORES_TOOLTIP[sub]),
                    )
                )

        figura.update_xaxes(hoverformat="%d/%m/%Y" if granularidade == "Dia" else "%m/%Y")
        figura.update_yaxes(title_text=unidade)
        incompletos = int((~base["completo"]).sum())
        grafico(
            figura,
            altura=460,
            rotular=not somar and len(escolhidos_livre) > 1,
            legenda=(
                f"{nome_metrica}, de {periodo[0]} a {periodo[1]}, "
                f"{'por dia' if granularidade == 'Dia' else 'por mês'}."
            ),
        )

        if incompletos and not so_completos:
            nota(
                f"<strong>{incompletos} dos {len(base)} períodos deste recorte estão "
                "incompletos.</strong> A média deles continua confiável, mas a energia "
                "aparece menor que a real, porque hora que não foi medida não entra na "
                "soma. Use o botão acima para escondê-los."
            )

        with st.expander("Ver os números"):
            st.dataframe(base.drop(columns=["periodo"]), hide_index=True, width="stretch")
            st.download_button(
                "Baixar este recorte em CSV",
                base.drop(columns=["periodo"]).to_csv(index=False).encode("utf-8"),
                file_name=f"carga_{granularidade.lower()}_{periodo[0]}_{periodo[1]}.csv",
                mime="text/csv",
            )

# --- subsistemas --------------------------------------------------------------

with subsistemas:
    st.subheader("Cada região puxa uma parte")

    fatia = mensal.groupby(["ano", "id_subsistema"])["carga_media_mwmed"].mean().unstack()
    fatia = fatia.div(fatia.sum(axis=1), axis=0) * 100
    primeiro_ano, ultimo_cheio = int(fatia.index.min()), int(fatia.index.max()) - 1
    nota(
        "O Sistema Interligado Nacional é dividido em quatro subsistemas. O "
        "Sudeste/Centro-Oeste sozinho responde por mais da metade da carga do país, mas "
        f"<strong>sua fatia vem encolhendo</strong>: era {fatia.loc[primeiro_ano, 'SE']:.0f}% "
        f"em {primeiro_ano} e é {fatia.loc[ultimo_cheio, 'SE']:.0f}% em {ultimo_cheio}. "
        "Quem mais ganhou espaço no período foi o Norte."
    )

    escolhidos = st.multiselect(
        "Subsistemas",
        options=list(SUBSISTEMAS),
        default=list(SUBSISTEMAS),
        format_func=lambda s: NOMES[s],
    )

    serie = mensal[mensal["id_subsistema"].isin(escolhidos)].copy()
    serie["periodo"] = primeiro_do_mes(serie)

    figura = go.Figure()
    for sub in SUBSISTEMAS:
        if sub not in escolhidos:
            continue
        parte = serie[serie["id_subsistema"] == sub]
        figura.add_trace(
            go.Scatter(
                x=parte["periodo"],
                y=parte["carga_media_mwmed"],
                mode="lines",
                name=NOMES[sub],
                line=dict(color=CORES[sub], width=2),
                hovertemplate=dica(NOMES[sub], "MWmed", CORES_TOOLTIP[sub]),
            )
        )
    figura.update_xaxes(hoverformat="%m/%Y")
    figura.update_yaxes(title_text="MWmed")
    grafico(figura, altura=420, rotular=True, legenda="Carga média de cada subsistema, por mês.")

    figura = go.Figure()
    total = serie.groupby("periodo")["carga_media_mwmed"].transform("sum")
    serie["participacao"] = serie["carga_media_mwmed"] / total * 100
    for sub in SUBSISTEMAS:
        if sub not in escolhidos:
            continue
        parte = serie[serie["id_subsistema"] == sub]
        figura.add_trace(
            go.Scatter(
                x=parte["periodo"],
                y=parte["participacao"],
                mode="lines",
                name=NOMES[sub],
                line=dict(color=CORES[sub], width=2),
                hovertemplate=(
                    f'<span style="color:{CORES_TOOLTIP[sub]}"><b>{NOMES[sub]}</b>'
                    "   %{y:.1f}%</span><extra></extra>"
                ),
            )
        )
    figura.update_xaxes(hoverformat="%m/%Y")
    figura.update_yaxes(title_text="% do total do país")
    grafico(
        figura,
        altura=340,
        rotular=True,
        legenda="Quanto cada subsistema representa do total, mês a mês.",
    )

# --- perfil do dia ------------------------------------------------------------

with perfil:
    st.subheader("Como a carga se comporta ao longo do dia")
    nota(
        "Esta é a única tela que abre os dados hora a hora. As outras leem tabelas já "
        "resumidas pelo pipeline, e por isso carregam na hora."
    )

    filtros = st.columns(2)
    ano_perfil = filtros[0].selectbox(
        "Ano", options=sorted(diario["ano"].unique(), reverse=True), key="ano_perfil"
    )
    sub_perfil = filtros[1].selectbox(
        "Subsistema", options=list(SUBSISTEMAS), format_func=lambda s: NOMES[s]
    )

    horas = ler_horas(int(ano_perfil), sub_perfil).copy()
    horas["tipo"] = tipo_de_dia(horas)
    media = horas.groupby(["tipo", "hora"], as_index=False)["val_cargaenergiahomwmed"].mean()

    figura = go.Figure()
    for nome_tipo, cor in CORES_DIA.items():
        parte = media[media["tipo"] == nome_tipo]
        if parte.empty:
            continue
        figura.add_trace(
            go.Scatter(
                x=parte["hora"],
                y=parte["val_cargaenergiahomwmed"],
                mode="lines+markers",
                name=nome_tipo,
                line=dict(color=cor, width=2),
                marker=dict(size=8),
                hovertemplate=dica(nome_tipo, "MWmed", CORES_TOOLTIP_DIA[nome_tipo]),
            )
        )
    figura.update_xaxes(title_text="hora do dia", dtick=3)
    figura.update_yaxes(title_text="MWmed")

    contagem = horas.groupby("tipo")["data"].nunique()
    grafico(
        figura,
        altura=420,
        legenda=(
            "Média de cada hora em "
            + ", ".join(f"{n} dias de {t.lower()}" for t, n in contagem.items())
            + "."
        ),
    )

    pico_util = media[media["tipo"] == "Dia útil"]
    if not pico_util.empty:
        hora_pico = int(pico_util.loc[pico_util["val_cargaenergiahomwmed"].idxmax(), "hora"])
        nota(
            f"O dia útil tem <strong>vale de madrugada e pico às {hora_pico}h</strong>. "
            "Entre 9h e 15h a distância para o fim de semana é a indústria e o comércio "
            "ligados. Por volta das 18h as três curvas se aproximam: à noite o consumo é "
            "quase todo residencial, e a essa hora todo mundo está em casa de qualquer jeito. "
            "Feriado que cai no fim de semana conta como feriado."
        )

# --- sazonalidade -------------------------------------------------------------

with sazonalidade:
    st.subheader("O ano inteiro de uma olhada")
    nota(
        "Cada quadradinho é um mês. Lendo de cima para baixo aparece o crescimento do "
        "consumo ao longo dos anos; da esquerda para a direita, o verão puxando mais "
        "que o inverno."
    )

    alvo = st.selectbox(
        "Mostrar",
        options=["SIN", *SUBSISTEMAS],
        format_func=lambda s: "Brasil inteiro (SIN)" if s == "SIN" else NOMES[s],
    )

    if alvo == "SIN":
        base = mensal.groupby(["ano", "mes"], as_index=False)["carga_media_mwmed"].sum()
    else:
        base = mensal[mensal["id_subsistema"] == alvo]

    grade = base.pivot(index="ano", columns="mes", values="carga_media_mwmed")

    figura = go.Figure(
        go.Heatmap(
            z=grade.values,
            x=[MESES[m - 1] for m in grade.columns],
            y=grade.index,
            colorscale=RAMPA,
            hovertemplate="%{y} %{x}<br>%{z:,.0f} MWmed<extra></extra>",
            colorbar=dict(title="MWmed", thickness=12, outlinewidth=0),
            xgap=2,
            ygap=2,
        )
    )
    figura.update_yaxes(title_text=None, dtick=2, autorange="reversed")
    grafico(
        figura,
        altura=560,
        legenda="Carga média de cada mês. Os quadrados vazios de 2026 são meses que ainda não aconteceram.",
    )

# --- qualidade do dado --------------------------------------------------------

with dado:
    st.subheader("O que entrou, o que ficou de fora e por quê")
    nota(
        "Dizer quantas linhas foram descartadas, e por qual motivo, é informação, não "
        "vergonha. Esta tabela é escrita pelo próprio pipeline a cada execução."
    )

    resumo = st.columns(4)
    resumo[0].metric("Linhas lidas", numero(qualidade["lidas"].sum()), border=True)
    resumo[1].metric(
        "Aprovadas",
        numero(qualidade["aprovadas"].sum()),
        help=f"{qualidade['aprovadas'].sum() / qualidade['lidas'].sum() * 100:.4f}% do total.",
        border=True,
    )
    resumo[2].metric(
        "Horas que existiram e não chegaram",
        numero(qualidade["buracos"].sum()),
        help=(
            "Encontradas comparando o que chegou com todas as horas que o relógio "
            "brasileiro realmente teve. A maior parte é a hora que o horário de verão "
            "apagava, uma por subsistema por ano, até 2019."
        ),
        border=True,
    )
    resumo[3].metric(
        "Horas com salto atípico",
        numero(qualidade["marcadas"].sum()),
        help=(
            "Marcada quer dizer que merece um olhar humano, não que o dado esteja "
            "errado. Os dez maiores saltos do histórico são quatro apagões e seis "
            "jogos de Copa do Mundo."
        ),
        border=True,
    )

    tabela = qualidade.rename(
        columns={
            "ano": "Ano",
            "lidas": "Lidas",
            "aprovadas": "Aprovadas",
            "rejeitadas": "Rejeitadas",
            "buracos": "Horas faltantes",
            "marcadas": "Saltos marcados",
        }
    )[["Ano", "Lidas", "Aprovadas", "Rejeitadas", "Horas faltantes", "Saltos marcados"]]

    with st.container(border=True):
        st.dataframe(
            tabela.style.apply(pintar_qualidade, axis=None).format(
                thousands=".", subset=tabela.columns[1:]
            ),
            hide_index=True,
            width="stretch",
            height=420,
        )
    nota(
        "O fundo colorido marca o que foge do normal, para não ser preciso ler a tabela "
        "inteira. <strong>Vermelho</strong> em 2013 a 2018: alguma linha foi descartada, "
        "quase sempre uma medição que veio em branco. <strong>Laranja</strong> em 2013, "
        "2014 e 2015: faltaram mais horas do que as quatro que o horário de verão apagava "
        "todo ano, e são os três dias inteiros em que ninguém mediu nada. Quatro horas "
        "faltantes por ano até 2019 é o esperado, não um problema."
    )

st.divider()
st.caption(
    "Dados da Curva de Carga Horária do Operador Nacional do Sistema Elétrico (ONS), "
    "publicados em dados.ons.org.br sob licença CC-BY. Este painel não é um produto "
    "oficial do ONS."
)
