# Dashboard da gestão à vista — etapa posterior

O dashboard é um snapshot HTML autocontido, sem Power BI, servido diretamente
do PostgreSQL por meio das funções da fase 3. Ele não faz parte da fase 4 de
transformação e carga.

## Gerar ou atualizar

Após uma carga bem-sucedida do ETL:

```bash
./.venv/bin/python dashboard/build_dashboard.py
```

Depois empacote o `artifact.json` como HTML:

```bash
npm run report:deliver -- \
  --input dashboard/artifact.json \
  --output dashboard/gestao_a_vista.html
```

Abra [gestao_a_vista.html](gestao_a_vista.html) localmente. O arquivo não
depende de servidor, CDN ou acesso ao banco depois de gerado.

## Conteúdo

- KPIs de horas Clockify e eficiência Jira;
- horas por sprint, tag e squad;
- eficiência por sprint;
- tabela de horas por tag × sprint;
- filtros de sprint, tag, squad e foco;
- definições e limitações da totalização no próprio painel.

O snapshot exclui atribuições de sprint ambíguas por padrão e deve ser
regenerado após cada atualização do PostgreSQL. O total de horas não é
recalculado a partir das tabelas de relacionamento.
