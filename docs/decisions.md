# Decisões

Cada linha aqui é uma pergunta que já apareceu, ou que vai aparecer, em entrevista.
Documento vivo: decisão nova entra aqui no mesmo commit em que entra no código.

## Arquitetura

| Decisão | Escolha | Por quê, e o que foi rejeitado |
|---|---|---|
| Processamento | pandas | 910 mil linhas cabem na memória com folga. Polars seria mais rápido, mas velocidade não é o gargalo, e trocar de ferramenta tiraria o foco do desenho do pipeline. Polars fica para o P3. |
| Ambiente | uv | Lockfile reprodutível e `uv sync` deixa qualquer pessoa rodando. Rejeitados: pip com requirements.txt (sem lock confiável) e poetry (mais lento, sem vantagem aqui). |
| Formato de saída | Parquet | Colunar, tipado, particionável. CSV na saída jogaria fora a tipagem que a validação garantiu. |
| Layout | raw e processed | Duas camadas: arquivo como veio (imutável) e Parquet limpo. Medalhão de verdade fica para o P2. |
| Dashboard | Streamlit | O foco é o pipeline, não o front. |
| Produção | VPS própria, com Docker | Subdomínio próprio conta mais em entrevista que deploy de um clique. Fallback: Streamlit Community Cloud. |
| Testes | pytest | Fixtures sintéticas pequenas, com foco em caso que importa, não em cobertura. |
| API de Carga Verificada | Semana 3 | Entra depois do histórico pronto. Se apertar, vira v1.1 e o projeto lança do mesmo jeito. |

## Semana 1

| Decisão | Escolha | Por quê, e o que foi rejeitado |
|---|---|---|
| Cliente HTTP | requests | O pipeline baixa 27 arquivos em sequência. httpx traria async e HTTP/2, que não usaríamos. |
| Leitura do `.env` | python-dotenv | Sem ele, seria preciso exportar variável na shell antes de cada execução. |
| Versão do Python | 3.12 fixa em `.python-version` | A máquina tem 3.14, mas na Semana 2 entra pyarrow, e versão recém-lançada costuma demorar a ter wheel. Sem wheel, o build compila do zero. |
| Cache do download | ETag e tamanho por HEAD | HEAD não baixa conteúdo. Com 27 arquivos, é a diferença entre 40 MB por execução e quase nada quando tudo está em cache. Rejeitado: comparar por data de modificação local, que se perde ao copiar arquivo. |
| Arquivo revisado pelo ONS | Sobrescreve, guardando o histórico de ETag | Revisão do ONS é correção, então o dado novo é mais confiável. O manifesto registra quando cada ano foi revisado, que é a única prova de que mexeram. Rejeitado: versionar o CSV antigo, que faz `data/raw/` crescer sem uso claro. |
| Escrita do arquivo baixado | Temporário e depois `os.replace` | Download interrompido deixa um `.parte` truncado, nunca um CSV pela metade que a validação leria como íntegro. O temporário fica na mesma pasta porque rename entre sistemas de arquivos não é atômico. |
| Leitura do CSV | Tudo como texto, conversão explícita depois | Deixar o pandas parsear na leitura faria um valor corrompido explodir dentro do `read_csv`, e sobraria um traceback em vez do endereço da linha ruim. |
| Formato da data | `format="%Y-%m-%d %H:%M:%S"` fixo | Sem formato explícito o pandas infere pelas primeiras linhas. Inferência pode acertar por acidente num ano e trocar dia por mês em outro, silenciosamente. |
| `nom_subsistema` | Descartado | Derivável do id e não é estável: o SE aparece como `SUDESTE` até 2025 e `SUDESTE/CENTRO-OESTE` em 2026. Guardar os dois convidaria o dashboard a agrupar pelo campo errado. |
| Fuso na Semana 1 | Localizar já no extract | O caso mais interessante do projeto aparece no dia 1, e a V4 fica mais simples com grade tz-aware. Rejeitado: adiar para o transform da Semana 2. |
| Rótulo do fuso | `America/Sao_Paulo`, não UTC | Timestamp com fuso guarda o mesmo instante nos dois casos; muda só o rótulo. Com o rótulo local, o dashboard mostra "pico das 19h" sem converter, e o Parquet guarda em UTC com o fuso nos metadados de qualquer forma. |
| Hora ambígua (volta do horário de verão) | `ambiguous=True`, a primeira ocorrência | Mantém 22:00 e 23:00 consecutivas em UTC. Com a segunda ocorrência, o salto de 2 horas cairia dentro do pico noturno e a V6 acusaria degrau todo ano, por escolha nossa e não por problema no dado. |
| Hora inexistente (entrada do horário de verão) | `nonexistent="NaT"` e rejeição | O instante não existiu no relógio local, então não há valor a corrigir nem a salvar. |
| Valor vazio | Rejeita, com motivo próprio | Regra dura, separada da faixa física. O Parquet nunca carrega NaN em coluna de medição, e o relatório distingue "não mediram" de "mediram errado". |
| Idioma do código | Português | Alinhado com as colunas da fonte e com o domínio. README continua em inglês. |
| V1, coluna fora de ordem | Avisa, não bloqueia | O pandas lê por nome, então ordem trocada não quebra nada. Mas é sinal de mexida na fonte, e isso a gente quer ver. Coluna faltando ou renomeada continua bloqueando o ano. |
| V4, janela de busca | Primeiro ao último instante observados no ano | Fixar 01/01 a 31/12 faria o arquivo do ano corrente acusar milhares de buracos que são só futuro. Como a janela sai de todos os subsistemas juntos, um subsistema que perdeu um dia aparece porque os outros três esticam a janela. |
| V4, saída | Lista de buracos, não linhas rejeitadas | Ausência não tem linha para rejeitar. Schema próprio, sem arquivo nem linha de origem. |
| V6, critério | Relativo com piso absoluto, os dois ao mesmo tempo | Só absoluto erode conforme o sistema cresce (5.780 MWmed eram 16,5% do pico do SE em 2000 e são 9,9% hoje). Só relativo dispara por nada quando a carga base é pequena (a recuperação pós-apagão do NE marca 409%, saindo de 665 MWmed). |
| V6, calibragem | Percentil 99,9 do relativo e 99 do absoluto, medidos em 933 mil observações | Marca 0,097% das horas, cerca de 34 por ano, que é uma lista que um humano consegue revisar. Cortes mais largos marcavam 210 por ano, e alerta que ninguém revisa vira decoração. |
| V6, nome da marca | `salto_suspeito` | Mantido do plano original. Registrado aqui que "suspeito" quer dizer "merece olhar humano", não "dado errado": no histórico brasileiro a regra acha apagão nacional e jogo da Copa, que são dados corretos sobre eventos atípicos. |
| Ordem das validações | Fuso antes da faixa física | Na entrada do horário de verão o Sul veio com `0E-8` na hora que não existiu. Rejeitar isso por "carga zero é impossível" seria diagnóstico errado: o problema não é o valor, é o instante. Validação na ordem errada produz explicação falsa. |
| Falha de download | Segue com os anos que deram certo | Rede instável não pode derrubar a execução inteira. Os anos que faltaram aparecem em aviso no topo do relatório, antes de qualquer número, porque relatório incompleto que não avisa que está incompleto é pior que relatório nenhum. |
| Memória do pipeline | Não acumula as aprovadas | Na Semana 1 nada consome os 933 mil registros validados, então guardá-los custaria uns 300 MB de RAM sem servir a ninguém. O pipeline guarda só resumos, rejeições, buracos e marcações. |

## Semana 2

| Decisão | Escolha | Por quê, e o que foi rejeitado |
|---|---|---|
| Engine do Parquet | pyarrow | Caminho maduro para Parquet particionado no pandas, e já era o motivo de fixar o Python 3.12. Rejeitado: fastparquet, com suporte pior a datetime com fuso, que é justamente a coluna central deste projeto. |
| Feriados | biblioteca `holidays` | Carnaval, Sexta-Santa e Corpus Christi dependem do cálculo da Páscoa. Reimplementar isso seriam trinta linhas para manter num assunto que não é o do projeto, e erro no cálculo passaria silencioso. |
| Quais feriados marcar | nacionais **e** pontos facultativos | Carnaval e Corpus Christi não são feriado por lei federal, mas a carga cai neles como cai em feriado: no SE, terça de Carnaval de 2018 às 10h marca 36.268 MWmed contra 44.932 na terça seguinte, 19% a menos. O critério é o efeito no que a gente mede, não a definição jurídica. Custo aceito: Dia do Servidor Público entra junto e quase não afeta carga. |
| Estação do ano | limites de data fixos (21/12, 21/03, 21/06, 23/09) | O solstício anda um ou dois dias entre anos e isso não muda carga de energia. O objetivo da coluna é agrupar por clima, não marcar efeméride. |
| Grade de horas | uma função só, em `transform.grade_local` | A V4 e a agregação fazem a mesma pergunta ("quais horas existiram no relógio"). Duas implementações um dia divergiriam, e aí o relatório de buracos e o agregado dariam respostas diferentes sobre o mesmo dia. |
| Escrita do Parquet | pasta explícita por partição, arquivo de nome fixo | Reprocessar um ano sobrescreve o anterior. `to_parquet(partition_cols=...)` gera nomes com UUID, e reprocessar deixaria o arquivo antigo do lado do novo: o dado dobraria em silêncio. Verificado rodando o pipeline duas vezes, com a contagem estável em 933.620. |
| Colunas de partição | saem de dentro do arquivo | `ano` e `id_subsistema` já estão no caminho, no padrão Hive, e voltam na leitura. Repetir o mesmo valor em 35 mil linhas seria pagar duas vezes pela mesma informação. |
| Colunas fora do processado | `din_instante`, `arquivo_origem`, `linha_origem` | O naive é redundante com o localizado, e o rastreio serve ao relatório de rejeitados, não à camada processada. Quem precisar voltar ao CSV bruto acha a linha pelo par (subsistema, instante). |
| Tabela de qualidade | em `processed/`, não em `rejected/` | O dashboard lê só o processado. Se ele precisasse abrir o relatório de rejeitados para se montar, a regra de que ele nunca toca no que não passou pela validação seria só uma frase no README. |
| Memória do pipeline (revisão) | escreve o ano e o descarta | Revoga em parte a decisão da Semana 1, que era "não acumula porque nada consome". Agora existe consumidor: cada ano vai para o disco e sai da memória, e o que sobrevive ao loop são resumos, rejeições, buracos e as 909 linhas marcadas. |
| Período incompleto no agregado | agrega sempre, declarando `horas_presentes`, `horas_esperadas` e `completo` | Mesma linha do resto do projeto: o que tem problema sai etiquetado, não descartado. Descartar o período incompleto tiraria um dia de todo fevereiro entre 2000 e 2019. |
| `horas_esperadas` | da grade do `zoneinfo`, nunca 24 | A armadilha da Semana 1 volta aqui: dividir a soma por 24 inventaria número em 156 dias do histórico. São 80 dias de 25 horas (a volta do horário de verão, 2000 a 2019) e 76 de 23 horas (a entrada, até 2018). |
| Janela do agregado | dias inteiros, diferente da janela da V4 | As duas perguntas são diferentes. A V4 pergunta "faltou medição?", e por isso para no último instante observado, senão o ano em andamento acusaria como buraco o que ainda não aconteceu. O agregado pergunta "esse dia está inteiro?", e sem o dia inteiro o último dia de 2026 sairia como completo por ter sido medido pela metade. |
| Agregado mensal | calculado do horário, não do diário | Média de médias diárias daria o mesmo peso a um dia inteiro e a um dia com seis horas medidas, e o mês sairia torto sem ninguém perceber. |
| `energia_mwh` | soma dos MWmed, cada linha vale uma hora | Só é comparável entre períodos quando `completo` é verdadeiro: hora que faltou não entra na soma. A docstring diz isso, porque somar MWmed sem olhar a completude é o erro mais fácil de cometer com esta coluna. |
| Dia sem medição nenhuma | vira linha com `horas_presentes = 0` e medidas nulas | Sem linha para agrupar, o `groupby` não cria grupo e o dia sumiria do agregado em silêncio. São três no histórico (01/12/2013, 01/02/2014 e 09/04/2015), e sem eles o gráfico ligaria a véspera no dia seguinte como se nada tivesse acontecido. Nulo e não zero: média de coisa nenhuma é ausência, e zero seria apagão nacional. |
| Biblioteca de gráficos | Plotly | Hover, zoom e legenda clicável prontos, num painel que vai ser mostrado em entrevista. Rejeitado: Altair, que já vem com o Streamlit e não custaria dependência nova, mas exigiria mais código para a mesma interatividade. |
| Cor dos subsistemas | dicionário fixo, não lista percorrida | A cor segue a entidade, nunca a posição na lista. Com lista, desmarcar o Norte no filtro repintaria os outros três e o leitor perderia a referência no meio da análise. |
| Paleta | dois conjuntos, um por tema | Não é o mesmo hex clareado: são passos calibrados para cada superfície. Na escala sequencial do heatmap, o conjunto escuro é o invertido, para que "mais tinta" continue significando "mais carga" nos dois temas em vez de a carga alta sumir no fundo. |
| Carga média anual no painel | energia dividida por horas medidas | Primeira versão somava as médias mensais e mostrava 641.747 MWmed, oito vezes o valor real. Média de médias pesa fevereiro igual a janeiro e um mês furado igual a um mês inteiro. É a mesma razão pela qual o agregado mensal sai do horário, agora do lado de quem consome. |
| Feriado no fim de semana | conta como feriado | A precedência muda as três curvas do perfil do dia. O critério é o comportamento da carga, não a contagem de categorias. |
| Identidade das séries | legenda **e** nome no fim da linha | Achar a cor na legenda é um vai e volta que o olho paga a cada leitura. Os rótulos que ficariam colados são afastados na vertical: Sul e Nordeste terminam a 83 MWmed um do outro, menos de um pixel, e empilhados leriam pior que rótulo nenhum. |
| Métricas que não somam | carga máxima e mínima não viram SIN | O pico do Norte e o do Sul acontecem em horas diferentes, então somar os dois não é pico de coisa nenhuma. O toggle fica desabilitado com a explicação do lado, em vez de permitir e depois avisar. |
| Muitos pontos no gráfico | `Scattergl` acima de 4.000 pontos | A visão diária dos 26 anos tem 38.904 pontos, e o SVG do Plotly engasga nessa ordem de grandeza. Troca só a classe do traço; o resto do código é igual. |
| Leitura do painel | só `processed/`, e o horário só numa tela | Quatro das cinco abas leem agregado pronto e abrem instantâneo. A aba de perfil do dia é a única que abre o Parquet horário, e o filtro de ano e subsistema vira poda de pasta no pyarrow: um arquivo de 8.760 linhas em vez dos 108 do dataset. |
| Limite conhecido: dia vazio na borda | fica de fora do agregado | A janela sai do próprio dado. Dia vazio no meio aparece porque a janela passa por cima dele; dia vazio na primeira ou na última posição não, porque nada indica que deveria existir. Vale para a V4 pelo mesmo motivo. Os três dias vazios do ONS estão todos no meio do ano. Fixado em teste para não ser "consertado" por engano. |

## Deploy

| Decisão | Escolha | Por quê, e o que foi rejeitado |
|---|---|---|
| Imagem | uma só, dois comandos | Dashboard e pipeline rodam do mesmo código, mudando só o `command`. Duas imagens seriam duas coisas para manter em sincronia, e a segunda existiria só para repetir a primeira. |
| Fuso no container | `tzdata` instalado via apt | `python:3.12-slim` não traz `/usr/share/zoneinfo`, e sem ele o `zoneinfo` não conhece `America/Sao_Paulo`. O projeto inteiro se apoia nisso para saber quais horas existiram em cada dia, então o pipeline morreria na primeira linha que tenta localizar um instante. É a dependência menos óbvia e mais crítica da imagem. |
| Dados na VPS | pipeline roda lá, a cada 12 horas | O painel se atualiza sozinho e o projeto vira pipeline em produção, não Parquet estático que alguém subiu. Rejeitado: embutir o Parquet na imagem, que obrigaria a rebuildar para atualizar dado. |
| Agendamento | loop de shell no container | Cron dentro de container precisa de init, de configuração de log e de um segundo processo. O loop cabe em dez linhas e falha de uma execução não derruba o serviço: os dados da última execução boa continuam no ar. |
| Reprocessar tudo a cada ciclo | sim | O ONS revisa dados retroativamente, então reprocessar é o desenho e não desperdício. O `extract` só re-baixa o ano cuja ETag mudou, e uma execução com tudo em cache leva segundos. |
| Dono do volume | `/dados` criado na imagem | Volume nomeado nasce com as permissões do diretório que existe na imagem naquele caminho. Sem o `mkdir`, ele nasceria de root e o pipeline, que roda como usuário sem privilégio, não conseguiria escrever. |
| Sistema de arquivos do pipeline | somente-leitura, menos o volume | Tudo que ele grava vai para `/dados`. O resto ser imutável fecha uma porta de graça. |
| Proxy | Caddy, que já estava na VPS | HTTPS automático e WebSocket encaminhado sem configuração. Com nginx seria preciso lembrar dos cabeçalhos `Upgrade` e `Connection`, e sem eles a página do Streamlit carrega e nunca sai do "Please wait...". |
| Porta do dashboard | `expose`, não `ports` | Quem fala com a internet é o Caddy, pela rede interna. Publicar a 8501 no host deixaria o painel acessível por IP, contornando o HTTPS. |
| Cache do painel | 30 minutos de validade | Cache sem prazo faria o dashboard servir para sempre o dado da hora em que o container subiu, sem nunca enxergar o que o agendador gerou. Foi encontrado ao preparar o deploy, não em produção. |
| Healthcheck no pipeline | desligado | A imagem é uma só, e o healthcheck dela pergunta ao Streamlit se está de pé. O pipeline não roda Streamlit, então ficava marcado unhealthy para sempre. Alarme que sempre toca ninguém escuta. Visto no primeiro `docker compose ps` da VPS. |
| Painel sem dados | avisa em vez de estourar | Na primeira subida o dashboard fica de pé antes de o pipeline terminar, e mostrava `FileNotFoundError` para quem abrisse o link. |

## O que o dado real desmentiu

O plano dizia, com base na documentação do ONS e no funcionamento do horário de verão:

> Nos dados antigos existe um dia por ano com 23 horas e outro com 25, com hora
> duplicada de madrugada.

Metade disso é falso, e descobrimos abrindo os arquivos.

**Dias de 25 horas não existem.** Na volta do horário de verão as 23:00 aconteciam
duas vezes, com cargas diferentes, mas o formato do ONS usa o timestamp local como
chave e não tem onde guardar as duas. Uma das medições foi descartada na origem. O
pipeline detecta isso: são exatamente 4 horas faltantes por ano (uma por subsistema)
em todos os anos de 2000 a 2019, e zero de 2020 em diante, quando o país acabou com o
horário de verão. A validação reconstruiu uma mudança de política pública a partir do
formato do arquivo.

**Dias de 23 horas existem, mas não em todos os anos.** Na entrada do horário de verão
o relógio pulava de 00:00 para 01:00. Até 2013 o ONS simplesmente não gravava a linha,
e o dia tem 23. De 2014 a 2018 ele grava a linha com o campo vazio, e o dia tem 24.
Em 04/11/2018, três subsistemas vieram em branco e o Sul veio com `0E-8`.

Consequência de desenho: **nenhuma contagem funciona**. Não existe "24 linhas por dia"
nem "8.760 por ano" que valha para todos os anos, porque existe linha que não é hora e
hora que não tem linha. Por isso a V4 compara conjuntos: pede a grade de instantes
reais ao `zoneinfo` e subtrai o que chegou. Não há nenhuma data de horário de verão
escrita no código.

## Achados de qualidade no histórico

Encontrados pelo próprio pipeline, sem ninguém procurar.

- **Três dias inteiros sem medição**: 01/12/2013, 01/02/2014 e 09/04/2015. Em 2014 e
  2015 o Norte não tem nem linha, enquanto os outros três têm linha com campo vazio.
- **Abril de 2020, subsistema Norte**: salto horário médio de 336 MWmed contra 109 a
  147 em todos os outros meses do mesmo ano, e máximo de 2.076 contra 350 a 717. Três
  vezes a variabilidade normal, sustentada por um mês, com volta ao normal em maio.
  Causa desconhecida. Lockdown explicaria queda de nível, não triplicação da
  variabilidade hora a hora. Fica como pergunta para os relatórios de operação do ONS.
- **Os dez maiores saltos do histórico são quatro apagões e seis jogos de Copa do
  Mundo.** Apagões: 21/01/2002 (SE), 10/11/2009 (SE, o maior blecaute do país),
  28/08/2013 (NE) e 21/03/2018 (N e NE). Jogos: Copa 2006 (quatro partidas, incluindo
  a final), Copa 2010 e Copa 2014. Todos os jogos aparecem às 18:00, no Sudeste, como
  subida entre 7.283 e 9.022 MWmed. Parar para assistir é gradual; voltar ao trabalho
  é abrupto, e é a retomada que dispara a regra.
