# Save analyses and workspaces

A saved analysis stores the settings and the result of an analysis under a
name, so that you can open it again in a later session. The workspace lists
your saved analyses, your subcorpora, and the analysis jobs of the server.
This guide saves an analysis and opens it again.

## Before you begin

- An analysis on the screen, for example the collocations of `freedom`.

## Save an analysis

1. In the analysis view, click **Save**.
2. In the dialog **Save analysis**, enter a name, for example
   `freedom collocates, window 5`.
3. Click **Save**.

CandyConc reports **Analysis saved**. The button **Save** is available in
the views Frequency, Collocations, Dispersion, N-grams, Keyness, Word sketch,
and Network.

## Open a saved analysis

1. In the top bar, click **Saved analyses**.

   The panel **Workspace** opens.

2. Click the tab **Saved analyses**.

   The list shows each analysis with its name, its type (for example
   **Collocations**), its scope, its corpus, its query, and the dates it was
   created, modified, and last opened.

3. Click **Open analysis** next to the analysis.

CandyConc activates the corpus and the scope the analysis was saved with and
opens the analysis view with the stored query and settings. If the corpus is
no longer in the corpus catalog, a message names it and the analysis stays
closed. Import or register the corpus again to open the analysis.

```{figure} ../../_static/screenshots/workspace-saved-analyses.png
:alt: Workspace, tab Saved analyses, with the entry freedom collocates, window 5, of the type Collocations for the query freedom in sotu_en, below the analysis jobs.
:width: 640px

The saved analysis lists its type, scope, corpus, and query. **Open analysis** (the play icon) opens it again.
```

## Delete a saved analysis

Click **Delete analysis** next to it in the list.

## Follow analysis jobs

Frequency lists, collocations, n-grams, keyness, and contrasts run as jobs on
the server. The section **ANALYSIS JOBS** of the tab **Saved analyses** lists
the running and recently known jobs with their kind, status, number of rows,
and result size. **Status** and **Rows** load the state and the result rows of
a job. The server keeps the jobs in memory. After CandyConc is restarted,
the results of earlier jobs can no longer be loaded, and a saved analysis
keeps the result rows it had when you saved it.

## Where saved analyses are stored

Saved analyses are stored in the file `projects/default/analysis_presets.json`
in your data folder, together with the result rows at the time of saving.
`candy paths` shows the folder. See [Back up your data](back-up-your-data.md).

## Result

Your analyses are stored under names and can be opened from the workspace in
a later session. Subcorpora are managed in the tab **Subcorpora** of the same
panel, see [Create and reuse subcorpora](../narrow-the-scope/create-subcorpora.md).
