"""Ponto de entrada do pipeline: baixa, valida, escreve o Parquet e publica o relatorio.

Processa ano a ano e escreve cada ano antes de passar para o proximo. O historico
aprovado nunca fica inteiro em memoria: o que sobrevive ao loop sao os resumos, as
rejeicoes, os buracos e as linhas marcadas, que juntos nao chegam a mil linhas.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from . import aggregate, api_client, config, extract, load, transform, validate

logger = logging.getLogger(__name__)

# Ordem importa: fuso antes de faixa fisica, senao o 0E-8 do Sul na hora inexistente
# seria rejeitado por "carga zero", que e' o diagnostico errado para o problema certo.
ETAPAS_LINHA = (
    validate.v2_subsistema,
    validate.instante_inexistente,
    validate.v5_valor_ausente,
    validate.v3_unicidade,
    validate.v5_faixa_fisica,
)


@dataclass
class ResumoAno:
    ano: int
    lidas: int = 0
    aprovadas: int = 0
    rejeitadas: int = 0
    buracos: int = 0
    marcadas: int = 0
    bloqueio: str | None = None


def processar_ano(ano: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, ResumoAno]:
    """Roda o funil inteiro num ano. Devolve aprovadas, rejeitadas, buracos e o resumo."""
    resumo = ResumoAno(ano)
    vazio_buracos = pd.DataFrame(columns=list(validate.COLUNAS_BURACO))

    cru = extract.ler_ano(ano)
    resumo.lidas = len(cru)

    erro = validate.v1_schema(cru)
    if erro:
        resumo.bloqueio = erro
        logger.error("%s: V1 bloqueou o ano inteiro (%s)", ano, erro)
        return transform.vazio_processado(), validate.rejeicoes_vazias(), vazio_buracos, resumo

    df = extract.localizar_fuso(extract.converter_tipos(cru))

    rejeitados = []
    for etapa in ETAPAS_LINHA:
        df, r = etapa(df)
        if len(r):
            rejeitados.append(r)

    buracos = validate.v4_continuidade(df)
    df = validate.v6_salto(df)

    rejeicoes = (
        pd.concat(rejeitados, ignore_index=True) if rejeitados else validate.rejeicoes_vazias()
    )
    resumo.aprovadas = len(df)
    resumo.rejeitadas = len(rejeicoes)
    resumo.buracos = len(buracos)
    resumo.marcadas = int(df["salto_suspeito"].sum())

    processado = transform.selecionar_colunas_finais(transform.adicionar_calendario(df))
    return processado, rejeicoes, buracos, resumo


@dataclass
class ResumoApi:
    """Como a busca incremental terminou. Vai inteiro para o relatorio de qualidade."""

    inicio: date
    fim: date
    lidas: int = 0
    aprovadas: int = 0
    rejeitadas: int = 0
    buracos: int = 0
    reparos_json: int = 0
    janelas: int = 0
    janelas_com_problema: int = 0
    # Preenchidos depois, pela reconciliacao. Ficam aqui e nao numa segunda dataclass
    # porque o relatorio conta uma historia so': o que veio da API e o que ela disse
    # sobre o arquivo.
    horas_reconciliadas: int = 0
    atipicas: int = 0
    so_no_arquivo: int = 0
    so_na_api: int = 0
    divergencia_media_pct: dict = field(default_factory=dict)


def processar_api(
    inicio: date, fim: date, subsistemas: list[str] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[api_client.ResultadoApi], ResumoApi]:
    """Roda o funil da API. Mesmas validacoes de linha do historico, sem uma alteracao.

    A tupla ETAPAS_LINHA e' a mesma que o processar_ano usa. E' o que "as duas fontes
    passam pelo mesmo funil" quer dizer na pratica: o api_client entrega o dado ja' com
    os nomes de coluna do arquivo anual, e os validadores nao sabem de onde ele veio.

    Duas coisas mudam, e as duas por causa do grao:
      - a V4 pede a grade de meia em meia hora, nao de hora em hora
      - a V6 fica de fora. Os limiares dela foram medidos em saltos de uma hora, e
        aplica-los a saltos de meia hora acusaria degrau onde nao ha', por erro de
        calibragem nosso e nao por problema no dado
    """
    resumo = ResumoApi(inicio, fim)
    df, resultados = api_client.buscar_janela(inicio, fim, subsistemas)

    resumo.janelas = len(resultados)
    resumo.janelas_com_problema = sum(1 for r in resultados if r.status != "ok")
    resumo.reparos_json = sum(r.reparos for r in resultados)
    resumo.lidas = len(df)

    rejeitados = []
    for etapa in ETAPAS_LINHA:
        df, r = etapa(df)
        if len(r):
            rejeitados.append(r)

    buracos = validate.v4_continuidade(df, freq="30min")

    rejeicoes = (
        pd.concat(rejeitados, ignore_index=True) if rejeitados else validate.rejeicoes_vazias()
    )
    resumo.aprovadas = len(df)
    resumo.rejeitadas = len(rejeicoes)
    resumo.buracos = len(buracos)

    return df, rejeicoes, buracos, resultados, resumo


def _reconciliar(horario_api: pd.DataFrame) -> pd.DataFrame:
    """Roda a V7 contra o Parquet ja' escrito, nao contra o CSV bruto.

    Le a camada processada de proposito: o que a API tem que reconciliar e' o dado que
    passou pela validacao e foi publicado, nao o texto que o ONS mandou. E' a mesma
    regra que o dashboard segue.

    Parquet ausente nao e' erro: na primeira subida em producao o pipeline historico
    ainda nao rodou, e a busca na API continua valendo por si.
    """
    if horario_api.empty:
        return pd.DataFrame(columns=list(validate.COLUNAS_RECONCILIACAO))

    anos = sorted(horario_api["din_instante_local"].dt.year.unique())
    try:
        arquivo = load.ler_horario(anos=[int(a) for a in anos])
    except (FileNotFoundError, OSError) as erro:
        logger.warning("V7 nao rodou: camada horaria indisponivel (%s)", erro)
        return pd.DataFrame(columns=list(validate.COLUNAS_RECONCILIACAO))

    return validate.v7_reconciliacao(arquivo, horario_api)


def executar_incremental(dias: int | None = None) -> ResumoApi:
    """Busca os ultimos dias na API, valida, reconcilia com o arquivo e publica.

    Nao toca no historico. Nem para ler o CSV bruto, nem para reprocessar ano nenhum: a
    unica coisa que ele le' do fluxo historico e' o Parquet ja' publicado, para a V7 ter
    com o que comparar. E' por isso que falha da API nao derruba o fluxo historico, e a
    garantia e' estrutural: `executar` nao chama a API em lugar nenhum, entao nao existe
    excecao de API para escapar de la'.
    """
    config.criar_pastas()
    dias = dias or config.API_DIAS_PADRAO
    fim = date.today()
    inicio = fim - timedelta(days=dias - 1)

    df, rejeicoes, buracos, resultados, resumo = processar_api(inicio, fim)

    if len(df):
        load.escrever_verificada(df)
    else:
        # A tabela antiga fica onde esta'. Apagar deixaria o painel sem a aba de ultimos
        # dias por causa de uma indisponibilidade passageira da fonte, e dado de ontem
        # rotulado com a data de ontem e' melhor que tela vazia.
        logger.warning("api: nada veio, a tabela verificada anterior continua no ar")

    if len(rejeicoes):
        rejeicoes.to_csv(config.REJECTED_DIR / "rejeitados_api.csv", index=False)
    if len(buracos):
        buracos.to_csv(config.REJECTED_DIR / "buracos_api.csv", index=False)

    horario_api = api_client.para_horario(df)
    reconciliacao = _reconciliar(horario_api)
    if len(reconciliacao):
        load.escrever_agregado(reconciliacao, load.RECONCILIACAO)

        contagem = reconciliacao["motivo"].value_counts()
        resumo.horas_reconciliadas = len(reconciliacao)
        resumo.atipicas = int(contagem.get(validate.MOTIVO_ATIPICA, 0))
        resumo.so_no_arquivo = int(contagem.get(validate.MOTIVO_SO_ARQUIVO, 0))
        resumo.so_na_api = int(contagem.get(validate.MOTIVO_SO_API, 0))
        resumo.divergencia_media_pct = (
            reconciliacao.groupby("id_subsistema")["divergencia_pct"].mean().round(2).to_dict()
        )

    load.escrever_agregado(pd.DataFrame([_quadro_api(resumo)]), load.QUALIDADE_API)
    _escrever_relatorio_api(resumo, resultados, rejeicoes)
    return resumo


def _quadro_api(resumo: ResumoApi) -> dict:
    """O resumo como uma linha de tabela, para o dashboard ler do Parquet como sempre."""
    linha = asdict(resumo)
    linha["inicio"] = str(resumo.inicio)
    linha["fim"] = str(resumo.fim)
    # Um dict por subsistema nao cabe numa celula de forma util. Vira uma coluna por
    # subsistema, que e' o formato que o painel consegue mostrar direto.
    for subsistema, media in linha.pop("divergencia_media_pct").items():
        linha[f"divergencia_{subsistema}_pct"] = media
    linha["atualizado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return linha


def _escrever_relatorio_api(
    resumo: ResumoApi, resultados: list[api_client.ResultadoApi], rejeicoes: pd.DataFrame
) -> None:
    """Relatorio proprio, em arquivo proprio. O do historico nao e' tocado.

    Os dois modos rodam em cadencias diferentes em producao, e um sobrescrever o
    relatorio do outro faria o painel mostrar sempre o da ultima execucao, seja la' qual
    tenha sido.
    """
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    partes = [
        "# Relatorio da carga incremental (API de Carga Verificada)",
        "",
        f"Gerado em {agora}. Janela pedida: {resumo.inicio} a {resumo.fim}.",
        "",
    ]

    problemas = [r for r in resultados if r.status != "ok"]
    if problemas:
        partes += ["## Aviso: a busca nao voltou inteira", ""]
        partes += [f"- {r.subsistema} {r.inicio}..{r.fim}: {r.status}, {r.detalhe}" for r in problemas]
        partes += ["", "Os numeros abaixo valem so' para o que chegou.", ""]

    partes += [
        "## Busca",
        "",
        f"- Janelas pedidas: {resumo.janelas} ({resumo.janelas_com_problema} com problema)",
        f"- Registros semi-horarios recebidos: {resumo.lidas}",
        f"- Reparos de JSON malformado: {resumo.reparos_json}",
        "",
        "## Funil",
        "",
        f"- Aprovadas: {resumo.aprovadas}",
        f"- Rejeitadas: {resumo.rejeitadas}",
        f"- Meias-horas que existiram e nao chegaram (V4): {resumo.buracos}",
        "",
    ]

    if len(rejeicoes):
        contagem = rejeicoes.groupby(["regra", "motivo"]).size().sort_values(ascending=False)
        partes += [
            _tabela(
                [f"| {regra} | {motivo} | {n} |" for (regra, motivo), n in contagem.items()],
                "| Regra | Motivo | Linhas |",
                "|---|---|---|",
            ),
            "",
            "Rejeicao esperada em toda execucao: a API pre-cria as 48 meias-horas do dia e",
            "preenche com zero as que ainda nao aconteceram. E' a mesma coisa que o arquivo",
            "anual faz com `0E-8` na hora que o horario de verao apagava, em outro formato.",
            "A V5 barra pela faixa fisica, porque carga zero nao existe num sistema",
            "interligado em operacao. Quem somasse o dia inteiro sem essa regra dividiria",
            "por 48 medicoes tendo medido menos, todo dia, sem sintoma nenhum.",
            "",
        ]

    if not resumo.horas_reconciliadas:
        partes += ["## Reconciliacao (V7)", "", "Nao rodou: sem sobreposicao com o arquivo.", ""]
        _gravar(partes)
        return

    taxa = resumo.atipicas / resumo.horas_reconciliadas * 100
    partes += [
        "## Reconciliacao (V7)",
        "",
        f"- Horas comparadas: {resumo.horas_reconciliadas}",
        f"- Divergencia atipica: {resumo.atipicas} ({taxa:.2f}%)",
        f"- So no arquivo, ausentes na API: {resumo.so_no_arquivo}",
        f"- So na API, ausentes no arquivo: {resumo.so_na_api}",
        "",
        "Divergencia media por subsistema, em relacao ao arquivo:",
        "",
    ]
    partes += [f"- {sub}: {media:+.2f}%" for sub, media in sorted(resumo.divergencia_media_pct.items())]
    partes += [
        "",
        "A API fica sistematicamente acima do arquivo porque as duas fontes nao medem a",
        "mesma coisa: a API conta geracao distribuida e o arquivo anual nao. Por isso a",
        "diferenca segue a curva do sol e e' maior onde ha' mais telhado com painel.",
        "",
    ]

    # O aviso que faz a regra saber quando ela envelheceu. A geracao distribuida cresce
    # todo ano, entao a faixa medida hoje fica apertada amanha, e sem este paragrafo o
    # sintoma (marcacoes subindo) seria lido como piora do dado.
    referencia = config.V7_TAXA_CALIBRAGEM_PCT
    if taxa > referencia * 3:
        partes += [
            "> **A faixa da V7 pode estar velha.** Esta execucao marcou "
            f"{taxa:.2f}% das horas, contra {referencia:.2f}% na calibragem de "
            f"{config.V7_CALIBRADA_EM[0]} a {config.V7_CALIBRADA_EM[1]}. Geracao distribuida",
            "> cresce, e com ela a divergencia. Vale remedir a tabela LIMITE_DIVERGENCIA",
            "> antes de concluir que o dado piorou.",
            "",
        ]

    _gravar(partes)


def _gravar(partes: list[str]) -> None:
    destino = config.REJECTED_DIR / "relatorio_api.md"
    destino.write_text("\n".join(partes), encoding="utf-8")
    logger.info("relatorio da API escrito em %s", destino)


def executar(anos: list[int] | None = None, baixar: bool = True) -> list[ResumoAno]:
    """Baixa, processa e escreve o relatorio. Ano que falha nao impede os outros."""
    config.criar_pastas()
    anos = list(anos) if anos is not None else list(config.ANOS)

    downloads = extract.baixar_todos(anos) if baixar else []
    falhas = [d for d in downloads if d.status in ("erro", "ausente")]

    marcadas, rejeicoes, buracos, resumos = [], [], [], []
    diarios, mensais = [], []
    for ano in anos:
        if not extract.caminho_csv(ano).exists():
            logger.warning("%s: sem arquivo local, ano ficou de fora", ano)
            continue

        df, r, b, resumo = processar_ano(ano)
        resumos.append(resumo)
        logger.info(
            "%s: lidas %s | aprovadas %s | rejeitadas %s | buracos %s | marcadas %s",
            ano, resumo.lidas, resumo.aprovadas, resumo.rejeitadas, resumo.buracos, resumo.marcadas,
        )

        if len(r):
            r.to_csv(config.REJECTED_DIR / f"rejeitados_{ano}.csv", index=False)
            rejeicoes.append(r)
        if len(b):
            b.to_csv(config.REJECTED_DIR / f"buracos_{ano}.csv", index=False)
            buracos.append(b)

        if len(df):
            load.escrever_horario(df, ano)
            diarios.append(aggregate.diario(df))
            mensais.append(aggregate.mensal(df))
            # As 35 mil horas do ano vao para o disco e saem da memoria aqui. O que
            # continua sao os agregados, pequenos, e as marcadas para o relatorio.
            marcadas.append(df[df["salto_suspeito"]].copy())

    if diarios:
        load.escrever_agregado(pd.concat(diarios, ignore_index=True), load.DIARIO)
        load.escrever_agregado(pd.concat(mensais, ignore_index=True), load.MENSAL)
    load.escrever_agregado(_quadro_qualidade(resumos), load.QUALIDADE)
    _escrever_relatorio(resumos, rejeicoes, buracos, marcadas, falhas, anos)
    return resumos


def _quadro_qualidade(resumos: list[ResumoAno]) -> pd.DataFrame:
    """Os resumos como tabela, para o dashboard mostrar a saude do dado.

    Vai para processed/ e nao para rejected/ porque o dashboard le so o processado.
    Se ele precisasse abrir o relatorio de rejeitados para se montar, a regra de que
    ele nunca toca no que nao passou pela validacao seria so uma frase no README.
    """
    quadro = pd.DataFrame([asdict(r) for r in resumos])
    quadro["bloqueio"] = quadro["bloqueio"].fillna("")
    return quadro


def _tabela(linhas: list[str], cabecalho: str, separador: str) -> str:
    return "\n".join([cabecalho, separador, *linhas])


def _escrever_relatorio(
    resumos: list[ResumoAno],
    rejeicoes: list[pd.DataFrame],
    buracos: list[pd.DataFrame],
    marcadas: list[pd.DataFrame],
    falhas: list[extract.ResultadoDownload],
    anos_pedidos: list[int],
) -> None:
    """Escreve o relatorio em Markdown. Quantas linhas cairam e por que e' informacao."""
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    partes = [
        "# Relatorio de qualidade",
        "",
        f"Gerado em {agora}. Fonte: Curva de Carga Horaria do ONS, licenca CC-BY.",
        "",
    ]

    # O aviso vem antes de qualquer numero: relatorio de dado incompleto que nao avisa
    # que esta incompleto e' pior que relatorio nenhum.
    processados = {r.ano for r in resumos}
    ausentes = [a for a in anos_pedidos if a not in processados]
    if falhas or ausentes:
        partes += ["## Aviso: este relatorio esta incompleto", ""]
        for f in falhas:
            partes.append(f"- {f.ano}: download {f.status}, {f.detalhe}")
        for a in ausentes:
            partes.append(f"- {a}: nao entrou no processamento, sem arquivo local")
        partes += [
            "",
            "Os anos acima ficaram de fora. Os numeros abaixo valem so para os anos processados.",
            "",
        ]

    bloqueados = [r for r in resumos if r.bloqueio]
    if bloqueados:
        partes += ["## Anos bloqueados pela V1", ""]
        for r in bloqueados:
            partes.append(f"- {r.ano}: {r.bloqueio}")
        partes.append("")

    lidas = sum(r.lidas for r in resumos)
    aprovadas = sum(r.aprovadas for r in resumos)
    total_rejeitadas = sum(r.rejeitadas for r in resumos)
    total_buracos = sum(r.buracos for r in resumos)
    total_marcadas = sum(r.marcadas for r in resumos)

    partes += [
        "## Resumo",
        "",
        f"- Anos processados: {len(resumos)}",
        f"- Linhas lidas: {lidas:,}".replace(",", "."),
        f"- Aprovadas: {aprovadas:,}".replace(",", "."),
        f"- Rejeitadas: {total_rejeitadas} ({total_rejeitadas / lidas * 100:.4f}%)" if lidas else "",
        f"- Horas que existiram e nao chegaram (V4): {total_buracos}",
        f"- Marcadas como salto suspeito (V6): {total_marcadas}",
        "",
        "## Ano a ano",
        "",
    ]
    partes.append(
        _tabela(
            [
                f"| {r.ano} | {r.lidas} | {r.aprovadas} | {r.rejeitadas} | {r.buracos} | {r.marcadas} |"
                for r in resumos
            ],
            "| Ano | Lidas | Aprovadas | Rejeitadas | Buracos | Marcadas |",
            "|---|---|---|---|---|---|",
        )
    )
    partes.append("")

    if rejeicoes:
        todas = pd.concat(rejeicoes, ignore_index=True)
        contagem = todas.groupby(["regra", "motivo"]).size().sort_values(ascending=False)
        partes += ["## Por que as linhas cairam", ""]
        partes.append(
            _tabela(
                [f"| {regra} | {motivo} | {n} |" for (regra, motivo), n in contagem.items()],
                "| Regra | Motivo | Linhas |",
                "|---|---|---|",
            )
        )
        partes += ["", "Detalhe linha a linha em `rejeitados_<ano>.csv`, com arquivo e linha de origem.", ""]

    if buracos:
        todos = pd.concat(buracos, ignore_index=True)
        por_dia = todos.groupby(todos["din_instante_local"].dt.date).size().sort_values(ascending=False)
        partes += [
            "## Horas faltantes (V4)",
            "",
            "Dias com mais de quatro horas ausentes sao falha de coleta. Os dias com exatamente",
            "quatro sao a hora que o horario de verao apagava: uma por subsistema, na volta ao",
            "horario padrao, quando 23:00 acontecia duas vezes e o formato do ONS so guarda uma.",
            "",
        ]
        partes.append(
            _tabela(
                [f"| {dia} | {n} |" for dia, n in por_dia.head(12).items()],
                "| Dia | Horas ausentes |",
                "|---|---|",
            )
        )
        partes.append("")

    if marcadas:
        todas = pd.concat(marcadas, ignore_index=True)
        maiores = todas.reindex(todas["salto_mwmed"].abs().sort_values(ascending=False).index).head(10)
        partes += [
            "## Maiores saltos marcados (V6)",
            "",
            "Marcado quer dizer que merece olhar humano, nao que o dado esta errado.",
            "",
        ]
        partes.append(
            _tabela(
                [
                    f"| {r.id_subsistema} | {r.din_instante_local:%Y-%m-%d %H:%M} | "
                    f"{r.val_cargaenergiahomwmed:,.0f} | {r.salto_mwmed:+,.0f} | {r.salto_pct:.1f}% |".replace(",", ".")
                    for r in maiores.itertuples()
                ],
                "| Subsistema | Instante | Carga (MWmed) | Salto | Relativo |",
                "|---|---|---|---|---|",
            )
        )
        partes.append("")

    destino = config.REJECTED_DIR / "relatorio.md"
    destino.write_text("\n".join(p for p in partes if p is not None), encoding="utf-8")
    logger.info("relatorio escrito em %s", destino)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline da curva de carga do ONS")
    parser.add_argument("--anos", type=int, nargs="+", help="anos especificos (padrao: todos)")
    parser.add_argument("--sem-download", action="store_true", help="usa so o que ja esta em data/raw")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="busca os ultimos dias na API de Carga Verificada, sem reprocessar o historico",
    )
    parser.add_argument(
        "--dias",
        type=int,
        help=f"quantos dias para tras no modo incremental (padrao: {config.API_DIAS_PADRAO})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Um modo ou o outro, nunca os dois na mesma invocacao. Sao cadencias diferentes em
    # producao (a API muda de hora em hora, o arquivo anual duas vezes por dia), e
    # separar aqui e' o que garante que uma falha da API nao tem por onde alcancar o
    # processamento do historico.
    if args.incremental:
        executar_incremental(dias=args.dias)
    else:
        executar(anos=args.anos, baixar=not args.sem_download)


if __name__ == "__main__":
    main()
