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

No GitHub Pages, o workflow publica o snapshot atual como
`outputs/latest.json`, e a view o carrega automaticamente. O endereço da view
será semelhante a:

```text
https://<owner>.github.io/<repository>/view/
```
