# Deploy na VPS

O painel roda em dois containers da mesma imagem, atrás do Caddy que já existe na VPS.
O `pipeline` baixa e processa; o `dashboard` lê o Parquet e serve a página. Eles se
falam só pelo volume, então reiniciar um não derruba o outro.

```
internet → Caddy (HTTPS) → dashboard:8501 ─┐
                                            ├── volume "dados" (Parquet)
              pipeline (a cada 12h) ────────┘
```

## O ambiente desta VPS

Levantado em 23/ago/2026, e é para isto que os arquivos estão configurados:

| | |
|---|---|
| Proxy | Caddy 2, container `caddy` |
| Rede | `interna` |
| Caddyfile | `/home/gabriel/infra/caddy/Caddyfile` |
| Endereço do painel | `energia.gabrielfdev.com` |
| Home do portfólio | `gabrielfdev.com` |

## 1. Apontar o DNS

No provedor do domínio, um registro A para o subdomínio, apontando para o IP da VPS:

```
energia   A   <ip-da-vps>
```

Confira antes de seguir, porque o Caddy só emite o certificado depois que o DNS resolve:

```bash
dig +short energia.gabrielfdev.com
```

## 2. Subir o código

```bash
ssh gabriel@vps
git clone <url-do-repo> ~/apps/energy-load-etl
cd ~/apps/energy-load-etl
```

Crie o `.env`, que não vai para o git:

```bash
cat > .env <<'EOF'
PORTFOLIO_URL=https://gabrielfdev.com
PORTFOLIO_NOME=Portfólio
REDE_PROXY=interna
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

Acrescente ao fim de `/home/gabriel/infra/caddy/Caddyfile`:

```caddyfile
energia.gabrielfdev.com {
    reverse_proxy energia-dashboard:8501
}
```

É só isso mesmo. O Caddy resolve o HTTPS pelo Let's Encrypt sozinho e encaminha
WebSocket sem configuração nenhuma, que é justamente onde deploy de Streamlit costuma
travar com nginx: sem os cabeçalhos `Upgrade` e `Connection`, a página carrega e nunca
sai do "Please wait...".

Valide a sintaxe antes de recarregar, porque Caddyfile quebrado derruba todos os sites,
não só este:

```bash
docker exec -w /etc/caddy caddy caddy validate --config /etc/caddy/Caddyfile
docker exec -w /etc/caddy caddy caddy reload --config /etc/caddy/Caddyfile
```

O `reload` troca a configuração sem derrubar conexão, então os outros sites não piscam.

## 5. Conferir

```bash
curl -sI https://energia.gabrielfdev.com | head -1    # espera HTTP/2 200
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
