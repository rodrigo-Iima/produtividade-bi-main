# Fase 6 — Operacionalização local e EC2

Esta etapa fornece o mínimo necessário para executar e observar o ETL em uma
máquina local ou em uma instância Ubuntu da AWS. A execução continua sendo um
processo finito, adequado para cron, systemd timer ou um job containerizado.

## Comandos

Na raiz do projeto:

```bash
# Executa ETL incremental e validação pós-carga
./.venv/bin/python -m operationalization run

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
pós-carga gera os relatórios em `validation/`.

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
