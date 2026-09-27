# Word sketches

A word sketch lists the collocates of a word by grammatical relation: the
adjectives that modify a noun, the verbs that take it as object, and so on.
The name and the idea come from the Sketch Engine (Kilgarriff et al. 2004).
CandyConc derives the relations directly from the dependency relations in the
index. It does not use a sketch grammar of queries over part-of-speech
patterns, as the Sketch Engine does.

## Requirements

The corpus must have dependency relations. The import adds them by default
when the pipeline has a dependency parser, as the trained spaCy pipelines
have, and leaves them out with `--no-deps`. Without them, the word sketch
view is unavailable. A VRT import that adopts the annotation of the source
has no dependency relations.

## What is counted

**Node.** The exact spelling you enter. If that spelling does not occur, its
lowercase form. The node is not a case-folded class: *Tea* and *tea* have
different sketches.

**Relations.** A row belongs to a relation label of the annotation pipeline.
Two directions are distinguished:

- `rel`: the node is the head, and the collocate is a dependent with the
  relation `rel`, for example `amod` for an adjective modifying the node.
- `rel_rev`: the node is the dependent, and the collocate is its head, for
  example `dobj_rev` for a verb whose direct object is the node.

The relations `ROOT`, `punct`, `case`, and `pnc` are not shown. The
interface names each relation by a gloss in the interface language, chosen
by the label scheme of the corpus: the ClearNLP scheme of the English spaCy
pipelines and the TIGER scheme of the German ones. `amod` is shown as
**has adjectival modifier**, `dobj_rev` as **direct object of**, and the
TIGER label `sb_rev` as **subject of**. Next to the gloss, each table shows
the relation as the dependency search writes it: `>amod` for `amod` and
`<dobj` for `dobj_rev`. A label that the scheme does not list is shown as
its code. The API returns the code as the key of each
relation and the gloss in its field `label`, in the language of the
`Accept-Language` header.

**Counts.** For one relation and one collocate:

- $O$ is the number of pairs of node and collocate in that relation,
- $f_1$ is the corpus frequency of the node form,
- $f_2$ is the corpus frequency of the collocate form,
- $N$ is the size of the corpus in tokens.

Only collocates that are word tokens are listed. Forms starting with `@` or
`#` are excluded. A relation keeps the node itself as a collocate, ignoring
case, only when it has no other eligible partner. A row needs at least 3
pairs by default.

## Measures

| Column | Formula |
| --- | --- |
| `f` | $O$ |
| `f2` | $f_2$ |
| `chi2_cell` | $(O - E)^2 / E$ with $E = f_1 f_2 / N$ |
| `t` | $(O - E) / \sqrt{O}$ |
| `ll` | G² over the table $[[O, f_1 - O], [f_2 - O, N - f_1 - f_2 + O]]$ |
| `dice` | $2 O / (f_1 + f_2)$ |
| `logdice` | $14 + \log_2 \bigl(2 O / (f_1 + f_2)\bigr)$ |

logDice follows the definition of Rychlý (2008) with the corpus frequencies of
the two words, and it is the default sort order.

## Assumptions and interpretation

- The table places a count of pairs next to marginal counts of tokens. It is
  an approximation, not a contingency table of one event space. G² and the
  t-score of a word sketch are therefore not comparable with those of the
  window-based [collocation analysis](association-measures.md). logDice is
  the measure to compare across relations and nodes.
- The relations are the output of a statistical parser. Their accuracy
  depends on the pipeline and the text type. Check surprising rows in the
  concordance.
- A collocate can appear in a relation with the node itself, for example in
  coordinations such as *green tea, green tea*.

## Example

The word sketch of *tea* in the synthetic tea corpus, imported with
`en_core_web_sm` and `--enable-deps`, with the minimum set to 1 pair. The
node form *tea* occurs 13 times ($f_1 = 13$), the corpus has $N = 162$
tokens. To include the pairs below the interface minimum of 3, request this
example through the [HTTP API](../guides/automate/use-the-http-api.md):

```bash
curl -s -H 'Content-Type: application/json' -H 'Accept-Language: en' \
  -d '{"corpus":"tea","term":"tea","min_freq":1}' \
  http://127.0.0.1:8010/api/v1/analysis/wordsketch
```

Replace `tea` in the `corpus` field with the name registered for your imported
tea corpus, and use the port printed when CandyConc starts. The response
contains the rows under `sketches` and the counting settings under `method`.

```{example-table} wordsketch-tea
```

Recomputed by hand for `amod` *green*: $O = 6$, $f_2 = 6$, so
$\text{logDice} = 14 + \log_2 \bigl(12 / (13 + 6)\bigr) = 13.3370$ and G²
over $[[6, 7], [0, 149]]$ is 33.380. The relation `appos_rev` with *tea*
itself comes from the repetition *Green tea, green tea, always green tea*.

A row opens the same pairs as a dependency search in the concordance. In the
English sample corpus, the word sketch of *freedom* lists *political* under
`amod` with 5 pairs, and `[word=freedom] >amod [word=political]` finds 5
hits. The search finds heads, so a head with two dependents of the partner in
the relation is two pairs and one line. See
[Query language](../reference/query-language.md#dependency-relations) and
[From numbers to lines](../concepts/from-numbers-to-lines.md#from-a-word-sketch-to-the-lines).

## Related pages

- [Make a word sketch](../guides/count-and-measure/word-sketches.md)
- [Association measures](association-measures.md)
