# Publicação inicial no Railway — etapa 1

## Topologia do teste

```text
Jira + Clockify
       │
       ▼
ETL Python — Railway Cron Job (sem domínio público)
       │ conexão privada
       ▼
PostgreSQL Railway (sem domínio público)
       ▲
       │ conexão privada, somente leitura
Metabase — serviço público via domínio railway.app
```

O PostgreSQL e o ETL não devem receber domínio público. O único serviço com
domínio público nesta fase é o Metabase.

## Serviços a criar no Railway

1. **PostgreSQL**: banco analítico da aplicação. Usar as variáveis fornecidas
   pelo Railway, preferencialmente `DATABASE_URL` e as variáveis privadas do
   serviço.
2. **ETL**: serviço baseado neste repositório, usando o `Dockerfile` da raiz.
   Configurar como Cron Job, com comando padrão:

   ```bash
   python -m operationalization run
   ```

   Não gerar domínio para esse serviço.
3. **Metabase**: serviço separado usando a imagem oficial do Metabase. Gerar
   domínio Railway apenas para esse serviço.
4. **Banco de aplicação do Metabase**: preferencialmente uma base lógica
   separada da base analítica. Nunca usar o H2 padrão para a publicação.

## Variáveis do ETL

O código aceita `DATABASE_URL` do Railway. No ambiente local, continua aceitando
`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER` e
`POSTGRES_PASSWORD`.

Também devem ser configuradas no serviço ETL as variáveis Jira e Clockify já
existentes no `.env.example`.

Se for necessário forçar SSL na conexão PostgreSQL, configurar
`POSTGRES_SSLMODE=require`. A conexão deve usar o endereço privado do Railway;
não usar TCP Proxy ou domínio público para a comunicação interna entre os
serviços.

## Encerramento do Cron Job

O comando termina com código `0` em caso de sucesso e código diferente de zero
em caso de falha. O `main()` sempre executa `engine.dispose()` no bloco
`finally`, encerrando o pool SQLAlchemy antes do processo terminar. O runner
também libera o lock local em qualquer saída.

Isso é necessário para que uma execução não deixe conexões ou processo ativos
e bloqueie as próximas execuções agendadas.

## Não fazer nesta etapa

- não criar domínio público para PostgreSQL;
- não criar domínio público para o ETL;
- não executar o ETL como serviço HTTP permanente;
- não publicar o HTML local como dashboard principal;
- não configurar ainda Kubernetes ou múltiplos ambientes.
