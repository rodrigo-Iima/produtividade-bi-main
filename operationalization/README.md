# Fase 6 — Operacionalização local e EC2

Esta etapa fornece o mínimo necessário para executar e observar o ETL em uma
máquina local ou em uma instância Ubuntu da AWS. A execução continua sendo um
processo finito, adequado para cron, systemd timer ou um job containerizado.

## Comandos

Na raiz do projeto:

```bash
# Executa ETL incremental e validação pós-carga
./.venv/bin/python -m operationalization run

# Aplica todas as migrations, incluindo as views SQL do dashboard. Use como
# etapa separada antes de executar o ETL regular em ambiente containerizado.
./.venv/bin/python -m operationalization migrate

# Permite uma nova tentativa em caso de falha
./.venv/bin/python -m operationalization run --retries 1 --retry-delay 30

# Consulta as últimas execuções e suas etapas
./.venv/bin/python -m operationalization status
./.venv/bin/python -m operationalization status --json

# Verifica PostgreSQL e tabelas essenciais
./.venv/bin/python -m operationalization healthcheck

# Reexecuta apenas a validação sobre dados já carregados
./.venv/bin/python -m operationalization acceptance
```

O runner usa `.runtime/etl.lock` para impedir duas execuções simultâneas no
mesmo host. Os resultados continuam registrados em `etl_run_log`, e o aceite
pós-carga gera os relatórios em `.runtime/validation/`, fora da árvore
versionada do projeto.

Por compatibilidade, `ETL_AUTO_MIGRATE=true` continua sendo o padrão. Em
ambientes corporativos, execute `migrate` com uma identidade autorizada a DDL
e configure o job regular com `ETL_AUTO_MIGRATE=false`.

## Integração Flow

A carga de ponto permanece desativada até que o ambiente contenha:

```dotenv
FLOW_LOGIN_URL=https://zgsolucoes.flow.gp/metadados.api/api/v1/Login
FLOW_LOGIN_USERNAME=<segredo>
FLOW_LOGIN_PASSWORD=<segredo>
# Optional legacy fallback when Login credentials are not configured.
FLOW_API_TOKEN=
FLOW_TOKEN_REFRESH_SKEW_SECONDS=300
FLOW_ENABLED=true
# Temporarily disable identity sync when the Flow user cannot read
# collaborators; use persisted IDs for point collection instead.
FLOW_IDENTITY_SYNC_ENABLED=true
FLOW_POINTS_INCLUDE_UNMAPPED=false
HOURS_COMPETENCE_CLOSING_DAY=25
HOURS_RECONCILIATION_LOOKBACK_DAYS=45
HOURS_RECONCILIATION_TOLERANCE_MINUTES=15
FLOW_RECONCILIATION_IGNORED_PERSON_IDS=208
CLOCKIFY_INCREMENTAL_LOOKBACK_DAYS=10
```

As credenciais do Login devem ficar no `.env` não versionado ou no gerenciador
de segredos do ambiente. O ETL autentica no início da chamada, extrai
`registros[0].token` e mantém o JWT somente em memória. Quando habilitada, a execução sincroniza primeiro os colaboradores
Flow com os usuários ativos do Clockify e consulta marcações apenas para os
vínculos ativos e resolvidos.

A janela incremental do Clockify relê alterações recentes. Depois da carga do
Flow, a conferência diária é recalculada e mantém um histórico somente quando
horas ou situação mudam. Pendências ainda dentro do prazo são informativas;
pendências vencidas aparecem como avisos no aceite pós-carga.

Na conferência, lançamentos concluídos do Clockify são rateados na meia-noite
de `America/Sao_Paulo`, sem alterar o lançamento bruto. Diferenças de até 15
minutos por dia são aceitas; acima disso, a situação informa se o Clockify
ficou maior ou menor que o ponto. Marcações ímpares, cálculo pendente ou erro
do Flow invalidam o dia. O dia atual não gera alerta.

O prazo usa fechamento fixo no dia 25 do próprio mês da data trabalhada:
17/07 fecha em 25/07. Se o mês não possuir o dia configurado, usa-se seu
último dia. Pessoas listadas em `FLOW_RECONCILIATION_IGNORED_PERSON_IDS`
continuam no histórico, com status `ignorado_regra_negocio`, mas não geram
pendências nem alertas.

## Agendamento por cron

Para um teste simples com `cron`, use o caminho absoluto do projeto e registre
na saída do sistema operacional:

```cron
0 7 * * 1-5 cd /caminho/do/projeto && mkdir -p .runtime && ./.venv/bin/python -m operationalization run >> .runtime/etl.log 2>&1
```

Em uma EC2, o cron pode permanecer como agendador inicial. O arquivo
`AWS_EC2_PUBLICACAO.md` apresenta a instalação, permissões e a configuração
do ambiente.

## Evolução planejada

- **AWS:** RDS ou banco gerenciado, armazenamento de logs e métricas
  centralizado, segredos e execução agendada;
- **Kubernetes:** `Job`/`CronJob`, política de concorrência, retries do
  controlador e observabilidade do cluster;
- **Banco:** retenção e particionamento de fatos conforme o volume crescer;
- **Operação:** alertas para falha, execução atrasada, aceite não aprovado e
  aumento de dados sem tag ou sem atribuição de sprint.
