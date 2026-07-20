# Gestão à Vista — camada analítica no Metabase

## Migration

A migration da camada analítica está em:

`database/migrations/phase7_dashboard_gestao_a_vista.sql`

Ela deve ser aplicada no PostgreSQL com permissão de DDL. As views são
recriadas dentro de uma transação para permitir evolução de colunas sem deixar
dependências antigas no banco.

Exemplo no EC2:

```bash
docker compose --env-file deploy/ec2/.env \
  -f deploy/ec2/docker-compose.yml exec -T postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
  < database/migrations/phase7_dashboard_gestao_a_vista.sql
```

Depois da aplicação, sincronizar o schema da base no Metabase e mapear os
filtros em cada card.

## Views e grãos

| Objeto | Grão | Uso |
|---|---|---|
| `vw_dashboard_valid_sprint` | sprint | Regra única de escopo de sprint |
| `dim_papel_atividade_principal` | papel × tag | Atividade principal por papel |
| `vw_dashboard_entry_base` | lançamento Clockify | Horas sem duplicação, filtros de pessoa e sprint canônica |
| `vw_dashboard_sprint_productivity` | sprint de período × colaborador | Fonte única dos KPIs de produtividade e qualidade dos lançamentos |
| `vw_dashboard_entry_tag` | lançamento × tag | Distribuição por tag e foco |
| `vw_dashboard_entry_sprint` | lançamento × sprint candidata | Atribuições e ambiguidades |
| `vw_dashboard_ticket_sprint` | ticket × sprint | TMR, eficiência, conclusão e Atravessamento |
| `vw_dashboard_ticket_filter_bridge` | ticket × sprint × colaborador | Propagação de filtros de pessoa para Jira |
| `vw_dashboard_ticket_filterable` | ticket × sprint × colaborador | Cards Jira que precisam de pessoa/papel |
| `vw_dashboard_sprint_kpis` | sprint | Resumo sem filtro de pessoa |

Todas as views de sprint usam estritamente:

```text
sprint_start > 01/01/2026
sprint_start <= momento atual
sprint_state IN (active, closed)
```

## Semântica de squad e filtros

O modelo agora mantém as duas noções de squad, sem misturá-las:

- Cards de esforço/pessoas: `collaborator_squad_id` e
  `collaborator_squad_name`, originados do grupo do colaborador no Clockify.
- Cards de tickets/sprint: `jira_squad_id` e `jira_squad_name`, originados do
  campo de squad do ticket no Jira e normalizados por `dim_squad_alias`.

Esse é o desenho mais robusto: horas pertencem à pessoa que apontou; tickets
pertencem à squad responsável no Jira. No Metabase, o filtro global `Squad`
deve ser conectado ao campo de colaborador nos cards Clockify e ao campo de
squad Jira nos cards Jira.

`Papel` e `Colaborador` são filtros diretos nos cards Clockify. Nos cards Jira,
eles passam por `vw_dashboard_ticket_filterable`, que relaciona o ticket às
issues mencionadas nos lançamentos Clockify. Por isso, tickets sem lançamento
Clockify relacionado não aparecem quando um filtro de pessoa é aplicado.

O filtro `Sprint` funciona diretamente em `vw_dashboard_entry_base` para
lançamentos com uma atribuição única e em `vw_dashboard_ticket_sprint` para
Jira. Lançamentos com sprint ambígua permanecem identificados, mas não recebem
um `sprint_id` canônico para evitar duplicação de horas.

Para os cards de produtividade, usar `vw_dashboard_sprint_productivity`. Essa
view atribui o lançamento ao período calendário da sprint, independentemente de
ele possuir issue Jira. O intervalo considera a data inicial e a data final da
sprint inclusive, conforme o filtro de datas do Clockify. O grão é
`sprint × colaborador`; portanto, o filtro `Sprint` deve ser aplicado antes da
agregação. Não se deve somar essa view entre todas as sprints sem agrupar por
sprint, pois sprints de squads diferentes podem ocorrer simultaneamente.
Como a dimensão de sprint não possui uma squad proprietária única confiável,
use também o filtro `Squad` para reproduzir exatamente o total de horas da
respectiva equipe no Clockify.

O filtro `Período` deve ser conectado conforme o card:

- esforço Clockify: `entry_date`;
- análise de sprint: `sprint_start`;
- criação de tickets: `created_at`;
- conclusão de tickets: `resolved_at`.

Na view `vw_dashboard_sprint_productivity`, o filtro `Sprint` deve usar
`sprint_name`, e os filtros de pessoa devem usar `collaborator_squad_name`,
`collaborator_name` e `papel`.
Todos os cards de horas da Sprint — total, foco, atividade principal, apoio,
ticket e qualidade — devem usar esta mesma view. No Metabase, os cards devem
ser resumidos por soma das colunas de horas correspondentes; isso evita que
cada card precise consultar uma tabela diferente ou depender de parâmetros SQL.

## Métricas

### KPIs estratégicos

- **Horas totais gerais:** `SUM(duration_hours)` em `vw_dashboard_entry_base`.
- **Horas totais da sprint:** `SUM(horas_totais)` em
  `vw_dashboard_sprint_productivity`. Inclui todos os lançamentos do período,
  mesmo sem issue Jira.
- **Horas com ticket:** `SUM(horas_com_ticket)` em
  `vw_dashboard_sprint_productivity`.
- **Horas sem ticket:** `SUM(horas_sem_ticket)` em
  `vw_dashboard_sprint_productivity`.
- **Qualidade dos lançamentos:**
  `SUM(horas_com_ticket) / SUM(horas_totais)`. Esse é o índice que deve ser
  acompanhado quinzenalmente para avaliar a evolução da rastreabilidade.
  No Metabase, exibir o resultado como percentual; não usar a média da coluna
  `indice_qualidade_lancamentos` quando houver mais de um colaborador filtrado.
- **Horas vinculadas à sprint no Jira:** `SUM(horas_vinculadas_sprint)` em
  `vw_dashboard_sprint_productivity`. É uma métrica de rastreabilidade mais
  restritiva que horas com ticket.
- **Horas foco:** `SUM(horas_foco)` em
  `vw_dashboard_sprint_productivity`.
- **Percentual de foco:** horas foco divididas pelas horas elegíveis, excluindo
  lançamentos sem papel ou sem classificação de foco. Usar
  `SUM(horas_foco) / SUM(horas_foco_elegiveis)`.
- **Horas de atividade principal:** `SUM(horas_atividade_principal)` em
  `vw_dashboard_sprint_productivity`.
- **Horas de apoio à entrega:** `SUM(horas_apoio_entrega)` em
  `vw_dashboard_sprint_productivity`.
- **Tickets concluídos:** `COUNT(DISTINCT issue_key)` com status agrupado
  `Concluído`.

### KPIs de sprint

`vw_dashboard_sprint_kpis` contém o resumo sem filtros de pessoa:

- **Eficiência da sprint:**
  `tickets_planejados_concluidos / tickets_planejados_inicio`;
- **Tickets atravessados:** `COUNT(DISTINCT issue_key)` com
  `atravessamento_flag = true`;
- **Percentual de atravessamento:** tickets atravessados dividido pelo total
  de tickets da sprint;
- **TMR médio:** média do tempo de resolução por ticket distinto;
- **TMR mediano:** mediana do tempo de resolução por ticket distinto;
- **Índice de apoio à entrega:** horas `qa` + `dev-check` divididas pelas horas
  de entrega classificadas;
- **Horas ambíguas:** esforço que possui mais de uma sprint candidata, exibido
  separadamente e não incluído nas horas atribuídas padrão.

Para cards Jira conectados aos filtros `Colaborador` ou `Papel`, usar
`vw_dashboard_ticket_filterable`. Como essa view pode possuir mais de uma
linha por ticket quando há vários colaboradores relacionados, as consultas
devem usar `COUNT(DISTINCT issue_key)`. Para TMR, primeiro deduplicar por
`issue_key, sprint_id` e só depois calcular a média ou mediana.

Exemplo conceitual para TMR filtrado:

```sql
SELECT sprint_id, AVG(resolution_time_days)
FROM (
    SELECT DISTINCT issue_key, sprint_id, resolution_time_days
    FROM vw_dashboard_ticket_filterable
    WHERE resolution_time_days IS NOT NULL
) AS tickets_distintos
GROUP BY sprint_id;
```

## Cards de controle e risco

- Distribuição por tag: usar `vw_dashboard_entry_tag`; a soma pode superar o
  total quando um lançamento possui várias tags.
- Sem tag: `has_tag = false` em `vw_dashboard_entry_base`.
- Sem ticket: `has_ticket = false`.
- Qualidade dos lançamentos: acompanhar `horas_com_ticket`, `horas_sem_ticket`
  e o índice `SUM(horas_com_ticket) / SUM(horas_totais)`.
- Sem sprint: `has_sprint = false`.
- Sprint ambígua: `vw_dashboard_entry_sprint.assignment_status = 'ambiguo'`.
- TMR inválido: `resolution_time_days IS NULL`; não converter para zero.
- Atravessamento: acompanhar quantidade e percentual por sprint, squad Jira e
  status de conclusão.

## QA após a aplicação

Executar no PostgreSQL:

```sql
SELECT COUNT(*) FROM vw_dashboard_valid_sprint;

SELECT COUNT(*) - COUNT(DISTINCT entry_id)
FROM vw_dashboard_entry_base;

SELECT COUNT(*) - COUNT(DISTINCT (issue_key, sprint_id))
FROM vw_dashboard_ticket_sprint;

SELECT extraction_method, COUNT(*)
FROM bridge_clockify_entry_issue
GROUP BY extraction_method
ORDER BY extraction_method;

SELECT COUNT(*)
FROM vw_dashboard_ticket_sprint
WHERE resolution_time_days < 0;

SELECT
    sprint_name,
    ROUND(SUM(horas_totais)::numeric, 2) AS horas_totais,
    ROUND(SUM(horas_com_ticket)::numeric, 2) AS horas_com_ticket,
    ROUND(
        (SUM(horas_com_ticket) / NULLIF(SUM(horas_totais), 0.0))::numeric,
        4
    ) AS qualidade_lancamentos
FROM vw_dashboard_sprint_productivity
GROUP BY sprint_id, sprint_name
ORDER BY MIN(sprint_start);

SELECT
    COUNT(*) AS linhas,
    COUNT(DISTINCT (sprint_id, user_id)) AS combinacoes_sprint_colaborador,
    COUNT(*) FILTER (
        WHERE indice_qualidade_lancamentos < 0
           OR indice_qualidade_lancamentos > 1
    ) AS indices_fora_do_intervalo
FROM vw_dashboard_sprint_productivity;
```

Também executar o aceite do projeto:

```bash
./.venv/bin/python -m operationalization acceptance
```

A migration prepara a camada de dados. A criação dos cards, conexão dos filtros
em cada card, formatação e publicação continuam sendo etapas do Metabase.
