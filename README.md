# OKR de tempo de resolução de Bugs

Este projeto busca dados do Jira e do Clockify, relaciona os lançamentos aos
Bugs e prepara um contrato JSON para uma futura view HTML + CSS. Não há mais
PostgreSQL, Docker, Metabase ou dependência de dashboard neste fluxo.

## Métrica

- **Escopo Jira:** definido por `OKR_BUGS_JQL`; o padrão seleciona Bugs criados
  em 2026.
- **Estimativa:** campo Jira `timeoriginalestimate`, convertido de segundos
  para horas.
- **Tempo real:** duração dos lançamentos Clockify iniciados no ano analisado.
- **Relacionamento:** chave Jira encontrada na descrição ou no nome da Task do
  Clockify.
- **Mês:** mês de criação do Bug no Jira. O tempo de todos os lançamentos
  relacionados ao Bug é agregado antes da média mensal.
- **Média real:** média de horas reais entre os Bugs que possuem pelo menos um
  lançamento relacionado. A cobertura é exibida separadamente para não
  confundir ausência de apontamento com zero horas.
- **Lançamento com várias chaves:** o tempo é dividido igualmente entre as
  chaves reconhecidas, evitando duplicar horas.

O indicador principal para a OKR é `avg_actual_hours` por mês. A estimativa,
`avg_delta_hours`, `actual_to_estimate_ratio` e `coverage_pct` ajudam a explicar
o movimento sem substituir o indicador principal.

## Configuração

```bash
cp .env.example .env
```

Preencha as credenciais do Jira e do Clockify. Se a instância usa outro campo
de estimativa, ajuste `JIRA_ESTIMATE_FIELD`. A consulta JQL pode ser substituída
por `OKR_BUGS_JQL` ou pelo argumento `--jql`.

## Execução

```bash
python main.py --output outputs/okr_2026.json
```

O arquivo gerado contém a definição da métrica, os Bugs, os lançamentos
normalizados, os relacionamentos e as médias mensais. A camada visual será
construída depois sobre esse contrato.

## Testes

```bash
python -m unittest discover -s tests -v
```
