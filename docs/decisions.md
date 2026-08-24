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

## Semana 3

Decisões da fonte incremental. A exploração da API veio antes de qualquer linha de
código, e mudou o desenho: as duas fontes não medem a mesma coisa.

| Decisão | Escolha | Por quê, e o que foi rejeitado |
|---|---|---|
| Onde o dado da API mora | tabela própria, `processed/verificada/` | A API fica em média 5% acima do arquivo, com forma que varia ao longo do dia. Anexar na mesma tabela enfiaria um degrau estrutural numa série de 26 anos, e qualquer `groupby` que esquecesse de filtrar por fonte leria o degrau como fato. Rejeitado: coluna `fonte` na tabela horária. |
| Grão de armazenamento | semi-horário, como chega | Agregar na entrada jogaria fora informação que a fonte deu de graça. A agregação para hora acontece só na hora de comparar. |
| Coluna de medida | `val_cargaglobalcons` | É a consistida. Medido em 90 dias: `val_cargaglobalcons = val_cargaglobal + val_consistencia`, e só 4 registros em 4.320 tiveram correção. Usar a não consistida seria ignorar a correção que o próprio ONS aplicou. |
| Vocabulário de área | mapa explícito, com o inverso derivado dele | A API chama o SE de `SECO`. Pedir `SE` não dá erro: devolve `[ ]`. Dois dicionários escritos à mão dessincronizariam num refactor, e o sintoma seria dado sumindo em silêncio. |
| JSON malformado | reparado para `null`, com a contagem no relatório | A API devolve `"val_cargaglobalsmmgd": ,` em datas antigas, uns 100 por dia entre 2016 e 2019, sempre nos campos de geração distribuída, que não existia. `json.loads` recusa. Recusar o dia jogaria fora medição boa por causa de uma vírgula. Reparo silencioso é como um pipeline começa a mentir, então a contagem sobe para o relatório. |
| Regex do reparo | exige aspas antes dos dois-pontos | `:\s*(?=,)` solto também casaria dentro de uma string de valor, e um campo com o texto `"cuidado: , aqui"` viraria `"cuidado: null aqui"`. Corromper dado bom para consertar dado ruim seria péssima troca. Tem teste. |
| Corpo lido como texto | `resposta.text`, não `resposta.json()` | O `.json()` estoura no corpo malformado antes de haver chance de repará-lo. |
| Tamanho da janela por chamada | 30 dias | Medido: uma resposta nunca traz mais de 4.944 registros (103 dias). Passando disso ela corta o **fim** da janela, devolve HTTP 200 e não avisa, ou seja, some justamente com os dias recentes que o modo incremental quer. 30 fica bem abaixo do teto. |
| Conferência de cobertura | compara `dat_referencia` recebidos com os dias pedidos | Única defesa contra o corte silencioso. O teto foi medido, não documentado, então pode mudar amanhã sem aviso, e a conferência continua valendo se mudar. Verificado: pedindo 150 dias, ela acusa os 47 que faltaram. |
| Validação de pedido | local, antes de sair da máquina | A API responde HTTP 200 com `[ ]` para área inválida, data inválida, intervalo invertido e ano sem dado. Sem as recusas locais, erro nosso viraria ausência de dado sem nada apontando a causa. |
| Resposta vazia | anomalia, com status próprio | Não é erro nem sucesso. Depois das recusas locais, o único significado que sobra é "a fonte não tem esses dias", e isso merece linha no relatório em vez de virar DataFrame vazio que ninguém nota. |
| Retentativa | backoff exponencial com jitter, só em timeout, erro de conexão e 5xx | 4xx é problema do nosso pedido, e repetir o mesmo pedido errado não conserta nada. Resposta vazia também não se repete: o servidor devolveria a mesma coisa. O jitter existe porque, sem ele, todo cliente que caiu junto volta junto e a segunda onda derruba o servidor que estava se levantando. |
| Detalhe do erro no relatório | truncado em 140 caracteres | O `requests` aninha a exceção original na dele, e a mensagem passa de 400 caracteres com a URL repetida. Quatro janelas com erro deixavam o relatório ilegível, e relatório que ninguém lê não diagnostica nada. |
| Normalização na entrada | nomes de coluna do arquivo anual | Depois do `api_client`, o dado da API tem `id_subsistema`, `din_instante_local` e `val_cargaenergiahomwmed`, e as validações de linha do pipeline rodam sobre ele sem uma alteração. É o que "as duas fontes passam pelo mesmo funil" quer dizer na prática. |
| V6 na API | fica de fora | Os limiares foram medidos em saltos de uma hora. Meia hora tem metade do tempo para a carga variar, então o mesmo piso acusaria degrau onde não há. Seria erro de calibragem nosso, não problema no dado. |
| Grade da V4 | ganhou parâmetro `freq` | A mesma pergunta ("quais instantes existiram no relógio") serve às duas fontes, mudando só o passo. Duas implementações um dia divergiriam, e aí o relatório de buracos de uma fonte contradiria o da outra. |
| Alinhamento semi-horário para horário | recua 30 minutos, depois arredonda | A API carimba o **fim** do intervalo e o arquivo carimba o início. Sem o recuo, a série inteira sairia deslocada em uma hora com aparência de normalidade. |
| Onde arredondar | em UTC, nunca no horário local | `din_instante_local.dt.floor("h")` levanta `AmbiguousTimeError` na volta do horário de verão, porque o horário de parede 23:00 aconteceu duas vezes. Em UTC não há ambiguidade, e o resultado é o mesmo enquanto o fuso for de hora cheia, o que sempre foi o caso do Brasil. Fica o alerta para fuso de meia hora, como o da Índia. |
| Hora incompleta da API | entra declarando `meias_horas` e `completo` | Mesma linha do agregado diário e mensal. Comparar a média de meia hora com a média de uma hora inteira acusaria divergência que é nossa, não do dado, então hora incompleta nunca é marcada como atípica. |
| V7, o que ela decide | nada: reporta divergência e marca cobertura | Não existe fonte vencedora, e isso é conclusão, não omissão. As duas medem coisas diferentes. A pergunta "quem está certo" é a errada; a útil é "as duas contam a mesma história sobre esta hora". |
| V7, janela | sobreposição das duas fontes, não união | Sem o recorte, as 26 horas do arquivo anteriores à série da API sairiam todas como "só no arquivo", e o achado real afogaria em 900 mil linhas de ruído. Preço aceito: buraco exatamente na ponta não aparece na V7, e quem cuida disso é a conferência de cobertura do cliente. Tem teste fixando o comportamento. |
| V7, limiar | faixa medida por subsistema **e** por hora do dia | Medido: com faixa única por subsistema, 100% das marcações caíam entre 7h e 14h, ou seja, a regra estava medindo o sol e não anomalia. Com faixa por hora, as marcações ficam uniformes ao longo do dia. Rejeitados: faixa fixa generosa (marcava 0,12%, tudo ao meio-dia) e resíduo contra o perfil da própria janela (ruidoso, resíduo p99 de 11 pontos percentuais). |
| V7, calibragem | percentis 0,5 e 99,5 sobre um ano inteiro | 35.040 horas de sobreposição, 8.760 por subsistema, agosto de 2025 a agosto de 2026. Um ano e não três meses porque a divergência acompanha o sol, e verão e inverno têm perfis diferentes. Marca 1,10% no próprio dado da calibragem. |
| V7, envelhecimento | a taxa da calibragem fica no `config`, e o relatório compara | Única regra do projeto que envelhece: geração distribuída cresce todo ano e a divergência cresce junto, então faixa medida hoje fica apertada amanhã. Se a taxa de marcação disparar, o relatório diz "a régua ficou velha", não "o dado piorou". Regra calibrada que não sabe dizer quando precisa ser remedida vira alarme que ninguém escuta. |
| Escrita da tabela verificada | apaga a tabela inteira antes de escrever | Ela é uma janela móvel dos últimos dias, não um histórico que cresce. Torna a escrita idempotente e deixa claro que a cobertura dela é a da janela pedida. Acumular a série da API seria leitura mais merge por (subsistema, instante): decisão diferente, com custo diferente, e não está tomada. |
| Tabela vazia com tipos | `vazio_verificada()` fixa os dtypes, com precisão de microssegundo | Sem os tipos, um `.dt.year` sobre a tabela vazia quebraria só no dia em que a API estivesse fora, que é o pior dia para descobrir. A precisão é `us` e não `ns` porque é o que o `pd.to_datetime` devolve: com `ns`, concatenar rebaixaria o dado real e o Parquet sairia com um schema no dia em que a janela veio vazia e outro no dia em que veio cheia. |
| Modo incremental | função e flag separadas, sem `try/except` em volta da API | `executar` não chama a API em lugar nenhum. Um `try/except` garantiria que a exceção não escapa; caminhos separados garantem que ela não existe no fluxo histórico. Verificado apontando a URL para um host inexistente: o incremental falhou em 5,4s sem exceção e os anos de 2024 e 2025 processaram normalmente. |
| Reconciliação lê o Parquet | não o CSV bruto | O que a API reconcilia é o dado que passou pela validação e foi publicado, não o texto que o ONS mandou. Mesma regra que o dashboard segue. Parquet ausente não é erro: na primeira subida o histórico ainda não rodou. |
| API sem retorno | mantém a tabela anterior | Apagar deixaria o painel sem a aba de últimos dias por uma indisponibilidade passageira. Dado de ontem rotulado com a data de ontem é melhor que tela vazia, e quem diz que a busca falhou é o relatório. |
| Relatório do incremental | arquivo próprio, `relatorio_api.md` | Os dois modos rodam em cadências diferentes em produção, e um sobrescrever o relatório do outro faria o painel mostrar sempre o da última execução, seja qual tenha sido. |
| Tabelas da API no dashboard | opcionais | Ausência delas não derruba a página: as duas abas novas explicam que faltam dados e o resto continua inteiro. Um painel que só sobe quando a API respondeu jogaria fora a separação entre os fluxos no último metro. |
| Ritmo em produção | completa a cada 12h, incremental a cada 3h | As fontes mudam em cadências diferentes: os arquivos anuais são republicados às 12h e às 19h, e a API publica de meia em meia hora. Tratar as duas igual seria desperdício e falta de educação com o ONS. |
| Testes da API | sem rede, com recortes reais | Todo corpo de resposta nos testes foi copiado da API antes de virar fixture. Verificado rodando a suíte com `socket.connect` bloqueado. |

## O que a API desmentiu e revelou

Tudo medido em 23/08/2026, contra a API real e contra o Parquet local.

- **Os códigos de área não são os do arquivo.** São `N`, `NE`, `S` e `SECO`. Pedir `SE`
  devolve `[ ]`, sem erro nenhum.
- **A API responde HTTP 200 para tudo.** Área inválida, data inválida, intervalo
  invertido e ano sem dado: todos 200 com lista vazia. Não existe sinalização de erro.
- **Teto silencioso de 4.944 registros, e ela corta o fim.** Pedindo 150 dias vieram os
  103 primeiros, e os 47 dias mais recentes sumiram sem aviso, que é exatamente a parte
  que o modo incremental quer.
- **JSON inválido em datas antigas.** `"val_cargaglobalsmmgd": ,` sem valor, cerca de
  100 por dia entre 2016 e 2019, sempre nos campos de geração distribuída.
- **A série começa em 2016-01-01.** Antes disso a resposta vem vazia.
- **A API pré-cria as 48 meias-horas do dia e preenche com zero as que ainda não
  aconteceram.** Descoberto pela V5, sem ninguém procurar: numa execução às 22h, as
  meias-horas de 22:30 a 24:00 dos quatro subsistemas vieram com `0.0`. É a mesma
  mentira que o arquivo anual conta com `0E-8`, em outro formato. Quem somasse o dia
  corrente sem a faixa física dividiria por 48 medições tendo medido menos, todo dia,
  sem sintoma nenhum.
- **A API guarda a hora que o arquivo perdeu.** Chaveada em UTC, ela não tem o problema
  do formato do ONS. Em 17/02/2018 e 16/02/2019 o dia vem com 50 registros, com as duas
  ocorrências das 23:00 carimbadas `-02:00` e `-03:00`. A V7 recuperou 37.797,471 MWmed
  às 23:00 de 17/02/2018, uma medição real que não existe no arquivo anual. Em 2016 e
  2017 o dia vem com 48: nesses dois anos a hora extra se perdeu na API também.
- **As duas fontes divergem, e a divergência tem estrutura.** Em 35.040 horas de
  sobreposição a API fica acima do arquivo em média 5,0% no SE, 4,3% no NE, 2,7% no S e
  1,4% no N. A diferença tem duas partes somadas: uma constante, que continua lá de
  madrugada com o sol posto, e uma que varia ao longo do dia, com vale de manhã cedo e
  pico à tarde. A segunda acompanha a geração em telhado com painel solar, que não passa
  pela rede: o arquivo anual não a enxerga e a API a estima e soma.
- **O Norte fica negativo boa parte do dia**, ou seja, ali a API mede menos que o
  arquivo. Geração distribuída não explica isso. Fica como pergunta em aberto, do lado
  de abril de 2020, e não como conclusão.

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
