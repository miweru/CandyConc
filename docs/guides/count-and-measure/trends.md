# Follow a frequency over time

A trend counts the hits of a search in each period of a date field, such as
each year, and divides by the number of word tokens in the documents of that
period. This guide draws the trend of a word and reads its table.

## Before you begin

- A corpus with a metadata field that holds a date or a year, for example
  `date` or `year` in the English sample corpus. Dates in the form
  `YYYY-MM-DD` can be grouped by year or month.
- A search with hits, for example `freedom`.

## Draw the trend

1. Search for the word or query, for example `freedom`.
2. Click **More** in the tab bar.
3. Choose **Trend**.
4. Under **Date field**, choose the field, for example `year`.
5. Under **Granularity**, choose **Year** or **Month**.

The chart shows the hits per million word tokens for each period, with a
band for the 95% Wilson confidence interval of the rate. The table below it
lists each period with its values:

| Period | Documents | Hits | Tokens | Per million | 95% CI |
| --- | --- | --- | --- | --- | --- |
| 1945 | 1 | 7 | 1,907 | 3,670.69 | 1,779.21 to 7,557.75 |
| 1946 | 1 | 9 | 27,621 | 325.84 | 171.44 to 619.21 |

These are the first two rows for `freedom` over the field `year` in the
sample corpus. **Tokens** counts the [word tokens](../../reference/glossary.md)
of the period, the tokens with at least one letter or digit, which keyness
and the copilot tool `query_count` divide by as well. The field has 61
periods, one for each year with an address.
Periods without documents are left out.

The width of the interval shows how much a rate rests on: the 1945 address
has 1,907 word tokens, and its rate of 3,670.69 per million comes from 7 hits.

```{figure} ../../_static/screenshots/trend-freedom-year.png
:alt: Trend of freedom over the field year in sotu_en, a line of hits per million word tokens with a 95% Wilson band, and the table starting with 1945 (3,670.69) and 1946 (325.84).
:width: 100%

The chart shows the rate per period with its confidence band. The table below lists the counts the rates are computed from.
```

## Documents without a date

Documents whose date field cannot be read as a date form their own group,
**undated**, which appears only in the table. With the field `date` of the
sample corpus, a note above the table reads
**10 documents without a parsable date in the field 'date' are reported as a
separate bucket ‘undated’ (79 hits).**

## Open the lines of a period

Click a row of the table or a point of the chart. CandyConc narrows the scope
to the documents of the period with a metadata filter on the values of the
date field that form the period, for example **year: 1945**, and runs the
same search there. For `freedom` in 1945 the concordance shows 7 hits, the
same number as the row, and the line above it reads **From the trend:
freedom in 1945 (year), 7 hits**. For the field `date`, the filter lists the
dates of the period. If a scope was active, the filter is added to it.

The group **undated** has no link, because its documents have no date value
to filter on. To see all periods again, remove the filter in
**Filter / Subcorpus**. See [Filter by document metadata](../narrow-the-scope/filter-by-metadata.md).

## Export

The download icon above the chart, **Export trend as CSV**, saves the table.

## Result

You have the rate of your search per period, with its confidence interval
and the raw counts it is computed from. The formula and the interval are
described in [N-grams and trends](../../methods/n-grams-and-trends.md).
