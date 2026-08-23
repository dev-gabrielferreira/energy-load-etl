"""Exercicio da Semana 1: reescrever a V4 (continuidade de calendario) do zero.

NAO OLHE src/energy_load_etl/validate.py ANTES DE TERMINAR.

O objetivo nao e' acertar de primeira, e' descobrir sozinho onde a coisa complica.
Se travar, releia o contrato abaixo em vez de espiar o original.

--------------------------------------------------------------------------------
O PROBLEMA

Voce recebe um DataFrame com medicoes horarias de carga, ja validadas e ja com fuso.
Precisa devolver quais horas EXISTIRAM na vida real e NAO chegaram no arquivo.

Colunas que voce tem:
    ano                 int     ex: 2018
    id_subsistema       str     um de N, NE, S, SE
    din_instante_local  datetime com fuso America/Sao_Paulo
    (outras colunas existem, ignore)

Colunas que voce deve devolver, nesta ordem:
    ano, id_subsistema, din_instante_local, regra, motivo

Uma linha por hora faltante, por subsistema. `regra` e' sempre "V4" e `motivo` e'
sempre "hora_faltante". DataFrame vazio (com essas colunas) quando nao houver buraco.

--------------------------------------------------------------------------------
A PARTE DIFICIL

O Brasil teve horario de verao ate 2019, e por isso duas armadilhas convivem no
mesmo historico:

1. Existem linhas que nao correspondem a hora nenhuma. Na entrada do horario de
   verao o relogio pulava de 00:00 para 01:00, entao aquela hora nao existiu para
   ninguem. Alguns anos do ONS trazem essa linha vazia, outros nem trazem.

2. Existem horas que nao tem linha. Na volta do horario de verao as 23:00
   aconteciam duas vezes, com cargas diferentes, e o formato do ONS so guarda uma.

Consequencia: contar nao funciona. Nao existe "24 linhas por dia" nem "8.760 por
ano" que valha para todos os anos. Se voce escrever qualquer contagem fixa, um dos
testes abaixo vai te pegar.

Voce nao precisa de nenhuma tabela de datas de horario de verao. O Python ja sabe
quando cada transicao aconteceu. Descubra como perguntar.

--------------------------------------------------------------------------------
DECISAO DE ESCOPO

De onde ate onde procurar buraco? Se voce usar 01/01 ate 31/12, o arquivo de 2026
(que vai so ate agosto) vai acusar milhares de buracos que sao so futuro. Pense em
qual janela faz sentido e deixe sua escolha explicita num comentario.

--------------------------------------------------------------------------------
COMO RODAR

    uv run pytest exercicios/ -v

Sao 6 testes. Comece fazendo o primeiro passar.
"""

from __future__ import annotations

import pandas as pd

COLUNAS_BURACO = ("ano", "id_subsistema", "din_instante_local", "regra", "motivo")


def v4_continuidade(df: pd.DataFrame) -> pd.DataFrame:
    """Devolve as horas que existiram no relogio local e nao chegaram, por subsistema."""
    raise NotImplementedError("sua vez")
