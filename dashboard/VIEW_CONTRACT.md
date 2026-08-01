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
| `vw_dashboard_sprint_capacity` | sprint × squad | Capacidade efetiva e horas por equipe na sprint |
| `vw_dashboard_sprint_efficiency` | sprint × squad × papel × grupo de capacidade | Eficiência detalhada por composição da equipe, usando capacidade efetiva |
| `vw_dashboard_sprint_timebox` | sprint × squad | Fonte única dos cards de timebox, horas trabalhadas Flow e horas lançadas Clockify |
| `vw_dashboard_filter_sprint_squad` | sprint × squad | Opções válidas do filtro combinado |
| `vw_flow_ponto_dia` | colaborador Flow × dia | Marcações, pares sequenciais e horas canônicas do ponto |
| `vw_flow_marcacao_detail` | colaborador Flow × dia × ordem | Auditoria de cada marcação na ordem retornada pela API |
| `vw_conferencia_horas_dia` | colaborador × dia | Comparação incremental entre horas do ponto e lançamentos Clockify |
| `vw_conferencia_horas_semana` | colaborador × semana | Resumo complementar da conferência diária e de suas pendências |
| `vw_fila_revisao_horas` | colaborador × dia acionável | Revisão exclusiva de dias vencidos em que o Clockify supera o ponto |

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
7. As horas do ponto são a soma dos pares sequenciais de marcações `1–2`,
   `3–4` e assim por diante; a data analítica continua sendo `master_date`,
   inclusive quando a saída ocorre após a meia-noite.
8. Marcações ímpares, cálculos pendentes ou erros do Flow tornam o ponto
   incompleto. O campo `confirmed` permanece informativo porque a homologação
   mostrou dias estruturalmente válidos com valor `false`.
9. O banco de horas não participa da primeira versão da jornada nem da
   conferência com o Clockify.
10. A conferência soma todos os lançamentos concluídos do Clockify e divide
    lançamentos que atravessam a meia-noite no timezone
    `America/Sao_Paulo`; a fato bruta não é alterada.
11. Diferenças diárias de até 15 minutos, inclusive, são aceitas. Acima disso,
    o status distingue Clockify maior de Clockify menor.
12. Todo dia com ponto e sem Clockify é pendência. Dias `Compensado` continuam
    identificados pelo tipo para análise separada; Clockify em `Férias` ou
    `Repouso Remunerado` gera alerta específico.
13. O dia corrente permanece `em_andamento` e só entra na cobrança a partir do
    dia seguinte.
14. O prazo de ajuste fecha no dia 25 do próprio mês da data trabalhada; por
    exemplo, 17/07 tem prazo até 25/07.
15. Exceções pessoais permanecem auditáveis como
    `ignorado_regra_negocio`, sem compor pendências ou alertas.
16. A meta de aproveitamento dos lançamentos é 80% das horas válidas do ponto.
    A taxa `clockify_utilization_rate` e o indicador
    `meets_clockify_utilization_target` ficam disponíveis no grão diário.
17. Clockify menor que o ponto, ponto ausente/incompleto e ponto sem Clockify
    não entram na fila de revisão cuidadosa. Continuam no histórico e nas views
    do painel; dias sem Clockify servem para lembrar o colaborador de lançar.
18. A capacidade efetiva da Sprint preserva o snapshot teórico existente e
    desconta, por colaborador, dias Flow classificados como `Compensado`,
    `Férias`, `Repouso Remunerado` ou `Ocorrência`, limitados à capacidade
    disponível. A view preserva `calendar_capacity_hours`,
    `flow_non_working_days`, `flow_non_working_days_applied` e
    `flow_non_working_hours`; `sprint_window_business_days` permite identificar
    eventual defasagem da janela materializada.
19. Os três cards operacionais usam `vw_dashboard_sprint_timebox`: `timebox_hours`
    é a capacidade produtiva efetiva, `hours_worked` é a soma das marcações
    Flow e `hours_logged` é a soma dos lançamentos Clockify. Os três valores
    permanecem separados; Clockify não substitui as horas de ponto.

## Decisões pendentes para métricas de ponto

- Uso de jornada esperada, justificativas e avisos do Flow.
- Limites, frequência e canal dos alertas operacionais de dados.

## Estrutura planejada para banco de horas

Quando o contrato do campo `hours_bank` estiver validado, o saldo será
armazenado como snapshot, sem sobrescrever o histórico:

- chave por pessoa Flow, data de referência e instante de coleta;
- saldo assinado normalizado em segundos;
- período de competência e identificador de contrato, quando disponíveis;
- valor e unidade originais preservados para auditoria;
- origem da alteração separando cálculo normal, ajuste e expiração.

Essa futura fato não alterará as horas pareadas. Ela será conciliada em uma
camada própria para evitar misturar jornada realizada com saldo acumulado.

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
