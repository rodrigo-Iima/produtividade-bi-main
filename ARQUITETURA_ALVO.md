# Arquitetura do projeto — Fase 5

## Objetivo

O projeto passa a ter como produto principal uma camada de dados no
PostgreSQL, alimentada por Python a partir do Jira e do Clockify. Power BI,
DAX, slicers e chamadas de API a partir de ferramentas de visualização não
fazem parte do runtime.

## Grão oficial implementado

O schema v2 está aplicado no PostgreSQL. O grão persistido é:

- `fato_clockify_entry`: uma linha por lançamento Clockify;
- `bridge_clockify_entry_tag`: uma linha por lançamento e tag;
- `bridge_clockify_entry_issue`: uma linha por lançamento e ticket Jira;
- `dim_ticket_jira`: uma linha por ticket Jira;
- `fato_jira_ticket_sprint`: uma linha por ticket e sprint;
- `bridge_clockify_entry_sprint`: uma linha por lançamento e sprint atribuída;
- `dim_colaborador`: uma linha por colaborador;
- `dim_squad_alias`: uma linha por nome bruto de squad e origem;
- `dim_tag`, `dim_papel_tag`, `dim_status`, `dim_sprint` e `dim_calendario`:
  dimensões de referência.

## Regras de totalização

1. O total geral de horas soma somente `fato_clockify_entry`. A duração não
   deve ser somada a partir da tabela de tags.
2. A duração aparece integralmente em cada tag de um lançamento com múltiplas
   tags. Portanto, a soma das horas por tag pode superar o total geral.
3. A squad do colaborador e a squad do ticket são atributos distintos e não
   devem ser misturados numa única coluna.
4. Lançamentos sem ticket, sem sprint ou com mais de uma atribuição possível
   permanecem armazenados com um status de atribuição; não são descartados.
5. A atribuição de sprint será derivada pelo relacionamento do ticket com a
   sprint e pelo intervalo temporal do lançamento.

## Camadas do código

- `clients/`: comunicação com Jira e Clockify;
- `etl/`: extração, transformação e orquestração;
- `models/`: entidades persistidas;
- `database/`: conexão, migrations, repositórios e cargas;
- `providers/`: regras de referência versionadas, como a matriz de tags;
- `queries/` ou `services/`: consultas de métricas e filtros, sem DAX.

### Camada analítica da fase 3

- `database/migrations/phase3.py`: cria cinco views reutilizáveis de detalhe
  do Clockify, relacionamentos de sprint/ticket e a versão da camada;
- `queries/metrics.py`: funções parametrizadas para total geral, colaborador,
  tag, squad, sprint, tag × sprint, KPIs do Clockify e métricas do Jira;
- `queries/__init__.py`: API pública das consultas para consumo por uma futura
  interface ou rotina de exportação.

O dashboard HTML em `dashboard/` é um artefato posterior e não participa do
runtime da transformação/carga.

Os filtros são combináveis por data, colaborador, papel, squad, projeto, tag,
foco, ticket, sprint e status de atribuição. Por padrão, as métricas de sprint
consideram apenas atribuições `atribuido`; `include_ambiguous=True` inclui
também as atribuições ambíguas.

### Transformação e carga da fase 4

- `etl/jira.py`: transforma tickets/sprints, substitui relações do ticket de
  forma idempotente e remove tickets que passaram a estar fora do escopo;
- `etl/jira_sprint_changelog.py`: preserva o histórico e materializa relações
  ticket × sprint descobertas somente no changelog;
- `etl/clockify.py`: deduplica lançamentos e tags, transforma foco e relações,
  e faz a substituição transacional do conjunto recarregado;
- `etl/quality.py`: executa o quality gate de órfãos, escopo, intervalos e
  status de atribuição;
- `database/migrations/phase4.py` e `database/etl_log.py`: registram cada
  etapa, status, erro e contagens de extração, transformação e carga em
  `etl_run_log`.

### Validação e aceite da fase 5

- `etl/acceptance.py`: executa uma suíte reproduzível de aceite sobre o banco
  carregado, cobrindo versões de schema/views, presença de dados, integridade
  referencial, grão das views, reconciliação de horas, histórico de sprint,
  planejamento e domínio de status;
- `validation/acceptance_report.json`: evidência estruturada para automação;
- `validation/acceptance_report.md`: relatório legível para revisão funcional.

A carga atual foi aceita com 32 verificações aprovadas, sem avisos ou falhas.
O total de 21.429,2875 horas da fato coincide com `total_hours()` e as
relações históricas processadas no changelog não possuem órfãos. Há 22
atribuições ambíguas de sprint, excluídas por padrão dos agrupamentos por
sprint, e 1.619 lançamentos sem tag, que permanecem válidos no total geral,
mas não aparecem nos agrupamentos por tag.

### Operacionalização da fase 6 — baseline local

- `operationalization run`: executa o ETL incremental e o aceite pós-carga;
- `operationalization status`: consulta as últimas execuções e etapas em
  `etl_run_log`;
- `operationalization healthcheck`: verifica conexão com o PostgreSQL e as
  tabelas essenciais;
- `.runtime/etl.lock`: impede duas execuções locais simultâneas;
- `--retries`: permite repetir a execução completa em caso de falha.

Essa implementação é deliberadamente local e simples. O lock de arquivo e o
agendamento por cron serão substituídos por política de concorrência,
`CronJob`/jobs, observabilidade e armazenamento centralizado quando o projeto
for levado para AWS/Kubernetes.

### Publicação Railway — etapa 1

O primeiro alvo de publicação é composto por PostgreSQL e ETL sem domínio
público, comunicando-se pela rede privada do Railway, e Metabase como único
serviço exposto pelo domínio `railway.app`. O ETL possui `Dockerfile`, aceita a
variável `DATABASE_URL` do Railway e encerra o engine SQLAlchemy no final de
cada execução. A topologia e as configurações esperadas estão em
`RAILWAY_PUBLICACAO.md`.

## Status da migração

Os artefatos específicos de Power BI, os scripts de backfill do modelo antigo
e os diagnósticos que dependiam dele foram removidos. A migração física foi
aplicada como schema v2, com chaves estrangeiras, índices e cópia dos dados
preserváveis da fase anterior.

A camada de métricas da fase 3 está aplicada no PostgreSQL com cinco views e
funções Python parametrizadas. A validação da carga atual encontrou 20.299
lançamentos Clockify, 20.404 relações de tag, 20.325 atribuições de sprint e
1.010 relações ticket-sprint, sem duplicação no grão persistido.

A fase 4 foi aplicada com o quality gate em estado aprovado: não há órfãos,
sprints fora do escopo, durações negativas, intervalos inválidos ou status de
atribuição desconhecidos na carga atual. A fase 5 foi aceita com a suíte de
validação e o relatório versionável em `validation/`. O dashboard HTML
permanece como artefato posterior e não faz parte da transformação/carga. A
fase 6 possui um runner local operacional, sem ainda representar o ambiente
corporativo futuro.
