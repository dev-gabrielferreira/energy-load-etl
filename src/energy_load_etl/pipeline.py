"""Ponto de entrada do pipeline: baixa, valida, escreve o Parquet e publica o relatorio.

Processa ano a ano e escreve cada ano antes de passar para o proximo. O historico
aprovado nunca fica inteiro em memoria: o que sobrevive ao loop sao os resumos, as
rejeicoes, os buracos e as linhas marcadas, que juntos nao chegam a mil linhas.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import pandas as pd

from . import config, extract, load, transform, validate

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


def executar(anos: list[int] | None = None, baixar: bool = True) -> list[ResumoAno]:
    """Baixa, processa e escreve o relatorio. Ano que falha nao impede os outros."""
    config.criar_pastas()
    anos = list(anos) if anos is not None else list(config.ANOS)

    downloads = extract.baixar_todos(anos) if baixar else []
    falhas = [d for d in downloads if d.status in ("erro", "ausente")]

    marcadas, rejeicoes, buracos, resumos = [], [], [], []
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
            # As 35 mil horas do ano vao para o disco e saem da memoria aqui. So as
            # marcadas continuam, porque o relatorio lista as maiores no fim.
            marcadas.append(df[df["salto_suspeito"]].copy())

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
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    executar(anos=args.anos, baixar=not args.sem_download)


if __name__ == "__main__":
    main()
