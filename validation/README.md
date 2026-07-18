# Validação e aceite

A suíte da fase 5 valida o banco após a carga das APIs. Ela não chama Jira ou
Clockify e não altera os dados.

Execute na raiz do projeto:

```bash
./.venv/bin/python -m etl.acceptance
```

São gerados:

- `acceptance_report.json`: resultado estruturado para automação;
- `acceptance_report.md`: evidência legível para revisão e aceite.

O status é `accepted` quando não há falhas nem avisos,
`accepted_with_warnings` quando há apenas avisos e `not_accepted` quando algum
critério obrigatório falha. A suíte também registra limitações funcionais,
como lançamentos sem tag e atribuições ambíguas de sprint.
