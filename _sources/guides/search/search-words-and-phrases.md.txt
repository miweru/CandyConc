# Search words and phrases

Plain search finds words and phrases without the query language. This guide
shows the searches you type most often and what each one matches. The
examples run on the English sample corpus, see
[First results](../../get-started/first-results.md).

## Before you begin

- CandyConc is running, and the corpus you want to search is selected in the
  corpus selector.

## Search a word

1. Click the search field, which shows **Enter a word, phrase or query...**.
2. Type the word, for example `freedom`.
3. Press <kbd>Enter</kbd>.

   The **Search** button runs the same search.

The concordance shows the number of hits, for example **495 hits · 300
loaded**, and one line per hit. Plain search ignores case: `freedom`,
`Freedom`, and `FREEDOM` give the same 495 hits.

## Match case

1. Click **Aa** (**Match case**) in the search field. The button stays
   highlighted.
2. Search `Freedom`.

The concordance shows **14 hits**, only the capitalized form. Click **Aa**
again to ignore case.

## Use wildcards and regular expressions

| Search | Matches | Hits in the sample corpus |
| --- | --- | --- |
| `free*` | word forms that start with *free*, including *free* itself | 1,005 |
| `defen?e` | *defense* and *defence*: `?` stands for exactly one character | 346 |
| `/libert.*/` | a regular expression between slashes, matched against the whole word form | 89 |

A wildcard or a regular expression must match the whole word form and
ignores case.

## Search a phrase

1. Type the words in double quotes, for example `"freedom from fear"`.
2. Press <kbd>Enter</kbd>.

The concordance shows the **2 hits** where the three words follow each
other within one document, compared without regard to case.

If you type several words without quotes, for example `freedom from fear`,
the search field turns them into a sequence of the query language,
`cql:[word="freedom"] [word="from"] [word="fear"]`, and runs it. That
sequence respects case. Use quotes when case should not matter.

## Combine words

| Search | Matches | Hits |
| --- | --- | --- |
| `liberty OR freedom` | tokens that are either word | 575 |
| `freedom AND [pos=NOUN]` | tokens of *freedom* that are tagged as nouns | 486 |
| `freedom NEAR/3 peace` | *freedom* with *peace* at most three tokens away, and *peace* with *freedom* nearby. Both count as hits | 80 |

The operators are written in capital letters. On a corpus with dependency
relations, `defend >dobj freedom` finds the verb *defend* with *freedom* as
its direct object (12 hits).

## Result

The concordance shows the lines of your search, and the number above the
table counts them. How to sort the lines and open them in their documents is
described in [Read hits in context](read-in-context.md). All forms of plain
search, with their exact rules, are in
[Query language](../../reference/query-language.md). For lemmas, parts of
speech, and longer patterns, see [Write structured queries](write-structured-queries.md).
