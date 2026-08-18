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

# Executa o aceite específico do portfólio Jira (Etapa 8)
./.venv/bin/python -m operationalization accept-projects

# Backfill completo e idempotente dos metadados Jira históricos
./.venv/bin/python -m operationalization backfill-jira-metadata

# Reprocessa o changelog de Sprint de todos os tickets no escopo
./.venv/bin/python -m operationalization backfill-sprint-changelog

# Atualiza somente o portfólio de projetos, sem executar Clockify ou Flow
./.venv/bin/python -m operationalization run-projects --resume

# Backfill inicial dos Epics e da hierarquia desde 2026-01-01
./.venv/bin/python -m operationalization backfill-projects --from 2026-01-01 --resume

# Valida as invariantes das views do portfólio
./.venv/bin/python -m operationalization validate-projects --json

# Reconcilia a dimensão Jira, a bridge e a view final
./.venv/bin/python -m operationalization reconcile-projects --json
```

O backfill de metadados consulta tipo nativo, Atravessamento e
`timetracking.originalEstimateSeconds` no Jira e atualiza somente os tickets
existentes. A operação é idempotente; uma segunda execução deve informar zero
atualizações. O backfill de changelog materializa relações históricas
ticket × Sprint que não aparecem no estado atual do ticket.

O runner usa `.runtime/etl.lock` para impedir duas execuções simultâneas no
mesmo host. Os resultados continuam registrados em `etl_run_log`, e o aceite
pós-carga gera os relatórios em `.runtime/validation/`, fora da árvore
versionada do projeto.

Após uma carga bem-sucedida, o runner atualiza os snapshots materializados do
Analytics Interno (`phase30`) e executa `ANALYZE` neles antes do aceite. Por
isso, jobs alternativos que escrevam diretamente nas tabelas-base devem
executar o mesmo refresh na ordem documentada pela migration.

A janela analítica oficial fica em `vw_dashboard_sprint_window`, no grão
Sprint × Squad. Ela é semiaberta e usa o menor limite entre fim planejado,
início da próxima Sprint e encerramento formal antecipado (+1 dia). Um
encerramento atrasado no Jira não amplia a janela. `vw_dashboard_entry_final`,
`vw_dashboard_sprint_capacity_detail` e `vw_dashboard_sprint_timebox_detail`
consomem esse mesmo contrato.

Os comandos de projetos usam adicionalmente o advisory lock
`produtividade.project_pipeline`, mantido na sessão PostgreSQL. Isso impede que
um backfill e uma atualização incremental concorram mesmo quando iniciados por
processos ou agendadores diferentes no mesmo banco. Cada etapa (`hierarchy`,
`status_history`, `validate` e `reconcile`) recebe uma linha própria em
`etl_run_log`, e o checkpoint `jira_projects` em `etl_source_state` guarda o
watermark da última execução bem-sucedida.

`run-projects` usa o watermark para consultar Epics Jira atualizados desde a
última execução; quando a execução é a primeira, faz a carga completa do
escopo. `backfill-projects` sempre reprocessa o escopo inteiro, mas o
`--resume` evita repetir changelogs já concluídos.

O aceite de projetos é somente leitura e não chama Clockify ou Flow. Ele grava
`project_acceptance_report.json` e `project_acceptance_report.md` em
`.runtime/project-validation/`, cobrindo contagem dos quatro projetos,
Epics sem sprint, filhos históricos, unicidade, hierarquia, progresso,
inconsistências, datas, status, freshness, idempotência e reconciliação dos
KPIs da view oficial.

## Agendamento local da Etapa 11

O runner `scripts/run_etl_local.sh` é a entrada única para macOS e executa os
serviços do `deploy/local/compose.yaml` sem depender do diretório atual. Ele
carrega explicitamente `deploy/local/.env` e `deploy/local/runtime.env`, sobe o
PostgreSQL, espera o health check, cria um backup antes das migrations e então
executa a operação solicitada. Os logs por execução ficam em
`.runtime/logs/`, com rotação por tamanho e retenção configurável; o último
resultado fica em `.runtime/logs/last-run.status`.

```bash
# valida caminhos e o plano sem chamar Docker
scripts/run_etl_local.sh --dry-run

# atualização incremental (uma execução manual)
scripts/run_etl_local.sh --mode incremental

# reconciliação diária: backfill completo + reconcile-projects
scripts/run_etl_local.sh --mode reconcile --retries 1
```

Para instalar os dois `launchd` jobs no usuário atual, execute uma vez:

```bash
scripts/install_launchd_local.sh
```

O job incremental roda no minuto zero de cada hora. O job diário roda às
06:00, faz o backup, reexecuta o backfill idempotente dos Epics e grava a
reconciliação. Os arquivos materializados ficam em
`~/Library/LaunchAgents/`; para remover, use `launchctl bootout` com os labels
`com.zgsolucoes.produtividade-bi.projects-hourly` e
`com.zgsolucoes.produtividade-bi.projects-daily`.

## Pré-validação da Etapa 12

Antes de habilitar qualquer carga real, execute:

```bash
scripts/check_local_config.sh
```

O comando valida os dois arquivos locais, detecta placeholders, exige URL,
e-mail e token Jira e mostra somente decisões não sensíveis. O probe opcional
faz uma chamada autenticada a `/rest/api/2/myself` e informa apenas o status
HTTP:

```bash
scripts/check_local_config.sh --probe-jira
```

As credenciais permanecem em `deploy/local/runtime.env`, ignorado pelo Git.
Nunca cole tokens no código, em issues ou em logs.

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
`registros[0].token` e mantém o JWT somente em memória. Quando habilitada, a
execução consulta as identidades em `/api/v1/Pessoas`, extrai somente os campos
permitidos pelo DTO e sincroniza os colaboradores Flow com os usuários ativos
do Clockify. O endpoint `/api/v1/Funcionarios` não é utilizado porque seu
contrato pode expor dados salariais. As marcações são consultadas apenas para
os vínculos ativos e resolvidos.

A janela incremental do Clockify relê alterações recentes. Depois da carga do
Flow, a conferência diária é recalculada e mantém um histórico somente quando
horas ou situação mudam. Pendências ainda dentro do prazo são informativas;
pendências vencidas permanecem quantificadas no aceite pós-carga.

Por decisão funcional registrada em 2026-08-13, dias classificados como
`clockify_maior_vencido` são informativos: alguns colaboradores registram
legitimamente horas adicionais no Clockify. A contagem continua publicada no
relatório de aceite, mas não bloqueia nem gera aviso para a migração.

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

Como alternativa ao launchd, use caminhos absolutos e o mesmo runner. O
exemplo abaixo agenda o incremental no início de cada hora e a reconciliação
diária às 06:00:

```cron
0 * * * * /caminho/absoluto/produtividade-bi-main/scripts/run_etl_local.sh --mode incremental
0 6 * * * /caminho/absoluto/produtividade-bi-main/scripts/run_etl_local.sh --mode reconcile --retries 1
```

O script cria e mantém os próprios logs; não é necessário redirecionar para
um arquivo adicional. Em uma EC2, o cron pode permanecer como agendador
inicial, mas os caminhos e os arquivos de ambiente devem ser ajustados ao
usuário da instância. O arquivo `AWS_EC2_PUBLICACAO.md` apresenta a instalação
e a configuração do ambiente.

## Evolução planejada

- **AWS:** RDS ou banco gerenciado, armazenamento de logs e métricas
  centralizado, segredos e execução agendada;
- **Kubernetes:** `Job`/`CronJob`, política de concorrência, retries do
  controlador e observabilidade do cluster;
- **Banco:** retenção e particionamento de fatos conforme o volume crescer;
- **Operação:** alertas para falha, execução atrasada, aceite não aprovado e
  aumento de dados sem tag ou sem atribuição de sprint.
