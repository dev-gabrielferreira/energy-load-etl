"""Validacoes V1 a V7. O que falha nao some: sai etiquetado com regra, motivo e origem.

Toda validacao de linha tem a mesma forma, (df_ok, df_rejeitados), para poderem ser
encadeadas em qualquer ordem sem cada uma precisar saber da anterior. As tres que fogem
disso fogem por natureza: a V1 julga o arquivo inteiro, a V4 reporta ausencia (que nao
tem linha para rejeitar) e a V7 compara duas fontes (que nao cabe em um DataFrame so').
"""

from __future__ import annotations

import logging

import pandas as pd

from . import config, transform

logger = logging.getLogger(__name__)

# Colunas do relatorio de rejeitados. As tres primeiras respondem "onde estava isso
# no arquivo original", que e' o que torna o relatorio investigavel.
COLUNAS_REJEICAO = (
    "ano",
    "arquivo_origem",
    "linha_origem",
    "id_subsistema",
    "din_instante",
    "val_cargaenergiahomwmed",
    "regra",
    "motivo",
)

COLUNAS_RASTREIO = ("ano", "arquivo_origem", "linha_origem")

# A V4 nao rejeita linha: ausencia nao tem linha para rejeitar. Ela reporta buracos,
# que precisam de um schema proprio, sem arquivo nem linha de origem.
COLUNAS_BURACO = ("ano", "id_subsistema", "din_instante_local", "regra", "motivo")

# O motivo diz o grao do que faltou, porque as duas fontes tem grao diferente. Um
# relatorio que juntasse as duas com o mesmo rotulo faria "382 horas faltantes" somar
# hora cheia com meia-hora, e o numero nao significaria nada.
MOTIVO_FALTANTE = {"h": "hora_faltante", "30min": "meia_hora_faltante"}


def rejeicoes_vazias() -> pd.DataFrame:
    """DataFrame vazio com o schema de rejeicao, para concatenar sem caso especial."""
    return pd.DataFrame(columns=list(COLUNAS_REJEICAO))


def _separar(
    df: pd.DataFrame, ruins: pd.Series, regra: str, motivo: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parte o DataFrame em aprovados e rejeitados, etiquetando os rejeitados."""
    if not ruins.any():
        return df, rejeicoes_vazias()

    rejeitados = df[ruins].copy()
    rejeitados["regra"] = regra
    rejeitados["motivo"] = motivo
    return df[~ruins].copy(), rejeitados[list(COLUNAS_REJEICAO)]


def v1_schema(df: pd.DataFrame) -> str | None:
    """Confere as colunas do contrato. Devolve o motivo da falha, ou None se passou.

    Unica validacao de arquivo inteiro: se o layout mudou, nao ha linha boa para
    salvar, e continuar seria adivinhar qual coluna virou qual.
    """
    encontradas = tuple(c for c in df.columns if c not in COLUNAS_RASTREIO)

    if set(encontradas) != set(config.COLUNAS_CONTRATO):
        faltando = set(config.COLUNAS_CONTRATO) - set(encontradas)
        sobrando = set(encontradas) - set(config.COLUNAS_CONTRATO)
        return f"colunas faltando: {sorted(faltando)}, colunas a mais: {sorted(sobrando)}"

    # Ordem diferente nao quebra nada, porque o pandas le por nome. Mas e' sinal de
    # mexida na fonte, e sinal de mexida na fonte a gente quer ver.
    if encontradas != config.COLUNAS_CONTRATO:
        logger.warning("ordem das colunas mudou: %s", encontradas)

    return None


def v2_subsistema(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """id_subsistema tem que estar no conjunto conhecido do SIN."""
    ruins = ~df["id_subsistema"].isin(config.SUBSISTEMAS_VALIDOS)
    return _separar(df, ruins, "V2", "subsistema_desconhecido")


def instante_inexistente(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tira as horas que nunca existiram no relogio brasileiro.

    Roda antes da faixa fisica de proposito: na entrada do horario de verao o Sul vem
    com 0E-8, e rejeitar isso por "carga zero" daria o diagnostico errado. O problema
    nao e' o valor, e' o instante.
    """
    ruins = df["din_instante_local"].isna()
    return _separar(df, ruins, "FUSO", "instante_inexistente")


def v5_valor_ausente(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Medicao vazia e' ausencia de dado, nao dado. Motivo proprio, separado da faixa."""
    ruins = df["val_cargaenergiahomwmed"].isna()
    return _separar(df, ruins, "V5", "valor_ausente")


def v3_unicidade(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Um subsistema nao pode ter duas medicoes para o mesmo instante.

    Compara pelo instante localizado, nao pelo texto: e' o instante que e' unico.
    Mantem a primeira ocorrencia por ser a ordem em que o ONS gravou.
    """
    ruins = df.duplicated(subset=["id_subsistema", "din_instante_local"], keep="first")
    return _separar(df, ruins, "V3", "duplicata")


def v5_faixa_fisica(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carga fora do que e' fisicamente possivel num sistema interligado em operacao."""
    valores = df["val_cargaenergiahomwmed"]
    ruins = (valores <= config.CARGA_MIN_MWMED) | (valores >= config.CARGA_MAX_MWMED)
    return _separar(df, ruins, "V5", "fora_de_faixa")


def v4_continuidade(df: pd.DataFrame, freq: str = "h") -> pd.DataFrame:
    """Instantes que existiram no relogio local e nao chegaram, por subsistema.

    Nao conta linhas: pede a grade de instantes reais ao zoneinfo e subtrai o que veio.
    Contar quebraria, porque existe linha que nao e' hora (a fantasma da entrada do
    horario de verao) e hora que nao tem linha (a repetida, na volta).

    A janela sai do proprio dado, do primeiro ao ultimo instante do ano somando todos
    os subsistemas, e nao do calendario. Assim o ano em andamento nao acusa buraco pelo
    que ainda nao aconteceu, e um subsistema que perdeu um dia aparece porque os outros
    tres esticam a janela.

    O `freq` existe porque a mesma regra vale para as duas fontes: o arquivo anual e'
    horario e a API de Carga Verificada e' semi-horaria. A pergunta e' a mesma, so' muda
    o passo da grade.
    """
    if df.empty:
        return pd.DataFrame(columns=list(COLUNAS_BURACO))

    instantes_do_ano = pd.DatetimeIndex(df["din_instante_local"])
    grade = transform.grade_local(instantes_do_ano.min(), instantes_do_ano.max(), freq=freq)

    buracos = []
    for subsistema, grupo in df.groupby("id_subsistema", observed=True):
        faltantes = grade.difference(pd.DatetimeIndex(grupo["din_instante_local"]))
        if len(faltantes):
            buracos.append(
                pd.DataFrame(
                    {
                        "ano": grupo["ano"].iloc[0],
                        "id_subsistema": subsistema,
                        "din_instante_local": faltantes,
                        "regra": "V4",
                        "motivo": MOTIVO_FALTANTE.get(freq, "instante_faltante"),
                    }
                )
            )

    if not buracos:
        return pd.DataFrame(columns=list(COLUNAS_BURACO))
    return pd.concat(buracos, ignore_index=True)[list(COLUNAS_BURACO)]


def v6_salto(df: pd.DataFrame) -> pd.DataFrame:
    """Marca saltos atipicos entre horas consecutivas. Marca, nao rejeita.

    Unica regra de alerta das seis: o valor esta correto, o que fugiu do padrao foi o
    que aconteceu naquela hora. No historico brasileiro ela acha apagao nacional, e
    marcado nao quer dizer errado, quer dizer que merece olhar humano.

    Exige os dois criterios do config.LIMITE_SALTO ao mesmo tempo.
    """
    if df.empty:
        # Sem linha nao ha salto, mas quem consome depende das colunas existirem. Devolver
        # o DataFrame pelado aqui faria o pipeline quebrar so no ano que a V1 bloqueou.
        vazio = df.copy()
        vazio["salto_mwmed"] = pd.Series(dtype="float64")
        vazio["salto_pct"] = pd.Series(dtype="float64")
        vazio["salto_suspeito"] = pd.Series(dtype="bool")
        return vazio

    pedacos = []
    for subsistema, grupo in df.groupby("id_subsistema", observed=True):
        grupo = grupo.sort_values("din_instante_local").copy()
        anterior = grupo["val_cargaenergiahomwmed"].shift()

        grupo["salto_mwmed"] = grupo["val_cargaenergiahomwmed"] - anterior
        grupo["salto_pct"] = grupo["salto_mwmed"].abs() / anterior * 100

        # Depois de um buraco a diferenca nao e' salto de uma hora, e' a soma de varias
        # horas que ninguem mediu. Comparar isso com o limiar acusaria degrau inventado.
        consecutiva = grupo["din_instante_local"].diff() == pd.Timedelta(hours=1)

        limite = config.LIMITE_SALTO.get(subsistema)
        if limite is None:
            # Subsistema desconhecido nao chega aqui, a V2 barra antes. Se chegar, nao
            # temos limiar medido para ele, e inventar um seria pior que nao marcar.
            grupo["salto_suspeito"] = False
        else:
            grupo["salto_suspeito"] = (
                consecutiva
                & (grupo["salto_mwmed"].abs() >= limite["piso_mwmed"])
                & (grupo["salto_pct"] >= limite["relativo_pct"])
            )
        pedacos.append(grupo)

    return pd.concat(pedacos).sort_index()


# A V7 nao rejeita nem marca linha: ela compara duas fontes e devolve uma tabela propria,
# com uma linha por hora da sobreposicao. Schema separado pelo mesmo motivo da V4.
COLUNAS_RECONCILIACAO = (
    "ano",
    "id_subsistema",
    "din_instante_local",
    "hora",
    "val_arquivo",
    "val_api",
    "divergencia_mwmed",
    "divergencia_pct",
    "completo",
    "regra",
    "motivo",
)

MOTIVO_CONFERE = "confere"
MOTIVO_ATIPICA = "divergencia_atipica"
MOTIVO_SO_ARQUIVO = "so_no_arquivo"
MOTIVO_SO_API = "so_na_api"


def _faixas_divergencia() -> pd.DataFrame:
    """A tabela do config como DataFrame, para o limiar entrar por merge e nao por laco."""
    return pd.DataFrame(
        [
            (subsistema, hora, minimo, maximo)
            for subsistema, por_hora in config.LIMITE_DIVERGENCIA.items()
            for hora, (minimo, maximo) in enumerate(por_hora)
        ],
        columns=["id_subsistema", "hora", "divergencia_min", "divergencia_max"],
    )


def v7_reconciliacao(arquivo: pd.DataFrame, api: pd.DataFrame) -> pd.DataFrame:
    """Compara a API com o arquivo anual, hora a hora. Reporta tudo, nao bloqueia nada.

    Nao existe fonte vencedora aqui, e essa e' a conclusao da regra e nao uma omissao.
    As duas medem coisas diferentes: a API inclui geracao distribuida e o arquivo anual
    nao, e por isso a divergencia tem forma de curva solar e tamanho diferente em cada
    regiao. Perguntar "quem esta certo" e' a pergunta errada; a util e' "as duas contam a
    mesma historia sobre esta hora".

    Duas coisas saem daqui, e elas tem naturezas bem diferentes:

      - Cobertura, que e' fato duro e nao precisa de limiar nenhum: hora que existe numa
        fonte e nao existe na outra. E' aqui que aparece a hora que o horario de verao
        apagava do arquivo e a API guardou.
      - Divergencia numerica, que e' sempre calculada e reportada, e marcada como atipica
        so' quando sai da faixa medida para aquele subsistema naquela hora do dia.

    A janela e' a sobreposicao das duas fontes, e nao a uniao. Sem esse recorte, as 26
    horas do arquivo anteriores a' serie da API sairiam todas como "so no arquivo", e o
    relatorio de cobertura afogaria o achado real em 900 mil linhas de ruido.

    Hora incompleta da API (uma meia-hora so', o que acontece na ponta da janela) entra
    na tabela com `completo` falso e nunca e' marcada como atipica: comparar a media de
    meia hora com a media de uma hora inteira acusaria divergencia que e' nossa, nao do
    dado.
    """
    if arquivo.empty or api.empty:
        return pd.DataFrame(columns=list(COLUNAS_RECONCILIACAO))

    inicio = max(arquivo["din_instante_local"].min(), api["din_instante_local"].min())
    fim = min(arquivo["din_instante_local"].max(), api["din_instante_local"].max())
    if inicio > fim:
        logger.warning("V7: as duas fontes nao se sobrepoem, nada a reconciliar")
        return pd.DataFrame(columns=list(COLUNAS_RECONCILIACAO))

    chave = ["id_subsistema", "din_instante_local"]
    do_arquivo = arquivo.loc[
        arquivo["din_instante_local"].between(inicio, fim), [*chave, "val_cargaenergiahomwmed"]
    ].rename(columns={"val_cargaenergiahomwmed": "val_arquivo"})
    da_api = api.loc[
        api["din_instante_local"].between(inicio, fim),
        [*chave, "val_cargaenergiahomwmed", "completo"],
    ].rename(columns={"val_cargaenergiahomwmed": "val_api"})

    junto = do_arquivo.merge(da_api, on=chave, how="outer", indicator=True)
    junto["hora"] = junto["din_instante_local"].dt.hour
    junto["ano"] = junto["din_instante_local"].dt.year
    junto["completo"] = junto["completo"].fillna(False).astype(bool)

    junto["divergencia_mwmed"] = junto["val_api"] - junto["val_arquivo"]
    junto["divergencia_pct"] = junto["divergencia_mwmed"] / junto["val_arquivo"] * 100

    junto = junto.merge(_faixas_divergencia(), on=["id_subsistema", "hora"], how="left")
    atipica = (
        junto["completo"]
        & (
            (junto["divergencia_pct"] < junto["divergencia_min"])
            | (junto["divergencia_pct"] > junto["divergencia_max"])
        )
    ).fillna(False)

    junto["regra"] = "V7"
    junto["motivo"] = MOTIVO_CONFERE
    junto.loc[atipica, "motivo"] = MOTIVO_ATIPICA
    junto.loc[junto["_merge"] == "left_only", "motivo"] = MOTIVO_SO_ARQUIVO
    junto.loc[junto["_merge"] == "right_only", "motivo"] = MOTIVO_SO_API

    return junto[list(COLUNAS_RECONCILIACAO)].sort_values(chave, ignore_index=True)
