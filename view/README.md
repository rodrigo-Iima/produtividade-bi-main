# View da OKR

A view lê o snapshot gerado pelo pipeline. Depois de executar
`scripts/run_pipeline.py`, sirva
a raiz do projeto localmente:

```bash
python -m http.server 8000
```

Abra [http://localhost:8000/view/](http://localhost:8000/view/). Por padrão,
a view procura o snapshot da data atual em `outputs/okr_YYYY-MM-DD.json`.

Para consultar um snapshot específico:

```text
http://localhost:8000/view/?data=../outputs/okr_2026-07-24.json
```

No Vercel, a view usa automaticamente `/api/snapshot`. O endpoint é alimentado
pelo Cron semanal e não depende de arquivos locais.
