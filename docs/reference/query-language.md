# Query language

CandyConc accepts two kinds of queries in the search bar and in the `term`
parameter of the HTTP API:

- **Plain search**, for words, wildcards, phrases, and simple combinations.
  It ignores case.
- **The CandyConc query language**, a CQP-style language with token
  conditions in square brackets, sequences, repetition, sentence and document
  scope, and metadata conditions. It respects case unless you add `%c`.

This page describes both as they are implemented. Every example on this page was run
on one of the sample corpora, and the result under it is the recorded hit
count and document count. How the examples are checked is described in
[Documentation maintenance](../contribute/documentation.md). For the concepts
behind hits and counts, see [Queries and hits](../concepts/queries-and-hits.md).

The examples use three corpora:

- the **State of the Union sample corpus**: 65 addresses from 1945 to 2006,
  403,284 tokens, imported with `--language en` as in
  [First results](../get-started/first-results.md), which annotates with
  `en_core_web_md` including dependency relations, metadata fields
  `president`, `party`, `year`, `decade`, `date`, and `title`,
- the **German DTA sample corpus**: 30 texts from the Deutsches Textarchiv,
  1800 to 1899, 624,227 tokens, annotated with `de_core_news_md` including
  dependency relations, metadata fields `author`, `title`, `year`, `decade`,
  `genre`, `subgenre`, and `url`,
- the **synthetic tea corpus**: 8 short documents written for the worked
  examples, 162 tokens, see [Worked examples](../methods/worked-examples.md).

Part-of-speech values in the examples are Universal Dependencies tags, which
is what a spaCy import stores. See
[Languages and annotation](../concepts/languages-and-annotation.md).

## How CandyConc tells the two apart

An input is read as the query language when

- it starts with `cql:`, or
- it starts with a token condition in square brackets that contains a quoted
  value or is the empty condition `[]`, or
- it starts with `within(` or `where(`, or with the keyword `within` or
  `where` followed by `<`, `(`, `[`, or a quote, for example `within <s>`.

Everything else is plain search. The words *where* and *within* alone, or
followed by other words, are plain search for these words. `[lemma="freedom"]` is therefore read as the
query language, and `[lemma=freedom]` without quotes is plain search:

```{query-example} cql-bare
```

```{query-example} plain-attr
```

In parameters of analyses, for example the node of a collocation analysis,
write the prefix `cql:` explicitly.

## Plain search

### Words and case

A single word finds all tokens whose word form is equal to it in lowercase.

```{query-example} plain-word
```

```{query-example} plain-word-capital
```

Plain search ignores case by default. The HTTP API accepts
`case_insensitive=false` for a case-sensitive plain search.

### Wildcards

`*` stands for any sequence of characters, including none, and `?` for
exactly one character. The pattern must match the whole word form.

```{query-example} plain-star
```

```{query-example} plain-question
```

### Regular expressions

A pattern between slashes is a regular expression over word forms. It must
match the whole word form and ignores case.

```{query-example} plain-regex
```

Plain search splits its input at parentheses, so a regular expression with a
group such as `/liber(ty|ties)/` is not accepted. Write it with the `~`
operator of the query language instead, as shown in
[Operators](#operators).

### Phrases

Words in double quotes form a phrase: consecutive tokens with these word
forms, compared without regard to case, within one document.

```{query-example} plain-phrase
```

Several words without quotes are not a phrase. The query is rejected, and the
message shows the query-language form of the sequence.

```{query-example} plain-sequence-rejected
```

### AND, OR, NOT

The operators combine sets of token positions. They are written in capital
letters.

- `OR` finds tokens that match either side.
- `AND` finds tokens that match both sides at the same position. It combines
  conditions on one token, for example a word form and a part of speech.
- `NOT` finds every token that does not match, punctuation included.

```{query-example} plain-or
```

```{query-example} plain-and
```

`NOT` binds more strongly than `AND`, and `AND` more strongly than `OR`. Use
parentheses to group.

### NEAR

`A NEAR/n B` finds the tokens of `A` that have a token of `B` within `n`
tokens to the left or right in the same document, and the tokens of `B` that
have a token of `A` within that distance. Both words count as hits.

```{query-example} plain-near
```

### Attribute conditions

`[attribute=value]` without quotes matches the exact value of an attribute.
The attributes are those of the corpus: `word`, `lemma`, `pos`, `morph`, and,
when the corpus has them, `ent` and `rel`. See
[The corpus index](../concepts/corpus-index.md).

```{query-example} plain-attr
```

### Dependency relations

On a corpus with dependency relations, `HEAD >relation DEPENDENT` finds heads
that have a dependent with the given relation, and
`DEPENDENT <relation HEAD` states the same from the other side. Both sides
can be words, which are compared without regard to case, or attribute
conditions. The hit is the head.

```{query-example} plain-dep
```

```{query-example} plain-dep-amod
```

```{query-example} plain-dep-attr
```

The relation names are the labels of the annotation pipeline, for example
`nsubj`, `dobj`, and `amod` for the English pipelines.

## The query language

### Grammar

```text
query       := alternative ( "|" alternative )*
alternative := term+
term        := factor quantifier?
quantifier  := "?" | "*" | "+" | "{" m "}" | "{" m "," n "}" | "{" m ",}" | "{," n "}"
factor      := "[" condition ( "&" condition )* "]"
             | "[]"
             | "(" query ")"
             | "within(" "<s>" "," query ")"
             | "within(" "<doc>" "," query ")"
             | "where(" meta_or "," query ")"
condition   := attribute ( "=" | "!=" | "~" ) value flag?
             | attribute "in" "{" value ( "," value )* "}" flag?
flag        := "%c"
meta_or     := meta_and ( "|" meta_and )*
meta_and    := meta_atom ( "&" meta_atom )*
meta_atom   := "(" meta_or ")" | field ( "=" | "!=" ) meta_value
meta_value  := value | "{" value ( "," value )* "}"
value       := a string in double quotes | a number
```

Inside a string, `\"` is a double quote and `\\` a backslash. Every other
backslash sequence is passed to the regular expression unchanged, so `\.`
matches a literal full stop.

### Token conditions

A token condition in square brackets describes one token. `[]` matches any
token.

```{query-example} cql-word
```

```{query-example} cql-word-capital
```

```{query-example} cql-lemma
```

Several conditions on the same token are joined with `&`:

```{query-example} cql-and
```

```{query-example} cql-rel
```

The attributes are the token attributes of the corpus:

| Attribute | Available |
| --- | --- |
| `word`, `lemma`, `pos`, `morph` | in every corpus |
| `rel` | in corpora imported with dependency relations |
| `ent` | in corpora imported with named entities |

An attribute that the corpus does not have is rejected:

```{query-example} cql-reject-attr
```

A value of `pos` that does not occur in the corpus is rejected, and the
message lists the tags that occur. This catches, for example, an STTS tag on
a corpus with Universal Dependencies tags:

```{query-example} cql-reject-stts
```

```{query-example} de-reject-stts
```

(operators)=
### Operators

| Operator | Meaning |
| --- | --- |
| `=` | The value equals the string. If the string contains an unescaped regular expression character (`. * + ? \| ( ) [ ] { } ^ $`), it is a regular expression, as in CQP. |
| `!=` | The value does not equal the string. The string is compared as it is. A string with an unescaped regular expression character is rejected, because a negated regular expression is not executed. |
| `~` | The value matches the regular expression. |
| `in {…}` | The value equals one of the strings in the set. |

Regular expressions use Python syntax and must match the whole value.
Escape a character with a backslash to match it literally.

```{query-example} cql-eq-regex
```

```{query-example} cql-tilde
```

```{query-example} cql-in
```

`!=` is often used next to other conditions. Here it excludes punctuation
after *freedom*:

```{query-example} cql-neq
```

A regular expression that matches more than 200,000 distinct values or more
than 5,000,000 tokens is rejected when concordance lines are requested. The
limits are set with `CANDYCONC_MAX_REGEX_TYPES` and `CANDYCONC_MAX_REGEX_FREQ`.

### The flag %c

`%c` after a value compares without regard to case. It works with `=`, `!=`,
`in`, and `~`. Case-insensitive comparison uses Unicode lowercase mapping, so
the German *ß* and *ss* stay different.

```{query-example} cql-word-c
```

```{query-example} cql-lemma-c
```

```{query-example} cql-in-c
```

```{query-example} cql-tilde-c
```

With `!=`, `%c` excludes every spelling of the value. The result is the same
as one `!=` condition per spelling, joined with `&`:

```{query-example} cql-neq-c
```

```{query-example} cql-neq-and
```

The flag `%d` of CQP, which ignores diacritics, is rejected. To match variants
with and without a diacritic, write a character class that contains both:

```{query-example} cql-reject-d
```

```{query-example} de-diacritic-class
```

```{query-example} de-diacritic-plain
```

### Sequences

Token conditions written one after the other match consecutive tokens.

```{query-example} cql-adj-noun
```

```{query-example} cql-seq3
```

A hit that covers several tokens is shown whole in the column **NODE** of
the concordance, for example *political freedom*. One token of the hit is its
node: the first token of the pattern that has a fixed word or lemma value,
here *freedom*. The position at the start of the line and the column `pos`
of an export refer to the node. See
[Queries and hits](../concepts/queries-and-hits.md#the-concordance-line).

`[]` is one arbitrary token:

```{query-example} cql-any
```

### Repetition

| Quantifier | Meaning |
| --- | --- |
| `?` | zero or one time |
| `*` | zero or more times |
| `+` | one or more times |
| `{m}` | exactly `m` times |
| `{m,n}` | `m` to `n` times |
| `{m,}` | at least `m` times |
| `{,n}` | zero to `n` times |

```{query-example} cql-gap
```

```{query-example} cql-optional
```

```{query-example} cql-plus
```

```{query-example} cql-range
```

A single repetition count is limited to 256. Nested repetitions are rejected
when they would expand to more than 2,000 token instances, a limit set with
`CQLHPC_MAX_QUANT_EXPANSION`.

```{query-example} cql-reject-repeat
```

### Alternatives and grouping

`|` separates alternatives, and parentheses group:

```{query-example} cql-alt
```

```{query-example} cql-alt-inner
```

### Which hits are counted

Hits do not overlap. The engine takes the longest match that starts at the
leftmost possible position and continues after its end. A pattern with a
wider gap can therefore find fewer hits than a pattern with a narrower gap:

```{query-example} tea-gap-1
```

```{query-example} tea-gap-4
```

[Queries and hits](../concepts/queries-and-hits.md) explains this example.

### Sentence and document scope

A pattern does not cross a sentence boundary unless you ask for it.
`within(<s>, ...)` states the default, and `within(<doc>, ...)` lets a match
span several sentences of one document.

```{query-example} cql-scope-default
```

```{query-example} cql-scope-s
```

```{query-example} cql-scope-doc
```

`<s>` and `<doc>` are the only regions. Other structural regions of CQP, such
as paragraphs, are not part of the index.

### Metadata conditions

`where(condition, query)` keeps the hits of the query in documents whose
metadata satisfy the condition. Conditions compare a metadata field with `=`
or `!=`, a set of values in braces means any of them, and conditions are
combined with `&` (and) and `|` (or).

```{query-example} cql-where
```

```{query-example} cql-where-neq
```

```{query-example} cql-where-or
```

```{query-example} cql-where-and
```

```{query-example} cql-where-set
```

`where(...)` can enclose `within(...)`:

```{query-example} cql-where-within
```

```{query-example} de-where
```

Rules for `where(...)`:

- It must enclose the whole query. A `where(...)` inside an alternative is
  rejected.
- The import stores metadata values as strings, so only `=` and `!=` can be
  used. A comparison such as `>=` is rejected.
- A value with leading or trailing spaces is trimmed, and an empty value or an
  empty set is rejected.
- The corpus needs a metadata index. Without one, the query is rejected
  instead of counting the whole corpus.

```{query-example} cql-reject-range
```

### Similar words

The operator `sim` stands for a set of word forms that are similar in meaning
to a given word. `sim("freedom")` is short for `[sim="freedom"]`, and
`[sim="freedom"&k=30]` asks for up to 30 neighbors instead of the default 20.
Before the query runs, CandyConc replaces the operator with
`word in {…}` and the neighbors it found:

- The neighbors are word forms that occur in the corpus, with a cosine
  similarity of at least 0.55 to the given word, excluding stop words and
  forms without letters.
- The vectors come from the corpus: from its word similarity index, if it
  has one, or else from the static word vectors of the pipeline that
  annotated it, for example `en_core_web_md` for a corpus imported with
  `--language en`. A corpus annotated with an `_sm` pipeline or with
  `blank:` has no word vectors. A query with `sim` on such a corpus is
  rejected with status 422 and the code `word_vectors.unavailable`, and the
  message names the reason, for example a pipeline without static vectors.
  When the corpus records a pipeline with vectors that is not installed on
  the server, the status is 503 with the code `word_vectors.service_error`,
  and the message names the command that installs it. See
  [Word vectors](languages.md#word-vectors).
- `k` is limited to 2,000.

The set also contains the given word itself. The result depends on the vectors
and is therefore not part of the recorded examples. The `_md` pipelines give
many words the same vector, so the set can be large: on the State of the
Union sample corpus, `sim("freedom")` finds 2,172 hits, and the neighbors
*harmony*, *world*, *life*, and *ideals* all have the similarity 1.0 to
*freedom*.

### Diagnostics

A malformed query is rejected with a message that names the problem and its
position. CandyConc does not fall back to a looser search.

```{query-example} cql-reject-unclosed
```

```{query-example} cql-reject-token-compare
```

The server writes its messages in the language of the web interface,
English or German. Over the HTTP API, the header `Accept-Language` chooses
the language, and without it the messages are German.

## Differences from CQP

The query language follows the syntax of the CQP query language of the IMS
Open Corpus Workbench for token conditions, sequences, and repetition. These
parts of CQP are not supported:

- the flag `%d` and flags other than `%c`,
- comparisons of token values with `<` or `>`,
- structural regions other than sentences and documents, and region
  conditions such as `<s>` or `</s>` inside a pattern,
- labels, target markers, and global constraints that refer to labels,
- the CQP command language around queries, such as named query results,
  `sort`, `count`, `set`, or subqueries.

Metadata conditions use `where(...)` instead of the `::` global constraints
of CQP.

## Contract of the query engine

The query engine declares, construct by construct, what it supports. The
declaration classifies the constructs by the levels of the CQLF metamodel
(ISO 24623-1) and states the current level as `2-`, that is, the constructs
of level 1 and part of level 2. The interface uses this declaration for
autocompletion and diagnostics, and the server publishes it as
`cqlf_capability_contract` at `GET /api/v1/capabilities`. The following
table is generated from it.

```{include} _generated/query_contract.md
```
