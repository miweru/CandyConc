# Find collocations

Collocates are the words that occur near a word more often than their
overall frequency leads one to expect. This guide computes the collocates of
a search, changes the window and the measure, opens the lines behind a
collocate, and shows the collocation network.

## Before you begin

- A search with hits. The collocation view uses the current search as the
  node, for example `freedom` in the English sample corpus.
- Optional: a metadata filter or subcorpus. Collocations count in the active
  scope.

## Compute the collocates

1. Search for the node, for example `freedom`.
2. Click the tab **Collocations**.

The table lists the collocates with their co-occurrence frequency and the
score of the chosen measure, ranked by the score. With the defaults, the
first rows for *freedom* are *peace* (frequency 52, logDice 10.579),
*cause* (24, 10.337), and *defend* (18, 10.054).

## Change the settings

The row above the table holds the settings:

| Setting | Default | Meaning |
| --- | --- | --- |
| **Window** | 5 | the number of tokens to the left and right of each hit that are searched for collocates |
| **Within sentence** | on | windows stop at sentence boundaries |
| **Min. f** | 5 | collocates with a lower co-occurrence frequency are left out |
| measure | logDice | the association measure used for the score and the ranking: logDice, Dice, mutual information, MI3, LMI, NPMI, z-score, t-score, log-likelihood, co-occurrence frequency, and others |

Change a setting, and the table is computed again. With a window of 3,
for example, *peace* has the frequency 40 and the logDice 10.200. The
information button next to the measure, **Formula and explanation: logDice**,
shows the formula and the reference of the measure. The measures
and the contingency table they use are described in
[Collocations and association measures](../../methods/association-measures.md).

## Open the lines behind a collocate

1. In the table, click a collocate, for example **peace**.

CandyConc switches to the tab **KWIC** and shows the lines in which the
collocate occurs in the window of a hit, here **52 hits**, with the label
**Co-anchors** for *freedom* and *peace* and **O11: peace 52**. The search
field shows the query of these lines:

```text
co(term="freedom", collocate="peace", window=5, within_sentence=true)
```

The number of lines can differ from the frequency in the table when the
windows of two hits overlap. [From numbers to lines](../../concepts/from-numbers-to-lines.md)
explains why.

## Read the method card

Below the settings, click **Method and reproducibility** to open the method
card of the table. It lists every statistic of the result with its formula,
its smoothing, and its sort key. **Method limits** names the conditions and
limits of the analysis.

## Show the collocation network

1. Click **Network** above the table.

Alternatively, the tab bar offers the same view:

1. Open **More**.
2. Choose **Network**.

The network shows the node in the center and its collocates around it. The
size of a collocate is its co-occurrence frequency with the word through
which it was reached, and the width of an edge is the logDice score. In the
tab **Network**, **Depth 1 (star)** shows only the collocates of the node,
and **Depth 2 (ego network)** adds the collocates of the collocates.
**Nodes** sets the number of collocates, 30 by default. In the tab
**Network**, <kbd>Control</kbd> or <kbd>Command</kbd> with the mouse wheel
zooms the graph, a pinch on a trackpad does the same, and dragging moves it.
The mouse wheel alone scrolls the view.

```{figure} ../../_static/screenshots/collocations-freedom.png
:alt: Collocations of freedom ranked by logDice with window 5, within sentence, and minimum frequency 5, with the bar Method and reproducibility above the table.
:width: 100%

The settings row above the table, and the bar **Method and reproducibility**, which opens the method card.
```

## Save the result

**Save** stores the settings as a saved analysis, see
[Save analyses and workspaces](../keep-and-share/save-analyses.md). The
download icon, **Export collocations as CSV**, saves the table as a CSV file.

## Result

You have the collocates of your search in the active scope, ranked by the
measure you chose, and the lines behind each of them. To compare the
collocates of a word in two subcorpora, see
[Contrast collocations and paired versions](contrast.md). For collocates by
grammatical relation, see [Make a word sketch](word-sketches.md).
