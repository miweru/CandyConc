# Measure lexical diversity

Lexical diversity describes how varied the vocabulary of a text collection
is: how many different word forms (types) it uses for its number of word
tokens. This guide compares the lexical diversity of two groups of documents
in the interface and computes it for a whole corpus over the HTTP API.

## Before you begin

- Two groups defined by metadata values or saved subcorpora, for the
  comparison in the interface.

## Compare two groups

The lexical diversity of two groups is part of the contrast view.

1. Search for any word, for example `freedom`.
2. Click the tab **Contrast**.
3. Under **GROUP A (TARGET)** and **GROUP B (REFERENCE)**, choose the two
   groups, for example **party** with **Republican** and **party** with
   **Democratic**.
4. Click **Compute contrast**.

The card **Lexical diversity** above the contrast table shows, for each
group:

| Measure | party = Republican | party = Democratic |
| --- | --- | --- |
| TTR | 0.063 | 0.059 |
| STTR | 0.465 | 0.442 |
| Guiraud R | 26.49 | 24.93 |
| Tokens (N) | 174,284 | 180,221 |
| Types (V) | 11,059 | 10,582 |

These are the values of the English sample corpus. The measures count word
tokens only, without punctuation, so N is smaller than the token count of the
scope. They do not depend on the searched word.

TTR, the number of types divided by the number of tokens, falls as a text
grows longer, so it compares groups of about the same size only. STTR averages
the TTR over windows of 1,000 tokens and compares groups of different size.
The card says so in its note. **Refresh** computes the values again.

```{figure} ../../_static/screenshots/lexical-diversity-party.png
:alt: Card Lexical diversity for party = Republican and party = Democratic with TTR 0.063 and 0.059, STTR 0.465 and 0.442, Guiraud R 26.49 and 24.93, tokens 174,284 and 180,221, and types 11,059 and 10,582.
:width: 100%

The card **Lexical diversity** of the Contrast tab. The note above the table names STTR as the measure for groups of different size.
```

## Compute the diversity of a whole corpus

The interface shows lexical diversity for two groups. For a whole corpus,
request it over the HTTP API. With CandyConc running on port 8010:

```bash
curl -s "http://127.0.0.1:8010/api/v1/analysis/lexical-diversity?corpus=sotu_en" -H "Authorization: Bearer TOKEN"
```

Replace `TOKEN` with a token, see [Use the HTTP API](../automate/use-the-http-api.md).
The response contains `ttr`, `sttr`, `guiraud`, `n_tokens`, and `n_types`.
For the English sample corpus, `n_tokens` is 354,505, `n_types` 14,805, and
`sttr` 0.453.

## Result

You can compare the vocabulary of two groups with measures that fit their
sizes. The formulas and the effect of text length are described in
[Lexical diversity](../../methods/lexical-diversity.md).
