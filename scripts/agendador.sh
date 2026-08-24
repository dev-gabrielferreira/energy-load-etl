#!/bin/sh
# Dois ritmos, um loop so'.
#
# As duas fontes mudam em cadencias diferentes, entao seria desperdicio (e falta de
# educacao com o ONS) tratar as duas igual:
#   - os arquivos anuais sao republicados as 12h e as 19h, e o extract so' re-baixa o ano
#     cuja ETag mudou, entao duas passadas completas por dia bastam
#   - a API de Carga Verificada publica de meia em meia hora, e e' ela que da' ao painel
#     a dianteira de alguns dias sobre o arquivo
#
# Um loop de shell em vez de cron: cron precisaria de um init, de configuracao de log e
# de um segundo processo, e isto aqui cabe em vinte linhas.
#
# Falha de uma execucao nao derruba o servico: o container continua de pe' e tenta de
# novo no proximo ciclo, com os dados da ultima execucao boa ainda no volume. Vale para
# os dois modos, e eles sao independentes: a API fora do ar nao impede a passada
# completa, e vice-versa.
set -u

INTERVALO_HORAS="${INTERVALO_HORAS:-12}"
INTERVALO_INCREMENTAL_HORAS="${INTERVALO_INCREMENTAL_HORAS:-3}"

# De quantos ciclos incrementais em quantos roda uma passada completa. O `|| echo 1`
# protege contra alguem configurar o incremental mais espacado que o completo, que
# daria divisao por zero e mataria o container no primeiro ciclo.
CICLOS_ATE_COMPLETA=$((INTERVALO_HORAS / INTERVALO_INCREMENTAL_HORAS))
[ "$CICLOS_ATE_COMPLETA" -lt 1 ] && CICLOS_ATE_COMPLETA=1

echo "[agendador] completa a cada ${INTERVALO_HORAS}h, incremental a cada ${INTERVALO_INCREMENTAL_HORAS}h"

ciclo=0
while true; do
    # A completa vem primeiro no ciclo em que as duas caem juntas: ela e' quem escreve a
    # camada horaria que a reconciliacao do incremental le' logo depois.
    if [ $((ciclo % CICLOS_ATE_COMPLETA)) -eq 0 ]; then
        echo "[agendador] passada completa iniciada em $(date -Iseconds)"
        if python -m energy_load_etl.pipeline; then
            echo "[agendador] passada completa concluida"
        else
            echo "[agendador] passada completa falhou, os dados anteriores continuam no ar"
        fi
    fi

    echo "[agendador] passada incremental iniciada em $(date -Iseconds)"
    if python -m energy_load_etl.pipeline --incremental; then
        echo "[agendador] passada incremental concluida"
    else
        echo "[agendador] passada incremental falhou, o historico segue publicado"
    fi

    ciclo=$((ciclo + 1))
    echo "[agendador] proxima em ${INTERVALO_INCREMENTAL_HORAS}h"
    sleep "$((INTERVALO_INCREMENTAL_HORAS * 3600))"
done
