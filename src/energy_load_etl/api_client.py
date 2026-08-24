"""Cliente da API de Carga Verificada do ONS, a fonte incremental.

A API entrega carga semi-horaria por area de carga, em JSON, sem autenticacao. A
documentacao dela e' rala, e a exploracao achou tres coisas que mandam no desenho deste
modulo:

1. Ela responde HTTP 200 para tudo. Area inexistente, data invalida, intervalo
   invertido e ano sem dado devolvem todos `[ ]`. Nao ha' como distinguir "nao houve
   medicao" de "voce pediu errado" pela resposta, entao o pedido e' conferido aqui
   antes de sair.
2. O JSON vem malformado em datas antigas, com `"val_cargaglobalsmmgd": ,` no lugar do
   numero. Sao os campos de geracao distribuida, que nao existia em 2016. E' por isso
   que o corpo e' lido como texto e reparado antes de ser parseado, em vez de sair
   direto do `resposta.json()`.
3. Uma resposta nunca traz mais de 4.944 registros, e o que passa disso e' cortado do
   FIM da janela, calado. O fatiamento e a conferencia de cobertura moram no
   `buscar_janela`; aqui a janela ja' chega no tamanho certo.

Nenhuma funcao deste modulo levanta excecao por falha da fonte. Todas devolvem o que
conseguiram mais um `ResultadoApi` dizendo como foi, porque falha da API nao pode
derrubar o fluxo historico.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import requests

from . import config

logger = logging.getLogger(__name__)

# O que sai deste modulo, no vocabulario do arquivo anual e nao no da API.
#
# As sete primeiras sao exatamente o que as validacoes de linha do pipeline esperam
# encontrar, e e' por isso que elas rodam sobre o dado da API sem uma unica alteracao.
# As tres ultimas sao da API e nao tem equivalente no arquivo: seguem junto porque sao
# de graca e respondem perguntas que a V7 vai fazer.
COLUNAS_VERIFICADA = (
    "id_subsistema",
    "din_instante_local",
    "val_cargaenergiahomwmed",
    "ano",
    "din_instante",
    "arquivo_origem",
    "linha_origem",
    "hora_ambigua",
    "val_cargaglobal",
    "val_consistencia",
    "din_atualizacao",
)

# Campo sem valor nenhum, como `"val_cargammgd": ,` ou `"val_cargammgd": }`.
#
# As aspas no lookbehind sao o que torna isto seguro: elas prendem o casamento a' aspa
# que fecha o NOME do campo, que e' a unica posicao onde dois-pontos seguidos de virgula
# significam "valor faltando". Sem elas, um `: ,` dentro de uma string de valor tambem
# casaria, e o reparo corromperia dado bom para consertar dado ruim.
CAMPO_VAZIO = re.compile(r'(?<="):\s*(?=[,}\]])')

# Erros que valem uma segunda tentativa: a rede oscilou ou o servidor tropecou. 4xx fica
# de fora de proposito, porque pedido malformado nao melhora com insistencia.
ERROS_TEMPORARIOS = (requests.Timeout, requests.ConnectionError)


@dataclass(frozen=True)
class ResultadoApi:
    """Como uma janela terminou. Espelha o ResultadoDownload do extract, e pelo mesmo
    motivo: quem chama recebe o dado e o diagnostico juntos, sem precisar de try/except.
    """

    subsistema: str
    inicio: date
    fim: date
    status: str
    detalhe: str = ""
    registros: int = 0
    reparos: int = 0


def _resumir_erro(erro: Exception, limite: int = 140) -> str:
    """O erro em uma linha que cabe num relatorio.

    O requests aninha a excecao original dentro da dele, e a mensagem inteira passa de
    400 caracteres com a URL repetida duas vezes. Quatro janelas com erro deixariam o
    relatorio ilegivel, e relatorio que ninguem le' nao diagnostica nada. O tipo e o
    comeco da mensagem sao o que responde "o que aconteceu"; o resto e' ruido.
    """
    mensagem = f"{type(erro).__name__}: {erro}".replace("\n", " ")
    return mensagem if len(mensagem) <= limite else mensagem[: limite - 3] + "..."


def _reparar_json(texto: str) -> tuple[str, int]:
    """Troca campo sem valor por null. Devolve o texto e quantos reparos foram feitos.

    A contagem sobe para o relatorio de qualidade em vez de morrer num log. Reparo
    silencioso e' como um pipeline comeca a mentir: o dado sai certo e ninguem sabe que
    ele passou por uma correcao.
    """
    return CAMPO_VAZIO.subn(": null", texto)


def _pedir(parametros: dict) -> requests.Response:
    """Uma chamada, com backoff exponencial. Levanta a ultima excecao se nao conseguir.

    A espera dobra a cada tentativa (1s, 2s, 4s) e leva um jitter por cima. O jitter
    parece detalhe e nao e': sem ele, todo cliente que caiu junto volta junto, e a
    segunda onda derruba o servidor que estava se levantando.

    A API nao publica SLA nem limite de requisicoes. Na duvida, o educado e' recuar.
    """
    ultimo_erro: Exception | None = None

    for tentativa in range(config.API_TENTATIVAS):
        if tentativa:
            espera = config.API_ESPERA_BASE_SEGUNDOS * 2 ** (tentativa - 1)
            espera += random.uniform(0, config.API_ESPERA_BASE_SEGUNDOS / 2)
            logger.warning("api: tentativa %s em %.1fs (%s)", tentativa + 1, espera, ultimo_erro)
            time.sleep(espera)

        try:
            resposta = requests.get(
                config.URL_CARGA_VERIFICADA,
                params=parametros,
                timeout=config.API_TIMEOUT_SEGUNDOS,
            )
        except ERROS_TEMPORARIOS as erro:
            ultimo_erro = erro
            continue

        # 5xx e' problema do lado de la' e costuma passar. 4xx e' problema do pedido, e
        # repetir o mesmo pedido errado nao conserta nada.
        if resposta.status_code >= 500:
            ultimo_erro = requests.HTTPError(f"HTTP {resposta.status_code}", response=resposta)
            continue

        resposta.raise_for_status()
        return resposta

    raise ultimo_erro  # type: ignore[misc]


def buscar_area(subsistema: str, inicio: date, fim: date) -> tuple[list[dict], ResultadoApi]:
    """Busca uma janela de um subsistema. Nunca levanta excecao.

    O subsistema entra no vocabulario do arquivo (N, NE, S, SE) e e' traduzido para o
    da API aqui dentro. Sao vocabularios diferentes: o SE atende por SECO, e pedir "SE"
    devolve lista vazia sem reclamar de nada.

    A janela precisa caber num pedido so'. Quem fatia e' o buscar_janela.
    """
    area = config.AREAS_POR_SUBSISTEMA.get(subsistema)
    if area is None:
        return [], ResultadoApi(
            subsistema, inicio, fim, "recusado", f"subsistema fora do SIN: {subsistema!r}"
        )

    # As tres conferencias abaixo existem porque a resposta de um pedido errado e'
    # `[ ]`, identica a' de um dia sem medicao. Se elas nao acontecessem aqui, o erro
    # viraria uma ausencia silenciosa la' na frente, sem nada que apontasse a causa.
    if fim < inicio:
        return [], ResultadoApi(subsistema, inicio, fim, "recusado", "intervalo invertido")

    if fim < config.API_INICIO_SERIE:
        return [], ResultadoApi(
            subsistema, inicio, fim, "recusado", f"antes de {config.API_INICIO_SERIE}"
        )

    dias = (fim - inicio).days + 1
    if dias > config.API_MAX_DIAS_POR_CHAMADA:
        return [], ResultadoApi(
            subsistema, inicio, fim, "recusado", f"janela de {dias} dias, fatie antes"
        )

    parametros = {
        "dat_inicio": inicio.isoformat(),
        "dat_fim": fim.isoformat(),
        "cod_areacarga": area,
    }

    try:
        resposta = _pedir(parametros)
    except requests.RequestException as erro:
        return [], ResultadoApi(subsistema, inicio, fim, "erro", _resumir_erro(erro))

    texto, reparos = _reparar_json(resposta.text)
    try:
        registros = json.loads(texto)
    except json.JSONDecodeError as erro:
        # Chega aqui quando o corpo veio quebrado de um jeito que o reparo nao cobre.
        # Melhor reportar do que inventar um segundo remendo em cima do primeiro.
        return [], ResultadoApi(
            subsistema, inicio, fim, "erro", f"JSON invalido apos {reparos} reparos: {erro}"
        )

    if not registros:
        # Nao e' erro nem sucesso: e' anomalia. Depois das conferencias acima, o unico
        # significado que sobra e' "a fonte nao tem esses dias", e isso merece aparecer
        # no relatorio em vez de virar um DataFrame vazio que ninguem repara.
        return [], ResultadoApi(subsistema, inicio, fim, "vazio", "a fonte nao devolveu nada")

    return registros, ResultadoApi(
        subsistema, inicio, fim, "ok", registros=len(registros), reparos=reparos
    )


def vazio_verificada() -> pd.DataFrame:
    """DataFrame vazio no schema da API, com os tipos certos.

    Existe para quem consome nao precisar de caso especial quando a janela nao trouxe
    nada. Sem os tipos, um `.dt.year` sobre a tabela vazia quebraria so' no dia em que a
    API estivesse fora do ar, que e' o pior dia possivel para descobrir isso.
    """
    # Microssegundo, e nao nanossegundo, porque e' o que o pd.to_datetime devolve. Com
    # `ns` aqui, concatenar esta tabela com dado de verdade rebaixaria a precisao do dado
    # de verdade, e o Parquet sairia com um schema no dia em que a janela veio vazia e
    # outro no dia em que veio cheia. Schema que oscila so' aparece na leitura.
    df = pd.DataFrame(columns=list(COLUNAS_VERIFICADA))
    df["din_instante_local"] = pd.Series(dtype=f"datetime64[us, {config.FUSO}]")
    df["din_instante"] = pd.Series(dtype="datetime64[us, UTC]")
    df["din_atualizacao"] = pd.Series(dtype="datetime64[us, UTC]")
    df["val_cargaenergiahomwmed"] = pd.Series(dtype="float64")
    df["val_cargaglobal"] = pd.Series(dtype="float64")
    df["val_consistencia"] = pd.Series(dtype="float64")
    df["ano"] = pd.Series(dtype="int64")
    df["linha_origem"] = pd.Series(dtype="int64")
    df["hora_ambigua"] = pd.Series(dtype="bool")
    return df


def _fatiar(inicio: date, fim: date) -> list[tuple[date, date]]:
    """Quebra a janela em pedacos que cabem num pedido so'.

    Nao e' economia de banda: e' a unica forma de nunca esbarrar no teto de 4.944
    registros que a API corta em silencio. Melhor tres pedidos previsiveis do que um
    pedido que volta HTTP 200 com menos dado do que foi pedido.
    """
    passo = timedelta(days=config.API_MAX_DIAS_POR_CHAMADA)
    pedacos = []
    atual = inicio
    while atual <= fim:
        pedacos.append((atual, min(atual + passo - timedelta(days=1), fim)))
        atual += passo
    return pedacos


def _dias_pedidos(inicio: date, fim: date) -> set[str]:
    return {(inicio + timedelta(days=n)).isoformat() for n in range((fim - inicio).days + 1)}


def _conferir_cobertura(registros: list[dict], inicio: date, fim: date) -> list[str]:
    """Quais dias pedidos nao voltaram na resposta.

    E' a defesa contra o unico defeito da API que nao da' nenhum sinal. Pedindo mais de
    103 dias ela devolve HTTP 200, sem cabecalho nem aviso, com o FIM da janela cortado
    fora, ou seja, some exatamente com os dias recentes que o modo incremental quer.

    Conferir aqui e' barato e transforma um dado que desapareceria em silencio numa
    linha de relatorio. O teto foi medido, nao documentado, entao pode mudar amanha sem
    ninguem avisar, e esta funcao continua valendo se mudar.
    """
    return sorted(_dias_pedidos(inicio, fim) - {r["dat_referencia"] for r in registros})


def _normalizar(registros: list[dict], janela: str) -> pd.DataFrame:
    """Traduz o JSON da API para o vocabulario do arquivo anual.

    E' aqui que a promessa de "uma validacao so' para as duas fontes" se paga: depois
    desta funcao, o dado da API tem os mesmos nomes de coluna do dado do CSV, e as
    validacoes de linha do pipeline rodam sobre ele sem saber de onde ele veio.
    """
    bruto = pd.DataFrame(registros)

    df = pd.DataFrame(index=bruto.index)
    df["id_subsistema"] = bruto["cod_areacarga"].map(config.SUBSISTEMAS_POR_AREA)

    # O carimbo da API e' UTC, e converter e' so' trocar o rotulo do mesmo instante.
    # Repare no que NAO precisa acontecer aqui: nada de `ambiguous` nem de `nonexistent`.
    # Chaveado em UTC, a hora repetida da volta do horario de verao chega como dois
    # instantes distintos e a hora inexistente simplesmente nunca aparece. O problema
    # que domina o resto deste projeto nao existe nesta fonte.
    df["din_instante"] = pd.to_datetime(bruto["din_referenciautc"], utc=True, format="ISO8601")
    df["din_instante_local"] = df["din_instante"].dt.tz_convert(config.FUSO)
    df["ano"] = df["din_instante_local"].dt.year

    # A consistida, que e' a global depois da correcao registrada em val_consistencia.
    df["val_cargaenergiahomwmed"] = pd.to_numeric(bruto["val_cargaglobalcons"], errors="coerce")

    # Mesmo papel de arquivo_origem e linha_origem no CSV: responder "onde estava isso
    # na fonte" para o relatorio de rejeitados continuar investigavel. Aqui a origem e'
    # a janela pedida e a posicao no array que voltou.
    df["arquivo_origem"] = janela
    df["linha_origem"] = bruto.index + 1

    # Duas leituras com o mesmo horario de parede no mesmo subsistema: a hora que
    # aconteceu duas vezes na volta do horario de verao. No arquivo anual isso e'
    # impossivel de representar, e uma das duas medicoes foi descartada na origem.
    df["hora_ambigua"] = df["din_instante_local"].dt.tz_localize(None).duplicated(keep=False)

    df["val_cargaglobal"] = pd.to_numeric(bruto["val_cargaglobal"], errors="coerce")
    df["val_consistencia"] = pd.to_numeric(bruto["val_consistencia"], errors="coerce")
    df["din_atualizacao"] = pd.to_datetime(bruto["din_atualizacao"], utc=True, format="ISO8601")

    return df[list(COLUNAS_VERIFICADA)]


def buscar_janela(
    inicio: date, fim: date, subsistemas: list[str] | None = None
) -> tuple[pd.DataFrame, list[ResultadoApi]]:
    """Busca uma janela de varios dias para varios subsistemas. Nunca levanta excecao.

    Fatia a janela, percorre os subsistemas e devolve tudo junto mais um resultado por
    pedaco. Falha de um pedaco nao interrompe os outros, do mesmo jeito que falha de um
    ano nao interrompe os outros no download do historico.
    """
    subsistemas = subsistemas or sorted(config.AREAS_POR_SUBSISTEMA)

    pedacos, resultados = [], []
    for subsistema in subsistemas:
        for ini, fi in _fatiar(inicio, fim):
            registros, resultado = buscar_area(subsistema, ini, fi)

            if registros:
                faltantes = _conferir_cobertura(registros, ini, fi)
                if faltantes:
                    # Status proprio: veio dado, mas nao veio o que foi pedido. Chamar
                    # isso de "ok" seria a resposta incompleta passando por completa.
                    resultado = ResultadoApi(
                        subsistema, ini, fi, "incompleto",
                        f"{len(faltantes)} dias sem retorno, do {faltantes[0]} em diante",
                        registros=len(registros), reparos=resultado.reparos,
                    )
                pedacos.append(_normalizar(registros, f"api {ini}..{fi}"))

            logger.info(
                "api %s %s..%s: %s %s", subsistema, ini, fi, resultado.status, resultado.detalhe
            )
            resultados.append(resultado)

    df = pd.concat(pedacos, ignore_index=True) if pedacos else vazio_verificada()
    return df, resultados


# Duas meias-horas fazem uma hora. Escrito aqui porque a hora incompleta e' caso real:
# ela aparece na ponta da janela e num dia de falha de coleta.
MEIAS_HORAS_POR_HORA = 2

COLUNAS_HORARIA = (
    "id_subsistema",
    "din_instante_local",
    "val_cargaenergiahomwmed",
    "meias_horas",
    "completo",
)


def para_horario(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega o semi-horario da API para hora cheia, no alinhamento do arquivo anual.

    Duas convencoes precisam bater, e as duas sao faceis de errar.

    A primeira e' o carimbo. A API marca o FIM do intervalo: o registro rotulado 00:30
    e' a media entre 00:00 e 00:30. O arquivo anual marca o inicio. Por isso o instante
    recua meia hora antes de virar hora: sem o recuo, a carga da madrugada entraria na
    hora anterior e a serie inteira sairia deslocada em uma hora, com aparencia de
    normalidade.

    A segunda e' onde arredondar. `din_instante_local.dt.floor("h")` levanta
    AmbiguousTimeError na volta do horario de verao, porque o horario de parede 23:00
    aconteceu duas vezes e o pandas nao tem como escolher. Arredondar em UTC nao tem
    esse problema, e da' o mesmo resultado enquanto o fuso for de hora cheia, o que
    sempre foi o caso do Brasil. Fica o alerta para quem levar este codigo para um fuso
    de meia hora, como o da India: la' a equivalencia deixa de valer.

    Toda hora sai dizendo de quantas meias-horas ela e' feita, pelo mesmo motivo que os
    agregados diario e mensal dizem: media de uma metade parece tao solida quanto media
    de uma hora inteira.
    """
    if df.empty:
        vazio = pd.DataFrame(columns=list(COLUNAS_HORARIA))
        vazio["din_instante_local"] = pd.Series(dtype=f"datetime64[us, {config.FUSO}]")
        vazio["val_cargaenergiahomwmed"] = pd.Series(dtype="float64")
        vazio["meias_horas"] = pd.Series(dtype="int64")
        vazio["completo"] = pd.Series(dtype="bool")
        return vazio

    inicio_utc = (df["din_instante"] - pd.Timedelta(minutes=30)).dt.floor("h")

    base = pd.DataFrame(
        {
            "id_subsistema": df["id_subsistema"],
            "din_instante_local": inicio_utc.dt.tz_convert(config.FUSO),
            "val_cargaenergiahomwmed": df["val_cargaenergiahomwmed"],
        }
    )

    chave = ["id_subsistema", "din_instante_local"]
    horario = (
        base.groupby(chave, observed=True)["val_cargaenergiahomwmed"]
        .agg(val_cargaenergiahomwmed="mean", meias_horas="size")
        .reset_index()
    )
    horario["completo"] = horario["meias_horas"] == MEIAS_HORAS_POR_HORA

    return horario[list(COLUNAS_HORARIA)]
