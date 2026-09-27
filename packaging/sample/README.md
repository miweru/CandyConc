# Sample data for tests and first steps

`synthetic_en.csv` holds four English sentences written for CandyConc's tests
and first steps. They are synthetic, not taken from any source, and carry no
linguistic findings. Columns: `doc_id`, `text`, `genre` (document metadata).

```bash
candy import --input synthetic_en.csv --input-format csv --id-column doc_id \
  --meta-columns genre --spacy-model blank:en --output ~/.candyconc/corpora/sample_en
```
