# Deploy na VPS

O painel roda em dois containers da mesma imagem, atrás do Caddy que já existe na VPS.
O `pipeline` baixa e processa; o `dashboard` lê o Parquet e serve a página. Eles se
falam só pelo volume, então reiniciar um não derruba o outro.

```
internet → Caddy (HTTPS) → dashboard:8501 ─┐
                                            ├── volume "dados" (Parquet)
              pipeline (a cada 12h) ────────┘
```

## Antes de começar

Confirme qual proxy está de pé, porque o resto depende disso:

```bash
docker ps --format '{{.Names}}\t{{.Image}}' | grep -iE 'caddy|traefik|nginx'
```

E qual rede ele usa, que é a rede que o compose vai anexar:

```bash
docker inspect <nome-do-container-do-caddy> -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}'
```

Se o nome não for `proxy`, guarde o que apareceu: entra no `.env` como `REDE_PROXY`.

## 1. Apontar o DNS

No painel do seu provedor de domínio, um registro A para o subdomínio, apontando para o
IP da VPS:

```
energia   A   <ip-da-vps>
```

Confira antes de seguir, porque o Caddy só emite o certificado depois que o DNS resolve:

```bash
dig +short energia.seudominio.com
```

## 2. Subir o código

```bash
ssh usuario@vps
git clone <url-do-repo> ~/apps/energy-load-etl
cd ~/apps/energy-load-etl
```

Crie o `.env` (ele não vai para o git):

```bash
cat > .env <<'EOF'
PORTFOLIO_URL=https://seudominio.com
PORTFOLIO_NOME=Portfólio
REDE_PROXY=proxy
EOF
```

`PORTFOLIO_URL` é para onde o link do topo do painel leva. Vazio esconde o link.

## 3. Subir os containers

```bash
docker compose up -d --build
```

O pipeline começa a processar assim que sobe e leva alguns minutos na primeira vez,
porque baixa 39 MB de CSV e processa 933 mil linhas. Enquanto isso o dashboard já
responde, mostrando um aviso de que os dados estão sendo processados, em vez de um erro.

Acompanhe:

```bash
docker compose logs -f pipeline
```

Você deve ver as 27 linhas de "particoes escritas" e depois `diario`, `mensal` e
`qualidade`. No fim, `[agendador] proxima em 12h`.

## 4. Publicar no Caddy

No `Caddyfile` da VPS, um bloco novo:

```caddyfile
energia.seudominio.com {
    reverse_proxy energia-dashboard:8501
}
```

É só isso mesmo. O Caddy resolve HTTPS pelo Let's Encrypt sozinho e já encaminha
WebSocket sem configuração, que é justamente onde deploy de Streamlit costuma travar
com nginx (sem os cabeçalhos `Upgrade` e `Connection`, a página carrega e nunca sai do
"Please wait...").

Recarregue sem derrubar nada:

```bash
docker exec -w /etc/caddy <container-do-caddy> caddy reload
```

Se o seu Caddy roda fora do Docker, troque `energia-dashboard:8501` por
`localhost:8501` e publique a porta no compose (`ports: ["127.0.0.1:8501:8501"]`),
mantendo o `127.0.0.1` para a porta não ficar exposta na internet.

## 5. Conferir

```bash
curl -sI https://energia.seudominio.com | head -1     # espera HTTP/2 200
docker compose ps                                     # os dois "Up", dashboard "healthy"
```

Abra o link no navegador, troque entre tema claro e escuro, e confira se o link do topo
volta para o portfólio.

## Operação

| O quê | Comando |
|---|---|
| Ver logs do painel | `docker compose logs -f dashboard` |
| Forçar reprocessamento agora | `docker compose restart pipeline` |
| Atualizar o código | `git pull && docker compose up -d --build` |
| Espaço ocupado pelos dados | `docker system df -v \| grep dados` |

O pipeline reprocessa tudo a cada 12 horas, e isso é o desenho, não desperdício: o ONS
revisa dados retroativamente, e o `extract` só re-baixa o ano cuja ETag mudou. Uma
execução com tudo em cache leva poucos segundos.

Para mudar a frequência, `INTERVALO_HORAS` no `docker-compose.yml`.

## Quando algo der errado

**A página carrega mas fica girando.** É WebSocket bloqueado. Com Caddy não deveria
acontecer; se acontecer, confirme que o proxy está falando com a porta 8501 e não com
outra.

**"Os dados ainda estão sendo processados" não sai.** Veja
`docker compose logs pipeline`. Se aparecer erro de fuso horário, o `tzdata` não entrou
na imagem: rebuild com `--no-cache`.

**Certificado não emite.** O DNS ainda não propagou ou a porta 80 está fechada. O Caddy
precisa da 80 para o desafio do Let's Encrypt, mesmo servindo só em 443.

**O dashboard mostra dado velho.** O cache do Streamlit vale 30 minutos. Depois disso
ele relê o Parquet sozinho.
