# Fase 5 — Relatório de validação e aceite

**Status:** `accepted`  
**Executado em:** `2026-07-19T14:38:46.428803+00:00`  
**Checks:** 33 aprovados, 0 avisos, 0 falhas.

## Resumo técnico

O modelo possui 20,299 lançamentos Clockify, 5,314 tickets Jira e 16 sprints dentro do escopo.

O total reconciliado é **21429.2875 horas**; a função `total_hours()` retornou **21429.2875 horas**.

## Critérios de aceite

| Critério | Status | Observado | Esperado | Severidade |
|---|---|---:|---:|---|
| Schema operacional com Atravessamento e bridge auditável aplicado | pass | 5 | >= 5 | critical |
| Camada de views da fase 3 aplicada | pass | 3 | >= 3 | high |
| Tabela dim_sprint carregada | pass | 16 | > 0 | high |
| Tabela dim_ticket_jira carregada | pass | 5314 | > 0 | high |
| Tabela fato_clockify_entry carregada | pass | 20299 | > 0 | high |
| Tabela bridge_clockify_entry_tag perfilada | pass | 20404 | >= 0 | info |
| Tabela bridge_clockify_entry_issue perfilada | pass | 6304 | >= 0 | info |
| Tabela bridge_clockify_entry_sprint perfilada | pass | 20325 | >= 0 | info |
| Tabela fato_jira_ticket_sprint perfilada | pass | 1011 | >= 0 | info |
| Tabela jira_sprint_changelog perfilada | pass | 602 | >= 0 | info |
| Quality gate: orphan_clockify_tag_links | pass | 0 | 0 | critical |
| Quality gate: orphan_clockify_issue_links | pass | 0 | 0 | critical |
| Quality gate: orphan_clockify_sprint_links | pass | 0 | 0 | critical |
| Quality gate: orphan_ticket_sprint_links | pass | 0 | 0 | critical |
| Quality gate: orphan_changelog_links | pass | 0 | 0 | critical |
| Quality gate: out_of_scope_sprints | pass | 0 | 0 | critical |
| Quality gate: negative_durations | pass | 0 | 0 | critical |
| Quality gate: invalid_clockify_intervals | pass | 0 | 0 | critical |
| Quality gate: invalid_sprint_assignment_status | pass | 0 | 0 | critical |
| Quality gate: invalid_clockify_issue_extraction_method | pass | 0 | 0 | critical |
| View de lançamento mantém uma linha por entrada | pass | 20299 | 20299 | critical |
| View de tags mantém uma linha por entrada × tag | pass | 20404 | 20404 | critical |
| View de sprint mantém uma linha por entrada × atribuição | pass | 20325 | 20325 | critical |
| View Jira mantém uma linha por ticket × sprint | pass | 1011 | 1011 | critical |
| Total de horas da função coincide com a soma direta da fato | pass | 21429.2875 | 21429.2875 | critical |
| Horas por squad recompõem o total sem duplicação | pass | 21429.2875 | 21429.2875 | high |
| Horas atribuídas a sprint não superam o total de lançamentos | pass | 1990.6927777777778 | <= 21429.2875 | high |
| Todo relacionamento processado no changelog existe na fato histórica | pass | 0 | 0 | high |
| Nenhum ticket permaneceu com falha no changelog | pass | 0 | 0 | high |
| Relações ticket × sprint possuem resultado de planejamento | pass | 0 | 0 | high |
| Status Jira estão classificados na dimensão de status | pass | 0 | 0 | medium |
| Lançamentos sem tag são identificados para aceite funcional | pass | 1619 | informativo | medium |
| Eficiência da sprint está entre 0% e 100% | pass | 0.7535211267605634 | 0 <= valor <= 1 | high |

## Evidências e limitações

- Relações changelog sem correspondência na fato histórica: **0**.
- Atribuições ambíguas de sprint: **22**; elas ficam excluídas por padrão das métricas agrupadas por sprint.
- Lançamentos sem tag: **1619**; o total geral continua válido, mas esses lançamentos não aparecem nos agrupamentos por tag.
- A validação é sobre o banco carregado; não reexecuta APIs nem altera registros.

## Próximas ações

1. Corrigir qualquer critério `fail` antes de liberar o dashboard para uso operacional.
2. Registrar a aprovação funcional dos KPIs com amostras revisadas pelos responsáveis.
3. Usar `etl_run_log` e este relatório em cada carga agendada.
