# Resumo do Projeto — Dados de Produtividade (Jira + Clockify + PostgreSQL)

> Documento de contexto consolidado após a decisão de abandonar o Power BI.
> O produto desta etapa é uma camada de dados no PostgreSQL, alimentada por
> funções Python e consultas SQL. As referências ao Power BI abaixo descrevem
> apenas decisões históricas e não fazem parte do runtime atual.

---

## 1. Objetivo do projeto

Camada de dados de produtividade para equipe de 40 pessoas (Analistas de
Requisitos e Desenvolvedores), 6 squads, sprints quinzenais. Fontes: Jira
(tickets/sprints) e Clockify (apontamento de horas). A primeira entrega será o
PostgreSQL com tabelas relacionadas e consultas de métricas; uma interface de
gestão à vista será definida posteriormente.

---

## 2. Arquitetura anterior (legado)

**Antes:** Power Query (M) fazia todas as chamadas de API diretamente,
inclusive extrações pesadas (changelog do Jira por ticket, um a um).

**Motivo da mudança:** a extração de changelog por ticket (necessária para
Eficiência da Sprint) fazia uma chamada de API por ticket, sequencialmente,
dentro do Power Query. Com volume real de tickets, isso travou o Power BI
Desktop por mais de 12h, exigindo encerramento forçado e corrompendo o
arquivo.

**Arquitetura que será descontinuada:**
```
Jira API  ─┐
           ├─→ ETL em Python (requisições assíncronas/paralelas,
Clockify API ┘   com retry, rate limiting e cache incremental)
                        │
                        ▼
                  PostgreSQL (tabelas já no formato do modelo estrela)
                        │
                        ▼
                    Power BI (componente removido do novo escopo)
```

**Lições preservadas dessa arquitetura:**
- Extração pesada (changelog) roda fora do Power BI, com controle de
  paralelismo e log de erros
- Possibilidade de carga incremental (só buscar o que mudou desde a última
  execução, em vez de tudo de novo toda vez)
- O processamento pesado deve ficar fora de ferramentas de visualização
- Falha na extração não corrompe mais o arquivo do painel

### 2.1. Arquitetura vigente após a Fase 1

```text
Jira API ───────┐
                ├─→ ETL Python ─→ PostgreSQL ─→ views/consultas/funções
Clockify API ───┘
```

Não haverá chamadas de API a partir de ferramentas de visualização nem
medidas DAX. O agendamento e o mecanismo de entrega das consultas serão
definidos depois da camada de dados estar validada.

---

## 3. Catálogo de métricas (primeira versão)

| KPI | Definição | Fonte |
|---|---|---|
| Horas Engenharia | Soma de horas em tags do grupo Engenharia | Clockify |
| Horas Dev | Soma de horas na tag `Dev` | Clockify |
| % Apoio à Entrega | % das Horas Engenharia em tags `QA`/`Dev-Check` | Clockify |
| % Horas Foco | % das horas em tags cujo Papel bate com o Papel real do colaborador | Clockify |
| Tickets Concluídos | Contagem de tickets no status agrupado "Concluído" | Jira |
| % Eficiência da Sprint | % dos tickets planejados no início da sprint que foram concluídos | Jira |

**TMR (Tempo Médio de Resolução):** adiado, fora do escopo desta versão —
ainda não definido se a fonte será Clockify ou Jira.

---

## 4. Regras de negócio e decisões (conhecimento que não vem de API)

### 4.1 Tags do Clockify → Grupo
| Grupo | Tags |
|---|---|
| Engenharia | Análise e Levantamento de Requisitos, QA, Dev, Dev-Check |
| Dev | Dev |
| Apoio à Entrega | QA, Dev-Check |

### 4.2 Status do Jira → Status Agrupado
Tabela **global** (não por squad — validado que os nomes de status têm o
mesmo significado em todas as squads).

**Concluído** engloba: `Concluído`, `Inválido`, `Enviado para evolução`,
`Showcase`. Atenção: `Ready 4 Showcase` é DIFERENTE de `Showcase` — o primeiro
ainda não conta como concluído (é etapa anterior).

Todos os demais status (`Backlog`, `Em andamento`, `Dev`, `QA`,
`Ready 4 Dev`, `Ready 4 Devcheck`, `Ready 4 QA`, `Pendência Interna`,
`Pendencia Interna` — variação sem acento nos dados de origem, `Pendencia
Externa`, `On Hold`, `Travado`, `Aguardando início`, `Tarefas pendentes`,
`Devcheck`, `Pronto para Desenvolvimento`) = **Não Concluído**.

### 4.3 Squad Clockify ↔ Squad Jira (de-para manual)
Squad e produto são conceitos diferentes — squads homônimas podem pertencer
a produtos diferentes (ver linha "Operadoras").

| Squad_Jira (bruto) | Squad_Padrao |
|---|---|
| Sem Squad | Sem Squad *(mantido separado — não unificar com Transversal)* |
| ZGT - Evolução | ZGT - Evolução |
| ZGT - Novas Operadoras | ZGT - Operadoras |
| ZGT - Rede D'or | ZGT - RDSL |
| ZGT - Sustentação | ZGT - Sustentação |
| Operadoras | Operadoras *(produto Zero Glosa, diferente de ZGT - Operadoras)* |
| Núcleo | Núcleo |
| Rede D'Or - Zero Glosa | RDSL |
| Analytics | Descontinuada *(squad extinta, mantida p/ tickets históricos)* |
| Monitoramento SRE | Monitoramento |
| Frente Compartilhada (PrevOps) | Descontinuada *(squad extinta)* |
| *(nenhum ticket — só existe no Clockify)* | Transversal |

**Ruído identificado:** squad `SWAT` no Jira — 1 ticket, status Backlog,
confirmado como ruído/teste. Excluir na extração.

### 4.4 Papel e Squad do colaborador (Clockify)
Estruturados como **grupos** do Clockify, convenção de nome:
`Papel - X` (ex: `Papel - Coordenador`, `Papel - Desenvolvedor`, `Papel - SRE`)
`Squad - X` (ex: `Squad - ZGT - Evolução`)

Papéis sem squad própria (Coordenação, Squad Leader, Tribe Leader, Product
Designer) recebem o rótulo explícito **"Transversal"** em vez de ficarem
nulos (evita "(Em branco)" poluindo slicers/visuais, e some silenciosamente
de filtros).

### 4.5 Horas Foco — lógica de cálculo
Tabela `Dim_Tags_Papel` (Papel, Foco, Tag_Clockify — 45 linhas) tem **tags
repetidas para papéis diferentes** (ex: uma tag genérica pode ser "dentro do
foco" pra vários Papéis ao mesmo tempo). Isso quebra relacionamento 1:N
simples no Power BI.

**Solução:** calcular o flag Dentro/Fora do Foco na própria camada de ETL
(antes até era Power Query, agora será Python), cruzando o par
(Papel_Colaborador, Tag_Clockify) contra a Dim_Tags_Papel — se a combinação
existir, é "Dentro do Foco"; se não existir, "Fora do Foco". Colaborador sem
Papel mapeado = "Sem Papel Definido" (excluído do cálculo do % Horas Foco,
tanto do numerador quanto do denominador).

A coluna **Foco** (subtipo de atividade) é dimensão de detalhamento, não
entra na fórmula do % Horas Foco.

### 4.6 Eficiência da Sprint — lógica de "planejado no início"
Não dá pra saber isso só pelo estado atual do ticket — exige o **changelog**
(histórico de mudanças) para saber quando o ticket entrou em cada sprint.

**Regra final:**
```
Data Entrada Sprint = 
    SE existe mudança de campo "Sprint" no changelog mencionando essa sprint
        → data dessa mudança
    SENÃO (ticket nasceu direto na sprint, nunca foi movido)
        → Data de Criação do ticket

Planejado no Início = SE Data Entrada Sprint <= Sprint Data Início
                       ENTÃO "Planejado"
                       SENÃO "Adicionado Depois"
```

Escopo: considerar somente sprints com `sprint_start > 01/01/2026`, iniciadas
até o momento atual e com estado `ACTIVE` ou `CLOSED`. Sprints futuras,
anteriores ou sem metadados suficientes ficam fora do modelo analítico.

---

## 5. Padrões de API validados (continuam válidos na migração para Python)

### 5.1 Clockify

| Necessidade | Endpoint | Observações |
|---|---|---|
| Workspace ID | `GET https://api.clockify.me/api/v1/workspaces` | Primeiro da lista, `{0}[id]` |
| Usuários | `GET /v1/workspaces/{id}/users` | Campos: `id`, `name`, `email` |
| Grupos (Papel/Squad) | `GET /v1/workspaces/{id}/user-groups` | Campos: `id`, `name`, `userIds` (lista) |
| Lançamentos (Detailed Report) | `POST https://reports.api.clockify.me/v1/workspaces/{id}/reports/detailed` | **Domínio diferente** do resto da API (`reports.api.` em vez de `api.`). É POST com corpo JSON, não GET |

**Pegadinhas confirmadas:**
- O ID do lançamento no Detailed Report vem no campo **`_id`** (com
  underscore), não `id` — isso quebrou silenciosamente (retornou `null`) até
  ser corrigido
- **Duração**: não confiar em parsing manual do formato ISO 8601 (`"PTnS"`)
  — o formato pode variar. Solução robusta: extrair `timeInterval.start` e
  `timeInterval.end` (ambos com timezone) e calcular `Fim - Início`
  diretamente
- Entradas ainda "rodando" (sem hora de término) vêm com `end = null` —
  filtrar antes de calcular duração
- Um lançamento pode ter **até 2 tags simultâneas** (raro, mas acontece) —
  qualquer agregação por tag precisa considerar isso (uma hora pode contar
  em 2 grupos diferentes ao mesmo tempo, isso é esperado/correto)
- Corpo da requisição do Detailed Report:
  ```json
  {
    "dateRangeStart": "2026-01-01T00:00:00.000Z",
    "dateRangeEnd": "2026-12-31T23:59:59.000Z",
    "detailedFilter": { "page": 1, "pageSize": 1000 }
  }
  ```
  Paginar incrementando `page` até a resposta vir vazia.

### 5.2 Jira

| Necessidade | Endpoint | Observações |
|---|---|---|
| Busca de tickets (JQL) | `https://{dominio}.atlassian.net/rest/api/3/search/jql` | Endpoint NOVO — o antigo `/rest/api/3/search` está sendo descontinuado |
| Changelog por ticket | `GET /rest/api/3/issue/{key}/changelog` | Endpoint estável, funciona, mas é 1 chamada por ticket |
| Changelog em lote | `POST /rest/api/3/changelog/bulkfetch` | **NÃO funcionou nesta instância** — retornou 415 (Unsupported Media Type) mesmo testando com header `X-ExperimentalApi: opt-in`. Não usar; ir direto para changelog por ticket |

**Pegadinhas confirmadas:**
- **Paginação do `/search/jql`**: via `nextPageToken` (token encadeado),
  **não** por `startAt` como nas versões antigas da API
- **`expand=changelog` não é suportado** no endpoint `/search/jql` — retorna
  lista de issues vazia silenciosamente (sem erro claro) em vez de recusar o
  parâmetro
- Campos customizados (Squad, Sprint) têm ID específico da instância (ex:
  `customfield_10431` para Squad, `customfield_10010` para Sprint) — varia
  por ambiente, precisa ser levantado manualmente
- Squad (campo tipo "select") vem como `{value: "..."}` — precisa extrair
  `.value`
- **Sprint é uma LISTA**, não um valor único — um ticket carrega o histórico
  de todas as sprints pelas quais passou. Isso gera potencialmente mais de
  uma linha por ticket na tabela fato (uma por sprint)
- Datas vêm em texto com timezone embutido
  (`"2025-01-15T14:30:00.000-0300"`) — truncar antes de fazer parsing (pegar
  só os 19 primeiros caracteres) evita erro de conversão
- `resolutiondate` vem `null` para tickets ainda não resolvidos — tratar
  antes de converter tipo
- No changelog, a mudança do campo Sprint aparece com `field = "Sprint"` e
  `toString` contendo o(s) nome(s) da(s) sprint(s) — **pode conter mais de
  uma sprint no mesmo registro** se o ticket foi movido em lote, então o
  cruzamento com o nome da sprint precisa ser por "contém o texto", não
  igualdade exata
- Ticket que **nunca foi movido de sprint** (nasceu já na sprint em que
  está) **não gera entrada no changelog** para esse campo — é preciso
  fallback para a data de criação do ticket nesses casos

### 5.3 Autenticação
- Clockify: header `X-Api-Key`
- Jira: Basic Auth (`Authorization: Basic <base64 de email:api_token>`)
- **Nunca deixar credenciais em texto puro em nenhum lugar versionado ou
  compartilhado** — no projeto Python, usar variáveis de ambiente (`.env`,
  fora do controle de versão) ou um cofre de segredos
- **Lição aprendida:** durante o desenvolvimento, credenciais reais foram
  coladas em texto puro por engano mais de uma vez (chave do Clockify e
  token do Jira). Ambas precisam ser regeneradas antes de ir para produção,
  por precaução

---

## 6. Modelo de dados implementado no Postgres (schema v2)

```
Dim_Colaborador   (UserID, Nome, Papel, SquadID)
Dim_Squad         (SquadID, Nome)
Dim_Squad_Alias   (Origem, Nome_Bruto, SquadID)
Dim_Tag           (TagID, Nome_Original, Nome_Normalizado)
Dim_Papel_Tag     (Papel, Foco, TagID)
Dim_Calendario    (Data, Ano, Mês Número, Mês Nome, Dia da Semana, Dia Útil,
                   Dia do Mês)
Dim_Status         (Status_Original, Status_Agrupado)
Dim_Sprint        (SprintID, Nome, Data Início, Data Fim, Estado)
Dim_Ticket_Jira   (Chave_Ticket, Título, Status, Projeto, Squad_Jira,
                   Criado, Resolvido, Atualizado)

Fato_Clockify_Entry (EntryID, UserID, Projeto, Tarefa, Descrição,
                     Início, Fim, Data, Segundos)
                     -- 1 linha por lançamento

Bridge_Entry_Tag   (EntryID, TagID, Foco_Flag)
                   -- 1 linha por lançamento POR TAG

Bridge_Entry_Issue (EntryID, Chave_Ticket, Método)
Fato_Ticket_Sprint (Chave_Ticket, SprintID, Data Entrada,
                    Planejado no Início)
Bridge_Entry_Sprint (EntryID, SprintID, Status Atribuição, Motivo)

Jira_Sprint_Changelog (ID, Chave_Ticket, SprintID, Tipo, Alterado Em,
                       Coletado Em, Status Processamento, Erro)
```

**Relacionamentos devem ser relacionamentos reais do PostgreSQL**, com chaves
estrangeiras, índices e constraints únicas. A camada de consultas deve expor
o total geral no grão de lançamento e os detalhamentos de tag/sprint por meio
das tabelas de relacionamento.

---

## 7. Camada de métricas

A camada foi implementada como views SQL e funções Python parametrizadas em
`database/migrations/phase3.py` e `queries/metrics.py`. O conjunto atende:
- `Horas Engenharia`, `Horas Dev`, `Horas Apoio à Entrega`, `% Apoio à Entrega`
- `Horas Dentro do Foco`, `Horas Total para Foco`, `% Horas Foco`
- `Tickets Concluídos`, `Tickets Planejados no Início`,
  `Tickets Planejados Concluídos`, `% Eficiência da Sprint`
- total de horas sem duplicação;
- horas por tag;
- horas por squad;
- horas por sprint;
- horas por tag e sprint com filtros combináveis.

As funções públicas são `total_hours`, `hours_by_collaborator`,
`hours_by_tag`, `hours_by_squad`, `hours_by_sprint`,
`hours_by_tag_and_sprint`, `clockify_kpis`, `ticket_metrics` e
`tickets_by_sprint`. O total geral soma somente a fato de lançamentos; nos
agrupamentos por tag, a duração é atribuída integralmente a cada tag do
lançamento. Filtros de tag e foco também restringem a dimensão exibida, o que
permite consultas como “Dev na Sprint 10” sem trazer outras tags.

### 7.1 Gestão à vista — etapa posterior

O dashboard local está em `dashboard/gestao_a_vista.html`. Ele é um artefato
posterior, gerado por `dashboard/build_dashboard.py` a partir das consultas
da fase 3. Não faz parte do runtime da transformação/carga e é um snapshot
autocontido que precisa ser regenerado após uma nova carga do ETL.

## 8. Transformação e carga — fase 4

A fase 4 consolida a materialização dos dados no PostgreSQL. A carga é
idempotente para os registros recarregados, mantém os relacionamentos reais
entre fatos, dimensões e bridges, e registra a execução em `etl_run_log`.

Antes de finalizar uma execução bem-sucedida, o pipeline valida órfãos,
escopo de sprint, durações, intervalos e estados de atribuição. Uma falha de
qualidade impede que a execução seja reportada como concluída.

## 9. Validação e aceite — fase 5

A suíte `etl/acceptance.py` foi executada sobre a carga já realizada das APIs.
Ela verifica presença e versão do modelo, grão das tabelas e views,
integridade referencial, escopo de sprints, histórico do changelog,
reconciliação das horas e classificação dos status Jira.

O resultado atual foi **aceito**: 32 verificações aprovadas, sem avisos ou
falhas. O modelo contém 20.299 lançamentos Clockify, 5.312 tickets Jira e 16
sprints. O total de 21.429,2875 horas da fato foi reconciliado com a função
`total_hours()` e não há relacionamentos históricos órfãos.

Durante o aceite foram materializados 57 relacionamentos ticket × sprint
identificados no changelog, mas ausentes da fato histórica, e foram incluídos
os status `Pendência Externa`, `Em Análise` e `Ready 4 Correção` no domínio de
status não concluído. O relatório completo está em
`validation/acceptance_report.md` e sua versão estruturada em
`validation/acceptance_report.json`.

Pontos funcionais para acompanhamento: existem 22 atribuições ambíguas de
sprint, excluídas por padrão das métricas por sprint, e 1.619 lançamentos sem
tag, que continuam no total geral, mas não aparecem nos agrupamentos por tag.

## 10. Operacionalização — fase 6

A fase 6 foi implementada como um baseline local para testar a operação antes
da migração para a infraestrutura corporativa. O pacote
`operationalization/` fornece:

- runner do ETL incremental com retry opcional;
- lock de arquivo para impedir execuções locais simultâneas;
- aceite automático após uma carga bem-sucedida;
- consulta das últimas execuções em `etl_run_log`;
- healthcheck de conexão e tabelas essenciais do PostgreSQL;
- instruções de agendamento local temporário em
  `operationalization/README.md`.

Comandos principais:

```bash
./.venv/bin/python -m operationalization run
./.venv/bin/python -m operationalization status
./.venv/bin/python -m operationalization healthcheck
```

Essa solução não revisa credenciais e não tenta antecipar a infraestrutura
definitiva. Na migração, o lock local será substituído por controle de
concorrência do scheduler/Kubernetes; retries, logs, métricas, alertas,
retenção e armazenamento serão centralizados na arquitetura AWS.

## 11. Publicação AWS EC2 — etapa 1

A preparação inicial para a AWS foi recriada para uma instância Ubuntu na EC2.
O ETL aceita a variável genérica `DATABASE_URL` e mantém as variáveis
`POSTGRES_*` para execução local ou no host. O `Dockerfile` permanece genérico
para execução containerizada, enquanto o baseline da EC2 executa o ETL em um
ambiente virtual Python e o Metabase em Docker.

A topologia definida para o teste é:

- PostgreSQL em container local, com porta publicada somente em `127.0.0.1`;
- ETL Python executado por cron ou systemd timer na EC2;
- Metabase em container Docker, com a porta `3000` como único acesso público;
- banco lógico `metabasedb` separado para os metadados do Metabase;
- encerramento explícito do engine SQLAlchemy ao terminar o processo.

As instruções estão em `AWS_EC2_PUBLICACAO.md`, com o compose em
`deploy/ec2/docker-compose.yml`. O desenho poderá evoluir para RDS, Secrets
Manager e CloudWatch sem alterar o modelo analítico.

---

## 12. Lições aprendidas (para não repetir)

1. **Chamadas de API pesadas (1 por ticket, para changelog) devem rodar no
   ETL Python**, com controle de paralelismo, timeout e retry.
2. **Testar sempre com amostra pequena antes de rodar o volume completo** —
   isso já vinha sendo seguido e ajudou a pegar vários erros de estrutura
   (nomes de campo, formato de data) antes de gastar tempo/chamadas com
   tudo
3. **Campos obrigatórios de API devem ser validados explicitamente** para não
   transformar IDs e relacionamentos ausentes em `null` silenciosamente.
4. **Nunca usar `null` como chave de relacionamento** — causou problema
   real na `Dim_Squad` (linha "Transversal")
5. **Guardar toda credencial fora do código-fonte desde o primeiro
   protótipo**, não só antes de "ir para produção" — no meio do
   desenvolvimento é fácil esquecer e colar token em texto puro em algum
   lugar (aconteceu 2x neste projeto)
6. **Validar existência de endpoints "novos"/experimentais com um teste
   pequeno antes de desenhar a lógica completa em cima deles** — economizou
   retrabalho no caso do `expand=changelog` e do `changelog/bulkfetch`, que
   não funcionaram e exigiram pivotar para o endpoint por ticket

---

## 13. Próximos passos

1. Formalizar a aprovação funcional dos KPIs com amostras revisadas pelos
   responsáveis de negócio
2. Subir PostgreSQL e Metabase na EC2 e executar uma carga controlada do ETL
3. Testar o runner local com uma execução controlada e um caso de falha para
   confirmar retry, lock e registro em `etl_run_log`
4. Definir o desenho AWS/Kubernetes de jobs, observabilidade, alertas,
   retenção e escala
5. Retomar o dashboard como etapa posterior, agora sobre a camada aceita
