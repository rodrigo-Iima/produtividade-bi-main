# OKR de tempo de resolução de Bugs e Adaptativas

Este projeto busca dados do Jira e do Clockify, relaciona os lançamentos aos
Bugs e alimenta uma view HTML + CSS publicada como site estático. Não há
PostgreSQL, Docker, Metabase ou dependência de servidor local no fluxo
publicado.

## Métrica

- **Escopo Jira:** o padrão seleciona o projeto `ZG`, tickets dos tipos `Bug` e
  `Adaptativa`, com status concluído, criados desde 01/01/2026 até a data da
  execução e com estimativa informada. A JQL usa o alias `Done`, enquanto a
  API retorna o status localizado `Concluído`. A data pode ser reproduzida com
  `--as-of`; `OKR_BUGS_JQL` continua disponível para exceções.
- **Estimativa:** campo Jira `timeoriginalestimate`, validado contra
  `aggregatetimeoriginalestimate` e `timetracking.originalEstimateSeconds`.
- **Tempo real:** soma das durações dos lançamentos Clockify iniciados no ano
  analisado e que possuem a tag exata `Dev`. A configuração
  `CLOCKIFY_DEV_TAG` permite alterar o nome da tag sem mudar o código.
- **Relacionamento:** chave Jira encontrada na descrição ou no nome da Task do
  Clockify.
- **Tabela de relação:** cada view possui uma tabela `tickets_with_clockify`
  com uma linha por ticket Jira que tem pelo menos um lançamento Clockify
  mapeado. As views de Bugs e Adaptativas não são consolidadas. A tabela mantém
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
- **Mês:** mês de criação do ticket no Jira. O tempo de todos os lançamentos
  Dev relacionados ao ticket é agregado antes da média mensal.
- **Média real:** média de `spent_hours` entre os tickets concluídos que possuem
  pelo menos um lançamento relacionado. A cobertura é exibida separadamente
  para não confundir ausência de apontamento com zero horas. Como a JQL exige
  estimativa, `coverage_pct` representa tickets com lançamento Dev dividido por
  tickets concluídos elegíveis na consulta do período.
- **Lançamento com várias chaves:** o tempo é dividido igualmente entre as
  chaves reconhecidas, evitando duplicar horas.

O indicador principal para a OKR é `avg_actual_hours` por mês, usando a mesma
regra Clockify Dev. O snapshot mantém uma view independente para cada tipo:

- `views.bug`: somente Bugs concluídos;
- `views.adaptativa`: somente Adaptativas concluídas.

Dentro de cada view, os cards comparam duas coortes consolidadas por ticket:

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

O arquivo gerado contém a definição da métrica e, dentro de cada view, os
tickets, lançamentos normalizados, relacionamentos e médias mensais. A camada
visual alterna entre os tipos em `view/`.

## Automação e publicação com GitHub Actions

O workflow `.github/workflows/publish-okr.yml` executa o pipeline toda sexta-feira
às 07:00 em `America/Sao_Paulo` e também pode ser iniciado manualmente em
**Actions → Atualizar e publicar OKR → Run workflow**. O snapshot gerado é
publicado como `outputs/latest.json` junto da view no GitHub Pages; ele não é
gravado no histórico do repositório.

Na primeira configuração do repositório:

1. Em **Settings → Pages**, selecione **GitHub Actions** como fonte de build e
   publicação.
2. Em **Settings → Secrets and variables → Actions**, cadastre os secrets
   `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`, `CLOCKIFY_API_KEY` e
   `CLOCKIFY_WORKSPACE_ID`.
3. Execute o workflow manualmente para validar a primeira publicação.

A URL normalmente será `https://<owner>.github.io/<repository>/view/`. O site
carrega sempre o último snapshot publicado, mesmo entre duas execuções semanais.

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

## Atualização rápida do IP de administração da EC2

O script `scripts/update_ec2_ip.sh` descobre o IPv4 público atual e altera a
regra existente do Security Group. Ele não cria uma regra nova a cada troca de
rede e, por padrão, executa apenas uma simulação.

Pré-requisito: AWS CLI v2 instalada e um perfil com acesso à conta AWS. Valide
antes de executar o script:

```bash
aws --version
aws sts get-caller-identity --region sa-east-1
```

Inicialmente, informe o Security Group e valide a simulação:

```bash
./scripts/update_ec2_ip.sh \
  --security-group-id sg-xxxxxxxx \
  --port 32
```

Se o Security Group da instância tiver mais de uma regra para essa porta, o
script aborta para evitar alteração acidental. Depois de confirmar a saída,
aplique a troca:

```bash
./scripts/update_ec2_ip.sh \
  --security-group-id sg-xxxxxxxx \
  --port 32 \
  --apply
```

Também é possível informar a instância e deixar o script descobrir o Security
Group, desde que ela tenha apenas um Security Group associado:

```bash
./scripts/update_ec2_ip.sh \
  --instance-id i-xxxxxxxx \
  --port 32 \
  --apply
```

O script usa a região `sa-east-1` por padrão; altere com `--region` ou pela
variável `AWS_REGION`. A credencial e o perfil são os configurados para a AWS
CLI (`AWS_PROFILE`, se necessário).
