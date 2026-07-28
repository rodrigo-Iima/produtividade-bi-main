# Runtime OCI portátil

Este deployment contém somente os jobs do projeto. Ele não inclui PostgreSQL,
Metabase, volume de dados ou segredos e pode ser usado como referência em AWS,
OVH, Kubernetes ou uma VM com Docker Compose.

## Construir a imagem ETL

```bash
docker build \
  -f Dockerfile.etl \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  -t produtividade-etl:"$(git rev-parse --short HEAD)" \
  .
```

A imagem usa um usuário sem privilégios e expõe dois comandos:

```bash
docker run --rm produtividade-etl:<tag> migrate
docker run --rm produtividade-etl:<tag> run
```

O comando `migrate` aplica também as camadas SQL de views que no baseline da
EC2 eram executadas manualmente. O comando `run` usa
`ETL_AUTO_MIGRATE=false` no deployment portátil e não precisa de permissão DDL.

## Executar com Compose

Copie `runtime.env.example` para um arquivo fora do Git, preencha os segredos e
informe seu caminho por `RUNTIME_ENV_FILE`.

```bash
ETL_IMAGE=registry.example/produtividade-etl:<tag> \
RUNTIME_ENV_FILE=/secure/path/produtividade.env \
docker compose -f deploy/portable/compose.yaml \
  --profile tools run --rm migrate

ETL_IMAGE=registry.example/produtividade-etl:<tag> \
RUNTIME_ENV_FILE=/secure/path/produtividade.env \
docker compose -f deploy/portable/compose.yaml \
  --profile jobs run --rm etl
```

No ambiente corporativo, o scheduler deve garantir uma única execução do ETL.
Se mais de um worker puder iniciar o job, o lock de arquivo deve ser substituído
por política de concorrência do orquestrador ou advisory lock no PostgreSQL.

## Dashboard

O dashboard dinâmico será uma segunda imagem OCI e usará o mesmo PostgreSQL por
rede privada, com identidade somente leitura. A imagem será adicionada quando
estiverem disponíveis o pacote, o entrypoint e o contrato de inicialização da
biblioteca interna.
