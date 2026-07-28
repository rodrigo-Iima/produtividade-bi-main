# Contrato inicial das views do dashboard dinâmico

Este documento define a fronteira entre o modelo analítico no PostgreSQL e a
biblioteca interna que renderizará HTML dinâmico. A aplicação deve consultar o
banco no servidor; o navegador não recebe credenciais nem se conecta
diretamente ao PostgreSQL.

## Views principais

| View | Grão | Uso e regra de agregação |
|---|---|---|
| `vw_dashboard_entry_base` | lançamento Clockify | Fonte do total de horas; somar `duration_hours` sem joins que multipliquem lançamentos |
| `vw_dashboard_sprint_productivity` | sprint de período × colaborador | KPIs de produtividade; filtrar sprint antes de agregar |
| `vw_dashboard_entry_tag` | lançamento × tag | Distribuição por tag; horas podem superar o total geral quando há múltiplas tags |
| `vw_dashboard_entry_sprint` | lançamento × sprint candidata | Diagnóstico de atribuições e ambiguidades |
| `vw_dashboard_ticket_sprint` | ticket × sprint | Métricas Jira; usar `COUNT(DISTINCT issue_key)` |
| `vw_dashboard_ticket_filterable` | ticket × sprint × colaborador relacionado | Propagação de filtros de pessoa e papel para métricas Jira |
| `vw_dashboard_sprint_kpis` | sprint | Resumo de horas, tickets e ambiguidades por sprint |
| `vw_dashboard_entry_final` | lançamento Clockify | Classificação final de sprint e squad para painéis corporativos |
| `vw_dashboard_sprint_capacity` | sprint × squad | Capacidade e horas por equipe na sprint |
| `vw_dashboard_sprint_efficiency` | sprint × squad × papel × grupo de capacidade | Eficiência detalhada por composição da equipe |
| `vw_dashboard_filter_sprint_squad` | sprint × squad | Opções válidas do filtro combinado |

## Filtros

- Período de esforço usa `entry_date` ou `entry_date_local`.
- Período de sprint usa `sprint_start`.
- Squad de esforço usa os campos de squad do colaborador.
- Squad de tickets usa os campos de squad do Jira.
- Filtros de pessoa aplicados a tickets passam por
  `vw_dashboard_ticket_filterable`.
- Atribuições ambíguas não entram em métricas canônicas de horas por sprint.

## Regras invariantes

1. O total geral de horas vem do grão de lançamento.
2. Horas por tag não devem ser reconciliadas por soma com o total geral.
3. Tickets devem ser deduplicados pelo grão `issue_key × sprint_id`.
4. Percentuais são calculados como razão entre somas; não como média de
   percentuais por colaborador.
5. O timezone funcional é `America/Sao_Paulo`; transporte e armazenamento de
   timestamps devem continuar usando tipos com timezone.
6. A aplicação deve abrir conexões com um usuário somente leitura e
   `search_path` explícito.

## Contrato operacional da futura imagem

A imagem `produtividade-dashboard` deverá receber em runtime:

- `DATABASE_URL` ou os campos `POSTGRES_*`;
- `POSTGRES_SSLMODE`;
- configuração de bind/porta definida pela biblioteca interna;
- configuração corporativa de autenticação e autorização;
- versão do contrato das views esperada pela aplicação.

Antes de iniciar, o serviço deverá verificar a conexão, a presença das views
obrigatórias e a versão compatível do schema analítico. O entrypoint concreto
será definido quando a interface da biblioteca interna estiver disponível.
