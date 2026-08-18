# Ambiente local do ETL e do painel

Este Compose cria um PostgreSQL local separado do banco vazio que existia no
Compose do `analytics-interno`. O banco fica exposto somente em
`127.0.0.1:55432`.

## Inicialização

```bash
cd produtividade-bi-main
cp deploy/local/.env.example deploy/local/.env
cp deploy/local/runtime.env.example deploy/local/runtime.env
# preencha os dois arquivos sem commitar os valores reais

docker compose \
  --env-file deploy/local/.env \
  -f deploy/local/compose.yaml up -d postgres

docker compose \
  --env-file deploy/local/.env \
  -f deploy/local/compose.yaml \
  --profile tools run --rm migrate
```

O serviço `migrate` usa o usuário proprietário/migrator. O serviço `etl` usa
`produtividade_etl`, sem permissão de DDL, e o dashboard deve usar
`produtividade_reader`.

## Backup antes de migration ou backfill

```bash
docker compose \
  --env-file deploy/local/.env \
  -f deploy/local/compose.yaml \
  --profile tools run --rm backup
```

Os dumps ficam em `deploy/local/backups/`, fora do Git. A rotina usa formato
custom do `pg_dump` e inclui apenas o banco local configurado.

## ETL

```bash
docker compose \
  --env-file deploy/local/.env \
  -f deploy/local/compose.yaml \
  --profile jobs run --rm etl
```

O ETL não aplica migrations automaticamente. Execute o serviço `migrate`
explicitamente antes de uma nova versão do schema.

Para a operação diária no macOS, prefira o runner versionado na raiz do
projeto:

```bash
scripts/run_etl_local.sh --dry-run
scripts/run_etl_local.sh --mode incremental
scripts/run_etl_local.sh --mode reconcile --retries 1
scripts/install_launchd_local.sh
scripts/check_local_config.sh
```

O runner carrega os dois arquivos de ambiente, aguarda o PostgreSQL ficar
saudável, faz backup antes da migration, executa `run-projects --resume` no
incremental e `backfill-projects` + `reconcile-projects` na rotina diária.
Falhas retornam código diferente de zero, ficam no log da execução e são
registradas em `.runtime/logs/last-run.status`.

`check_local_config.sh` valida os arquivos locais e os placeholders sem
imprimir credenciais. O modo opcional `--probe-jira` consulta
`/rest/api/2/myself` e exibe apenas o status HTTP.

## Conexão do BFF

O backend do `analytics-interno` deve usar:

```text
jdbc:postgresql://host.docker.internal:55432/produtividade_local
user: produtividade_reader
```

As credenciais ficam no ambiente do Compose do backend, nunca no frontend ou
no repositório.
