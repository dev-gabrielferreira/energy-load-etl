# energy-load-etl — contrato de trabalho com o Claude

Este arquivo orienta como o Claude Code deve trabalhar neste repositório. Leia antes de qualquer tarefa.

## Contexto

Projeto P1 da trilha de portfólio de Engenharia de Dados do Gabriel (transição de Engenharia de Controle e Automação para dados, pós em andamento na PUC Minas). Pipeline batch da carga de energia do sistema elétrico brasileiro: 27 CSVs anuais da Curva de Carga Horária do ONS (2000-2026) + API REST de Carga Verificada como fonte incremental, validação central, Parquet particionado por ano/subsistema, dashboard Streamlit em produção na VPS do Gabriel.

O plano completo de execução está em `docs/PLANO.md`. Siga a ordem das etapas de lá. Não pule etapas nem antecipe trabalho de semanas futuras.

## O objetivo real deste projeto

Este é um projeto de PORTFÓLIO e de APRENDIZADO. O Gabriel precisa defender cada decisão em entrevista de emprego. Código que funciona mas que ele não entende é fracasso, não sucesso. Isso muda como você deve trabalhar:

1. **Explique antes de implementar.** Antes de cada bloco de código, explique em poucas frases o que vai fazer e por quê. Depois de implementar, aponte as duas ou três linhas que merecem atenção e o motivo.
2. **Passos pequenos.** Um módulo ou uma função por vez, nunca "o pipeline inteiro de uma vez". Espere o Gabriel rodar e confirmar antes de seguir.
3. **Pergunte quando houver escolha real.** Se existirem dois caminhos defensáveis (ex.: como tratar um caso de borda), apresente os dois com prós e contras e deixe o Gabriel decidir.
4. **Checkpoints.** Ao fechar cada etapa do plano, faça as perguntas de checkpoint listadas em `docs/PLANO.md` e espere as respostas dele em texto antes de avançar. Se uma resposta estiver errada ou vaga, explique de novo por outro ângulo em vez de seguir adiante.
5. **Exercícios de reescrita.** Uma vez por semana o plano manda o Gabriel reescrever um trecho do zero. Quando chegar nesse ponto, apague? Não: crie um arquivo paralelo (ex.: `exercicio_v4.py`), deixe ele implementar sem olhar o original, e depois compare os dois com ele.
6. **Commits são dele.** Nunca commite automaticamente. Ao fechar um bloco de trabalho, sugira a mensagem de commit e deixe o Gabriel rodar o git.

## Regras técnicas

- Python gerenciado com uv (`uv add`, `uv run`). Nunca pip install direto.
- pandas para processamento (Polars é decisão rejeitada, ver docs/decisions.md).
- Timestamps são hora local America/Sao_Paulo. O Brasil teve horário de verão até 2019: dias de 23 e 25 horas existem nos dados e são tratados, nunca "limpados".
- Dados brutos em `data/raw/` são imutáveis. O pipeline nunca edita arquivo bruto.
- Toda validação nova precisa de teste em `tests/` com fixture sintética pequena.
- Falha da API de Carga Verificada nunca pode derrubar o fluxo histórico.
- Segredos e caminhos locais só via `.env` (com `.env.example` atualizado).

## Estilo de comunicação e documentação

- Conversa em português brasileiro, tom direto e sem jargão desnecessário.
- README e documentação: sem travessão (—), escrever como pessoa, concreto e específico, sem palavras infladas. O README principal é em inglês com versão em português linkada.
- Docstrings curtas explicando o porquê, não o óbvio.

## O que NÃO fazer

- Não gerar arquivos grandes de uma vez "para adiantar".
- Não adicionar dependência sem justificar e perguntar.
- Não otimizar performance sem medir antes.
- Não usar orquestrador (Airflow etc.) neste projeto; isso é escopo do P3.
- Não commitar `data/` (está no .gitignore por design).
