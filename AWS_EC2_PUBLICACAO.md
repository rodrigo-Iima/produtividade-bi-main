# Publicação na AWS EC2 — baseline de teste

## Topologia inicial

```text
Jira + Clockify
       │ APIs externas
       ▼
ETL Python — cron/systemd timer na EC2
       │ localhost:5432
       ▼
PostgreSQL — container local, sem porta pública
       ▲
       │ rede Docker privada
Metabase — container Docker, única porta pública
```

Esta configuração usa a EC2 como ambiente de teste. O banco pode ser migrado
posteriormente para RDS sem mudança no modelo do ETL.

## Pré-requisitos da instância

- Ubuntu atualizado;
- Docker Engine e Docker Compose Plugin;
- Python 3.10 ou superior e `python3-venv`;
- repositório clonado em um diretório estável, por exemplo
  `/opt/produtividade-bi`;
- grupo de segurança permitindo somente `22/tcp` para administração e
  `3000/tcp` para o Metabase, preferencialmente restrito aos IPs autorizados.

Não liberar `5432/tcp` para a internet. O PostgreSQL deve aceitar conexões
somente no host local ou na rede interna do Docker.

## PostgreSQL e Metabase

O arquivo `deploy/ec2/docker-compose.yml` sobe:

- PostgreSQL com volume persistente;
- o banco analítico definido em `POSTGRES_DB`;
- o banco separado `metabasedb` para a aplicação Metabase;
- Metabase com limite de heap configurável e porta `3000`.

Copie `deploy/ec2/.env.aws.example` para `deploy/ec2/.env` e preencha os
valores. Nunca versionar esse arquivo.

```bash
cp deploy/ec2/.env.aws.example deploy/ec2/.env
docker compose --env-file deploy/ec2/.env -f deploy/ec2/docker-compose.yml up -d
docker compose --env-file deploy/ec2/.env -f deploy/ec2/docker-compose.yml ps
docker compose --env-file deploy/ec2/.env -f deploy/ec2/docker-compose.yml logs -f metabase
```

Depois de o Metabase iniciar, acesse `http://IP_DA_EC2:3000` e adicione como
fonte de dados o PostgreSQL analítico. Use o host `postgres`, a porta `5432`,
o banco `POSTGRES_DB` e as credenciais do banco analítico. Não adicione
`metabasedb` como fonte dos dashboards; ele guarda somente os metadados do
Metabase.

## ETL na EC2

O ETL pode ser executado diretamente em um ambiente virtual Python:

```bash
cd /opt/produtividade-bi
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env
# preencher Jira, Clockify e PostgreSQL
./.venv/bin/python -m operationalization healthcheck
./.venv/bin/python -m operationalization run --retries 1 --retry-delay 30
```

Para o PostgreSQL do compose, use `POSTGRES_HOST=127.0.0.1` e mantenha a
publicação da porta vinculada somente ao loopback. O comando termina ao final
da carga, libera o lock e fecha o engine SQLAlchemy.

## Cron inicial

Use o wrapper versionado para centralizar logs e, opcionalmente, enviar sinais
de sucesso e falha ao monitor de cron:

```bash
chmod +x /opt/produtividade-bi/deploy/ec2/run_etl.sh
```

Use `crontab -e` para o usuário que executará o ETL:

```cron
0 7 * * 1-5 /opt/produtividade-bi/deploy/ec2/run_etl.sh
```

Substitua a linha anterior do cron por esta, para não executar duas cargas no
mesmo horário. O wrapper usa o lock local e registra tudo em
`.runtime/etl.log`.

### Alerta de falha

Uma opção simples é criar um check no Healthchecks.io para o cron, configurar o
horário `0 7 * * 1-5`, o fuso `America/Sao_Paulo` e uma margem maior que a
duração normal da carga. Copie a Ping URL para `ETL_HEALTHCHECK_URL` no `.env`
do ETL. A URL é um segredo e não deve ser versionada nem compartilhada.

O wrapper envia `/start`, um ping de sucesso ao terminar com código `0` e
`/fail` quando o ETL termina com erro. O monitor também alerta quando nenhum
ping chega no horário esperado, cobrindo falha do cron, da máquina ou da rede.

Antes do primeiro agendamento, execute manualmente um ciclo controlado e
verifique:

```bash
./.venv/bin/python -m operationalization status
./.venv/bin/python -m operationalization healthcheck
```

## Próxima evolução

Após validar a operação na EC2, migrar o PostgreSQL para RDS, guardar segredos
no AWS Secrets Manager, enviar logs para CloudWatch e substituir o cron por um
job gerenciado. Nenhuma dessas evoluções exige alteração das métricas ou do
modelo dimensional.
