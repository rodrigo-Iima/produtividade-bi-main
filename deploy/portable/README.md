# Runtime OCI portátil

Este deployment contém somente os jobs do projeto. Ele não inclui PostgreSQL,
Metabase, volume de dados ou segredos e pode ser usado como referência em AWS,
OVH, Kubernetes ou uma VM com Docker Compose.

## Validar antes da imagem

Os testes não acessam um banco real, mas a configuração precisa de uma URL
sintaticamente válida durante a coleta:

```bash
python -m pip install -r requirements-dev.txt
DATABASE_URL=postgresql://test:test@127.0.0.1:1/test \
  python -m pytest -q
```

Antes de promover uma release, valide também `migrate` duas vezes sobre um
PostgreSQL vazio e execute `healthcheck --json`. Isso confirma criação do
schema, views, idempotência e conectividade da imagem.

## Construir a imagem ETL local

```bash
docker build \
  -f Dockerfile.etl \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  -t produtividade-etl:"$(git rev-parse --short HEAD)" \
  .
```

O carregamento local (`--load`) deve usar uma única arquitetura. Em Macs Apple
Silicon, por exemplo:

```bash
docker buildx build \
  --platform linux/arm64 \
  --load \
  -f Dockerfile.etl \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  -t produtividade-etl:"$(git rev-parse --short HEAD)" \
  .
```

## Publicar a imagem multi-arquitetura

A release portátil deve ser publicada em um registry OCI com um único tag e
manifests para `linux/amd64` e `linux/arm64`:

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --push \
  -f Dockerfile.etl \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  -t registry.example/produtividade-etl:"$(git rev-parse --short HEAD)" \
  .
```

O registry é a forma recomendada de entregar a imagem ao ambiente corporativo.
Enquanto o registry definitivo não estiver definido, o mesmo build pode ser
exportado como um arquivo OCI multi-arquitetura:

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f Dockerfile.etl \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  -t produtividade-etl:"$(git rev-parse --short HEAD)" \
  --output type=oci,dest=produtividade-etl.oci.tar \
  .
```

Esse arquivo fica na máquina onde o comando foi executado. Ele serve para
validação ou transferência offline; não substitui um registry para operação
normal.

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

Para carregar as marcações de ponto, forneça `FLOW_LOGIN_USERNAME` e
`FLOW_LOGIN_PASSWORD` nesse arquivo e defina `FLOW_ENABLED=true`. O ETL chama o
endpoint Login e mantém o JWT somente em memória. `FLOW_API_TOKEN` permanece
como fallback legado quando o Login não estiver configurado. Nenhuma dessas
credenciais deve ser incluída na imagem nem no Compose versionado.

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
