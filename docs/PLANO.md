# Plano de execução — energy-load-etl

Projeto P1 da trilha de portfólio de Engenharia de Dados do Gabriel Ferreira. Este arquivo vive em `docs/PLANO.md` e é o guia de desenvolvimento: o Claude Code deve segui-lo na ordem, junto com o contrato de trabalho do `CLAUDE.md` na raiz. Escrito em ago/2026.

## 1. O que vamos construir

Um pipeline batch com duas fontes e um destino. A fonte histórica são os 27 arquivos anuais da Curva de Carga Horária do ONS (um por ano, de 2000 a 2026, com a carga em MWmed de cada subsistema a cada hora, ~910 mil linhas no total). A fonte incremental é a API REST de Carga Verificada, que serve os dias recentes em granularidade semi-horária. As duas passam pelo mesmo funil de validação, viram Parquet particionado por ano e subsistema, e alimentam um dashboard Streamlit publicado na VPS do Gabriel.

Fluxo: `arquivos anuais ONS (27 CSVs, download com cache)` + `API Carga Verificada (GET por janela de datas)` → `extract` → `validate (contrato + regras V1-V7)` → o que passa vira `Parquet particionado (ano/subsistema)` → `dashboard Streamlit na VPS`. O que falha nas validações não some: cai em `data/rejected/` com motivo, e vira relatório de qualidade publicado.

O ponto central do desenho: nada chega ao Parquet nem ao dashboard sem passar pela validação, e o que falha não é descartado em silêncio.

A inclusão da API já no P1 foi escolha do Gabriel, e muda o projeto para melhor em um aspecto: ele deixa de ser "um script que baixa arquivo" e vira um pipeline com carga histórica cheia e atualização incremental, que é a dupla que existe em qualquer empresa.

## 2. Como vamos trabalhar

Formato escolhido pelo Gabriel: o Claude implementa explicando cada decisão em detalhe, pergunta quando houver escolha real a fazer, e o Gabriel acompanha entendendo o porquê de cada linha. Três regras para ele ser dono do projeto, não espectador:

1. Toda etapa termina na máquina dele. O código só conta como "feito" quando ele rodou e viu funcionar. É ele que dá push, do git dele, com o nome dele nos commits.
2. Checkpoint de entendimento antes de avançar. Cada etapa fecha com perguntas do tipo que caem em entrevista (listadas nas etapas abaixo, sem resposta de propósito). Se alguma travar, parar e destrinchar antes de seguir.
3. Um exercício de reescrita por semana. Um trecho central é refeito do zero pelo Gabriel sem olhar o original, e depois os dois são comparados.

## 3. Decisões já tomadas, e por quê

Cada uma vira linha em `docs/decisions.md`. Em entrevista, "por que X e não Y" é pergunta certa.

| Decisão | Escolha | Por quê (e o que foi rejeitado) |
|---|---|---|
| Processamento | pandas | Gabriel já domina, e 910 mil linhas cabem com folga na memória. Polars seria mais rápido, mas velocidade não é o gargalo, e trocar de ferramenta tiraria foco do desenho do pipeline. Polars entra no P3. |
| Gerenciador de ambiente | uv | Lockfile reprodutível, rápido, e `uv sync` deixa qualquer pessoa rodando o projeto. Rejeitados: pip + requirements.txt (sem lock confiável) e poetry (mais lento, sem vantagem aqui). |
| Formato de saída | Parquet | Colunar, tipado e particionável, padrão de camada processada. Particionado por ano e subsistema para o dashboard ler só o que precisa. CSV na saída jogaria fora a tipagem que a validação garantiu. |
| Layout dos dados | raw → processed | Duas camadas no filesystem: arquivo como veio do ONS (imutável) e Parquet limpo. A essência do medalhão sem fingir que filesystem é data lake. Bronze/silver/gold de verdade fica para o P2. |
| Fuso horário | America/Sao_Paulo | Timestamps do ONS são hora local, e o Brasil teve horário de verão até 2019, criando horas duplicadas e inexistentes nos dados antigos. Tratar isso explicitamente é um dos melhores assuntos do projeto. |
| Dashboard | Streamlit | Foco é o pipeline, não o front. Streamlit entrega dashboard decente em um arquivo Python. |
| Produção | VPS do Gabriel, via Docker | Ele já opera VPS com Docker e proxy reverso. Publicar em subdomínio próprio (ex.: energia.gabrielfdev.com) conta melhor em entrevista que deploy de um clique. Fallback: Streamlit Community Cloud. |
| Testes | pytest | Testes das validações e transformações com fixtures sintéticas pequenas, incluindo os casos de horário de verão. Sem meta de cobertura, com meta de caso que importa. |
| API no P1 | fase da semana 3 | Escolha do Gabriel, com salvaguarda: entra depois do pipeline histórico pronto. Se o prazo apertar, vira v1.1 publicada uma semana depois, e o projeto sai no ar do mesmo jeito. |

## 4. O contrato de dados

Verificado no portal de dados abertos do ONS e no dicionário oficial. É a base das validações: o pipeline confia nisso e grita quando a realidade divergir.

### Fonte 1 · Curva de Carga Horária (histórico)

| Coluna | Tipo | O que é |
|---|---|---|
| id_subsistema | texto (3) | Código do subsistema: N, NE, S, SE |
| nom_subsistema | texto (60) | Nome por extenso (Norte, Nordeste, Sul, Sudeste/Centro-Oeste) |
| din_instante | datetime | Instante da medição, hora cheia, hora local |
| val_cargaenergiahomwmed | float | Carga média na hora, em MWmed |

- Um arquivo por ano, 2000 a 2026, em CSV (separador `;`, UTF-8, decimal com ponto), XLSX e Parquet. Vamos ingerir o CSV de propósito: é o formato que mais aparece no mundo real e o que mais ensina.
- URL direta por ano no S3 público do ONS, padrão `https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/CURVA_CARGA_{ANO}.csv`.
- Atualização diária às 12h e às 19h. Detalhe importante: o ONS revisa dados retroativamente ("processo de consistência recorrente"). Anos recentes podem mudar depois de baixados, então o extract compara e re-baixa quando o arquivo remoto diverge do local.
- Licença CC-BY: uso livre com atribuição ao ONS, creditado no README e no rodapé do dashboard.

### Fonte 2 · API de Carga Verificada (incremental)

- Endpoint `https://apicarga.ons.org.br/prd/cargaverificada`, sem autenticação, parâmetros `dat_inicio`, `dat_fim` (YYYY-MM-DD) e `cod_areacarga`.
- Granularidade semi-horária por área de carga, respostas em JSON. Sem SLA publicado nem limite de requisições documentado, então o cliente terá timeout, retry com backoff exponencial e janela de datas curta por chamada. Falha da API não pode derrubar o fluxo histórico.
- Primeira tarefa da semana 3 é explorar a API de verdade (quais áreas existem, o que volta no JSON, como semi-horário casa com horário) e registrar as descobertas no README. A documentação dela é rala, e isso também é realista.

### A pegadinha central

> Corrigido na semana 1, depois de abrir os arquivos. O texto original dizia que existem dias de 23 e de 25 horas. Metade estava errada, e a versão abaixo é a verificada. Registro completo em `docs/decisions.md`.

O Brasil teve horário de verão até 2019, e o efeito nos arquivos do ONS é assimétrico:

- **Na volta (fevereiro), dias de 25 horas não existem.** As 23:00 aconteciam duas vezes, com cargas diferentes, mas o formato usa o timestamp local como chave e não tem onde guardar as duas. Uma medição real foi descartada na origem. São 4 horas perdidas por ano, uma por subsistema, em todos os anos de 2000 a 2019, e zero de 2020 em diante.
- **Na entrada (outubro), dias de 23 horas existem, mas só até 2013.** Depois disso o ONS passou a gravar a linha da hora inexistente com o campo vazio, e o dia volta a ter 24 linhas. Em 04/11/2018, três subsistemas vieram em branco e o Sul veio com `0E-8`.

Consequência: **nenhuma contagem funciona.** Não existe "24 por dia" nem "8.760 por ano" que valha para todos os anos, porque existe linha que não é hora e hora que não tem linha. A V4 compara conjuntos: pede a grade de instantes reais ao `zoneinfo` e subtrai o que chegou, sem nenhuma data de horário de verão escrita no código. Esse caso tem teste próprio e parágrafo próprio no README.

## 5. As validações

Na ordem em que rodam. O que falha não é descartado em silêncio: cai no relatório de rejeitados com motivo, arquivo de origem e linha.

| # | Regra | O que pega | Efeito |
|---|---|---|---|
| V1 | Schema: 4 colunas com os tipos do contrato | Mudança de layout em ano antigo, coluna renomeada, arquivo corrompido | bloqueia |
| V2 | id_subsistema ∈ {N, NE, S, SE} | Código novo ou sujeira indicando mudança estrutural na fonte | bloqueia |
| V3 | Unicidade de (subsistema, instante localizado) | Duplicata | bloqueia |
| V4 | Continuidade do calendário por subsistema, em hora local | Buraco de horas, comparando com a grade real do fuso | reporta buraco |
| V5 | Valor ausente, e faixa física: 0 < carga < 120.000 MWmed | Medição em branco, zero espúrio, negativo, valor absurdo. Teto bem acima do recorde do sistema, decisão documentada | bloqueia |
| V6 | Salto plausível entre horas consecutivas, relativo com piso absoluto por subsistema | Degrau atípico. Na prática acha apagão nacional e jogo da Copa, não falha de medição | marca como suspeito |
| V7 | Reconciliação API × histórico (semana 3) | Divergência entre semi-horário agregado da API e horário consolidado do arquivo | marca e reporta |

A distinção entre regra dura (V1-V5) e regra de alerta (V6-V7) é decisão de engenharia e vai explicada no README.

## 6. Estrutura do repositório

```
energy-load-etl/
├── README.md               ← diagrama no topo, EN com versão PT
├── pyproject.toml          ← deps e config, gerenciado pelo uv
├── uv.lock
├── .env.example
├── Dockerfile              ← imagem do dashboard para a VPS
├── CLAUDE.md               ← contrato de trabalho com o Claude Code
├── docs/
│   ├── PLANO.md            ← este arquivo
│   ├── architecture.excalidraw
│   └── decisions.md        ← tabela de decisões, viva
├── data/                   ← gitignored
│   ├── raw/                ← CSVs como vieram do ONS
│   ├── processed/          ← Parquet particionado
│   └── rejected/           ← relatórios de qualidade
├── src/energy_load_etl/
│   ├── config.py           ← anos, URLs, caminhos, limiares
│   ├── extract.py          ← download com cache e re-download por divergência
│   ├── api_client.py       ← cliente da API com retry/backoff (semana 3)
│   ├── validate.py         ← V1 a V7
│   ├── transform.py        ← tipos, timezone, features de calendário
│   ├── aggregate.py        ← agregações diária e mensal por subsistema
│   └── pipeline.py         ← orquestra tudo, ponto de entrada único
├── dashboard/
│   └── app.py              ← Streamlit, lê só o Parquet
└── tests/
    ├── conftest.py         ← fixtures sintéticas pequenas
    ├── test_validate.py    ← inclui os casos de horário de verão
    ├── test_transform.py
    └── test_aggregate.py
```

Um ponto de entrada só (`uv run python -m energy_load_etl.pipeline`) roda o fluxo inteiro; a flag `--incremental` (semana 3) busca só os dias recentes via API. Cada módulo tem uma responsabilidade e é testável sozinho, o que facilita a migração para DAGs do Airflow no P3.

## 7. As etapas

Quatro etapas em três semanas, ritmo de 15h+/semana. Cada uma fecha com entregável concreto e perguntas de checkpoint. As perguntas ficam sem resposta de propósito: são o teste de que a etapa entrou. O Claude Code deve fazê-las ao Gabriel e esperar resposta em texto antes de avançar.

### Etapa 0 · Ambiente pronto (1 a 2 dias)

Máquina do Gabriel: Windows 11. Caminho: WSL2 com Ubuntu, VS Code conectado ao WSL, git configurado com GitHub via SSH, uv instalado, repositório `energy-load-etl` criado (privado por enquanto) e clonado.

Entregável: ambiente completo + repo clonado com CLAUDE.md, docs/PLANO.md e .gitignore iniciais.

Checkpoint:
1. Por que rodar o projeto dentro do WSL e não no Windows direto?
2. O que o `uv.lock` garante que o `requirements.txt` não garante?

### Semana 1 · Extract e validate do histórico (~15h)

O coração do projeto. Download dos 27 arquivos com cache local e re-download quando o ONS revisar um ano; validações V1 a V6 com relatório de rejeitados. No fim da semana o dado ainda não está bonito, mas já está confiável, e essa ordem é proposital.

Entregável:
- `extract.py` e `validate.py` funcionando de ponta a ponta nos 27 anos
- Relatório de qualidade: quantas linhas passaram, quantas caíram e por quê, ano a ano
- Testes das validações, incluindo as duas transições de horário de verão nos dois formatos em que o ONS as grava
- Exercício de reescrita: refazer a V4 (continuidade de calendário) do zero

Checkpoint:
1. Por que guardar o arquivo bruto intacto em vez de já salvar limpo?
2. O que acontece com o pipeline se o ONS adicionar um subsistema novo amanhã, e por que esse é o comportamento certo?
3. Por que a V4 valida por calendário local e não por "24 linhas por dia"?

### Semana 2 · Transform, Parquet, dashboard e testes (~15h)

Transformação (tipos finais, timezone, features de calendário: dia da semana, feriado, estação), agregações diária e mensal, escrita em Parquet particionado por ano e subsistema, dashboard Streamlit lendo só o Parquet. No fim da semana o projeto funciona inteiro no modo histórico.

Entregável:
- Pipeline completo com um comando, do download ao Parquet
- Dashboard: visão geral do SIN, comparação entre subsistemas, perfil de carga por hora do dia, sazonalidade ao longo dos 26 anos
- Testes de transform e aggregate
- Exercício de reescrita: refazer a agregação mensal com groupby do zero

Checkpoint:
1. Por que particionar por ano e subsistema, e o que mudaria se o dashboard filtrasse por mês?
2. Qual a diferença entre MWmed e MWh, e por que essa coluna se chama "carga média"?
3. Por que o dashboard não pode tocar no CSV bruto nunca?

### Semana 3 · API incremental, produção e lançamento (~15h)

Exploração da API de Carga Verificada, cliente com retry e backoff, reconciliação do semi-horário da API com o horário do arquivo (V7), deploy do dashboard na VPS com Docker, documentação no padrão da trilha e post de lançamento.

Entregável:
- `api_client.py` com a exploração da API documentada no README
- Modo incremental: `--incremental` busca os últimos dias sem reprocessar o histórico
- Dashboard no ar em subdomínio próprio, com Docker, atrás do proxy da VPS
- README completo (diagrama, decisões, como rodar, o que aprendi com uma falha real), doc estendida no Notion, repo público, post de lançamento em carrossel com o repo no primeiro comentário

Checkpoint:
1. Por que falha da API não pode derrubar o fluxo histórico, e como o código garante isso?
2. O que é backoff exponencial e por que bater na API em loop sem ele é grosseria?
3. Se a API e o arquivo divergirem para a mesma hora, quem vence, e por quê?

## 8. Pronto quando

- Do zero: `git clone`, `uv sync`, um comando, e o pipeline processa os 26 anos na máquina de qualquer pessoa
- Dashboard acessível publicamente num subdomínio do Gabriel, com crédito ao ONS no rodapé
- README no padrão da trilha: problema primeiro, diagrama no topo, decisões com porquês, uma falha real documentada
- Relatório de qualidade publicado junto (quantas linhas caíram e por quê é informação, não vergonha)
- Testes verdes, incluindo os casos de horário de verão
- Gabriel responde qualquer pergunta de checkpoint das quatro etapas sem consultar nada
- Doc no Notion + post de lançamento publicado

## 9. Riscos e plano B

| Risco | Chance | Plano |
|---|---|---|
| API instável ou mal documentada demais na exploração | média | API vira v1.1, publicada uma semana depois. O projeto lança no prazo só com o histórico. |
| CSVs de anos antigos com layout diferente do dicionário atual | média | Até desejável: vira caso real de tratamento no extract e assunto pro README. V1 pega na hora. |
| ONS revisar dados retroativamente durante o desenvolvimento | alta | Já previsto: extract re-baixa quando o remoto diverge. Se acontecer, é demonstração ao vivo do desenho. |
| Semana estourar por causa da pós ou do trabalho | alta em alguma semana | A ordem protege o essencial: cada semana fecha algo utilizável. Atrasar uma semana atrasa o lançamento, não quebra o projeto. |
| VPS dar trabalho no deploy | baixa | Streamlit Community Cloud como fallback no mesmo dia; deploy na VPS vira melhoria posterior. |

## 10. Status

- [x] Plano aprovado (22/ago/2026)
- [x] Etapa 0 · ambiente
- [x] Semana 1 · extract + validate (23/ago/2026). 933.880 linhas lidas nos 27 anos, 260 rejeitadas, 368 horas faltantes detectadas, 909 saltos marcados, 29 testes verdes. Achados em `docs/decisions.md`.
- [x] Semana 2 · transform + parquet + dashboard (23/ago/2026). 933.620 linhas em 108 partições Parquet, 38.916 linhas no agregado diário e 1.280 no mensal, dashboard com cinco abas, 56 testes verdes. A soma de horas faltantes do agregado bate exatamente com as 368 horas que a V4 reporta, por dois caminhos de código independentes. Falta o exercício de reescrita da agregação mensal.
- [ ] Semana 3 · API + produção + lançamento
