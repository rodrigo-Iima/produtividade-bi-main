# Fase 6 — Operacionalização local

Esta etapa fornece o mínimo necessário para executar e observar o ETL em uma
máquina local. Ela não tenta reproduzir ainda a arquitetura futura de AWS,
jobs distribuídos ou Kubernetes.

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

O runner usa `.runtime/etl.lock` para impedir duas execuções locais
simultâneas. Os resultados continuam registrados em `etl_run_log`, e o aceite
pós-carga gera os relatórios em `validation/`.

## Agendamento local temporário

Para um teste simples com `cron`, use o caminho absoluto do projeto e registre
na saída do sistema operacional:

```cron
0 7 * * 1-5 cd /caminho/do/projeto && ./.venv/bin/python -m operationalization run >> .runtime/etl.log 2>&1
```

O agendamento deve ser substituído quando o job for transferido para a
infraestrutura corporativa.

## Evolução planejada

- **AWS:** job containerizado, armazenamento de logs e métricas centralizado,
  segredos e execução agendada;
- **Kubernetes:** `Job`/`CronJob`, política de concorrência, retries do
  controlador e observabilidade do cluster;
- **Banco:** retenção e particionamento de fatos conforme o volume crescer;
- **Operação:** alertas para falha, execução atrasada, aceite não aprovado e
  aumento de dados sem tag ou sem atribuição de sprint.
