#!/bin/sh
# Roda o pipeline agora e depois a cada INTERVALO_HORAS.
#
# Um loop de shell em vez de cron dentro do container: cron precisaria de um init, de
# configuracao de log e de um segundo processo, e isto aqui cabe em dez linhas. O ONS
# publica revisao as 12h e as 19h, entao duas passadas por dia bastam.
#
# Falha de uma execucao nao derruba o servico: o container continua de pe' e tenta de
# novo no proximo ciclo, com os dados da ultima execucao boa ainda no volume.
set -u

INTERVALO_HORAS="${INTERVALO_HORAS:-12}"

while true; do
    echo "[agendador] execucao iniciada em $(date -Iseconds)"
    if python -m energy_load_etl.pipeline; then
        echo "[agendador] execucao concluida em $(date -Iseconds)"
    else
        echo "[agendador] execucao falhou, os dados anteriores continuam no ar"
    fi
    echo "[agendador] proxima em ${INTERVALO_HORAS}h"
    sleep "$((INTERVALO_HORAS * 3600))"
done
