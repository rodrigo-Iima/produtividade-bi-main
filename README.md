# OKR de tempo de resolução de Bugs

Este projeto busca dados do Jira e do Clockify, relaciona os lançamentos aos
Bugs e alimenta uma view HTML + CSS hospedada no Vercel. Não há PostgreSQL,
Docker, Metabase ou dependência de servidor local no fluxo hospedado.

## Métrica

- **Escopo Jira:** o padrão seleciona o projeto `ZG`, Bugs criados desde
  01/01/2026 até a data da execução e com estimativa informada. A data pode ser
  reproduzida com `--as-of`; `OKR_BUGS_JQL` continua disponível para exceções.
- **Estimativa:** campo Jira `timeoriginalestimate`, validado contra
  `aggregatetimeoriginalestimate` e `timetracking.originalEstimateSeconds`.
- **Tempo real:** soma das durações dos lançamentos Clockify iniciados no ano
  analisado e que possuem a tag exata `Dev`. A configuração
  `CLOCKIFY_DEV_TAG` permite alterar o nome da tag sem mudar o código.
- **Relacionamento:** chave Jira encontrada na descrição ou no nome da Task do
  Clockify.
- **Tabela de relação:** `tickets_with_clockify` possui uma linha por ticket
  Jira que tem pelo menos um lançamento Clockify mapeado. Ela mantém
  `clockify_actual_hours` e `jira_logged_hours` para auditoria, mas define
  `spent_hours` somente com as horas Clockify filtradas por `Dev`.
  `spent_source=clockify_dev` torna essa regra explícita.
- **Variação:** `variation_hours = spent_hours - estimate_hours`. Valor
  positivo significa que o tempo gasto excedeu a estimativa; valor negativo
  significa que ficou abaixo dela.
- **Campos ausentes:** `jira_logged_hours` vazio não invalida o ticket porque
  esse campo é apenas de auditoria. Estimativa ausente não entra na média de
  estimativa, variação ou razão. O tempo Dev válido continua podendo entrar na
  média de tempo real.
- **Proteções:** horas negativas, infinitas ou não numéricas são descartadas
  durante a normalização; estimativas de `0h` são tratadas como ausentes. A
  tabela final só aceita lançamentos Clockify positivos e valida novamente a
  fonte escolhida e a variação antes de gerar o JSON.
- **Mês:** mês de criação do Bug no Jira. O tempo de todos os lançamentos Dev
  relacionados ao Bug é agregado antes da média mensal.
- **Média real:** média de `spent_hours` entre os Bugs que possuem pelo menos
  um lançamento relacionado. A cobertura é exibida separadamente para não
  confundir ausência de apontamento com zero horas. Como a JQL exige estimativa,
  `coverage_pct` representa Bugs com lançamento Dev dividido por Bugs Jira
  elegíveis na consulta do período.
- **Lançamento com várias chaves:** o tempo é dividido igualmente entre as
  chaves reconhecidas, evitando duplicar horas.

O indicador principal para a OKR é `avg_actual_hours` por mês, usando a mesma
regra Clockify Dev. Os cards comparam duas coortes consolidadas por ticket:

- **Base:** Bugs criados entre 01/01 e 31/05;
- **Exclusão:** junho não participa dos KPIs;
- **Atual:** Bugs criados desde 01/07 até a data do snapshot.

As médias consolidadas não são médias das médias mensais. A estimativa,
`avg_delta_hours`, `actual_to_estimate_ratio` e `coverage_pct` ajudam a explicar
o movimento sem substituir o indicador principal.

## Configuração

```bash
cp .env.example .env
```

Preencha as credenciais do Jira e do Clockify. Os campos Jira usados são
`timeoriginalestimate` para a estimativa e `timespent` para o tempo lançado,
ambos convertidos de segundos para horas. `JIRA_ESTIMATE_FIELD` continua
disponível para uma exceção futura. A consulta JQL pode ser substituída por
`OKR_BUGS_JQL` ou pelo argumento `--jql`.

## Execução

```bash
./.venv/bin/python scripts/run_pipeline.py
```

Cada execução salva automaticamente `outputs/okr_YYYY-MM-DD.json`.
Para repetir exatamente um check-in anterior, use `--as-of YYYY-MM-DD`.

Para a primeira etapa, buscar somente os dados brutos e validar os campos Jira:

```bash
./.venv/bin/python scripts/run_pipeline.py --fetch-only
```

O arquivo gerado contém a definição da métrica, os Bugs, os lançamentos
normalizados, os relacionamentos e as médias mensais. A camada visual será
consumida pela view visual em `view/`.

## Execução hospedada no Vercel

O endpoint `/api/cron` executa o mesmo pipeline e grava um snapshot compacto no
Vercel Blob. O endpoint `/api/snapshot` entrega o snapshot mais recente para a
view. O agendamento está configurado para `0 10 * * 5` em UTC, equivalente a
sexta-feira às 07:00 em `America/Sao_Paulo`. O ETL permanece em Python, e a
persistência é delegada internamente a `api/blob.js`, que usa o SDK oficial
`@vercel/blob` e o OIDC do Vercel.

No projeto Vercel, configure as credenciais do Jira e do Clockify, além de:

- Blob conectado ao projeto: as conexões novas usam OIDC automaticamente. O
  projeto não precisa de `BLOB_READ_WRITE_TOKEN` quando o store estiver em OIDC;
  para um store legado, essa variável ainda pode ser informada;
- `CRON_SECRET`: segredo aleatório com pelo menos 16 caracteres.

Depois do primeiro deploy, execute o endpoint `/api/cron` uma vez com o
header `Authorization: Bearer <CRON_SECRET>` para gerar o primeiro snapshot.
As execuções seguintes serão feitas pelo Cron.

## View local

Depois de executar o pipeline, sirva a raiz do projeto:

```bash
python -m http.server 8000
```

Abra [http://localhost:8000/view/](http://localhost:8000/view/). A view busca
automaticamente o snapshot da data atual. Para abrir um snapshot específico,
use `http://localhost:8000/view/?data=../outputs/okr_2026-07-24.json`.

## Testes

```bash
python -m unittest discover -s tests -v
```
