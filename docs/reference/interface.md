# Interface reference

This page lists the parts of the web interface, where each function is, and
every preference of the **Settings** dialog with its effect. The labels are
those of the English interface. How to use each view is described in the
[Guides](../guides/index.md).

## Top bar

| Control | What it does |
| --- | --- |
| corpus selector, for example **sotu_en · 403,284 tokens** | switches the active corpus. The list shows every corpus of the catalog with its size and language, and **Manage corpora** at the end. See [Switch, register, and remove corpora](../guides/bring-in-texts/manage-corpora.md). |
| **Export** (download icon) | exports the current result as PDF, Word, or CSV. See [Export a concordance](../guides/keep-and-share/export-concordances.md). |
| **Bookmarks** (bookmark icon) | saves the current search as a bookmark and lists the bookmarks. See [Bookmark and annotate concordance lines](../guides/search/bookmark-and-annotate-lines.md). |
| **Subcorpora** (layers icon) | opens the panel **Workspace** on the tab **Subcorpora**. See [Create and reuse subcorpora](../guides/narrow-the-scope/create-subcorpora.md). |
| **Saved analyses** (disk icon) | opens the panel **Workspace** with the saved analyses and the analysis jobs of the server. See [Save analyses and workspaces](../guides/keep-and-share/save-analyses.md). |
| **Manage corpora** (database icon) | opens the corpus manager: import a corpus, register an existing index, activate or remove a corpus. See [Import a corpus](../guides/bring-in-texts/import-a-corpus.md). |
| **Settings** (gear icon) | opens the settings, see [Settings](#settings). |
| session icon | shows the session: **Local single-user mode**, or the signed-in account in multi-user mode, with **Sign out**. |
| **Dark theme** (moon icon) | switches between the light and the dark color scheme. |
| **Help** (question mark icon) | opens this documentation or the list of keyboard shortcuts. |

## Search bar and scope

| Control | What it does |
| --- | --- |
| search field, **Enter a word, phrase or query...** | runs a plain search or a query of the query language. See [Query language](query-language.md). |
| **Aa** (**Match case**) | makes a plain search respect case. A query of the query language uses `%c` instead. |
| query builder icon (**Query builder**) | builds a query from fields. See [Write structured queries](../guides/search/write-structured-queries.md). |
| **Search** | runs the search. |
| **Filter / Subcorpus** | opens the panel **Subcorpus filters** with the metadata filters. See [Filter by document metadata](../guides/narrow-the-scope/filter-by-metadata.md). |
| scope label, **WHOLE CORPUS** or **SCOPE** | names the active scope, the documents that every search and analysis counts. See [Scope, subcorpora, and document sets](../concepts/scope.md). |

## Views

The tabs below the search bar hold the views, and **More** opens the others.
The key combinations use <kbd>Alt</kbd>, which is <kbd>Option</kbd> on macOS.

| Tab | Key | Content | Guide |
| --- | --- | --- | --- |
| **KWIC** | <kbd>Alt</kbd>+<kbd>1</kbd> | the concordance of the current search | [Read hits in context](../guides/search/read-in-context.md) |
| **Reader** | <kbd>Alt</kbd>+<kbd>L</kbd> | the documents of the active scope with their full text | [Read whole documents](../guides/search/read-in-context.md#read-whole-documents) |
| **Frequency** | <kbd>Alt</kbd>+<kbd>2</kbd> | frequency lists of word forms, lemmas, or parts of speech | [Make a frequency list](../guides/count-and-measure/frequency-lists.md) |
| **Collocations** | <kbd>Alt</kbd>+<kbd>3</kbd> | the collocates of the current search | [Find collocations](../guides/count-and-measure/collocations.md) |
| **Dispersion** | <kbd>Alt</kbd>+<kbd>4</kbd> | the spread of the hits over the documents | [Measure dispersion](../guides/count-and-measure/dispersion.md) |
| **Semantic** | <kbd>Alt</kbd>+<kbd>5</kbd> | similar words and passage search | [Find similar words and passages](../guides/count-and-measure/similar-words-and-semantic-search.md) |
| **Contrast** | <kbd>Alt</kbd>+<kbd>7</kbd> | the collocates of a word in two groups of documents | [Contrast collocations and paired versions](../guides/count-and-measure/contrast.md) |
| **Network** (under **More**) | <kbd>Alt</kbd>+<kbd>0</kbd> | the collocation network | [Show the collocation network](../guides/count-and-measure/collocations.md#show-the-collocation-network) |
| **N-grams** (under **More**) | <kbd>Alt</kbd>+<kbd>6</kbd> | n-grams and their contrast | [Count n-grams](../guides/count-and-measure/n-grams.md) |
| **Keyness** (under **More**) | <kbd>Alt</kbd>+<kbd>8</kbd> | keywords of a target against a reference | [Compare two subcorpora with keyness](../guides/count-and-measure/keyness.md) |
| **Word sketch** (under **More**) | <kbd>Alt</kbd>+<kbd>9</kbd> | collocates by dependency relation | [Make a word sketch](../guides/count-and-measure/word-sketches.md) |
| **Trend** (under **More**) | <kbd>Alt</kbd>+<kbd>T</kbd> | the rate of the hits over time | [Follow a frequency over time](../guides/count-and-measure/trends.md) |

A view that the active corpus cannot support is disabled, and pointing at it
shows the reason, for example that the corpus has no dependency relations.
**PARTIAL** next to a tab means that part of the view is available.

## Status bar, command palette, and copilot

- The status bar at the bottom shows the active corpus with its size, the hit
  count of the current search, the state of the server, for example
  **Server READY**, and a button that checks the server again.
- **K for commands** in the status bar stands for <kbd>Command</kbd>+<kbd>K</kbd>
  on macOS and <kbd>Control</kbd>+<kbd>K</kbd> on Linux. The command palette
  lists the views and panels and says why a blocked one is not available.
- The round copilot button at the left end of the status bar, or
  <kbd>Command</kbd>+<kbd>Shift</kbd>+<kbd>K</kbd>, opens the copilot panel
  with the tabs **Chat**, **Runs**, and **Research**. Without a language
  model, the panel shows **No language model set up** and the button
  **Set up model connection**. See
  [Connect a language model](../guides/copilot/connect-a-model.md).

## Settings

The **Settings** dialog has six tabs. A change applies at once and is saved
on the server in the preferences file and in the browser, see
[Configuration reference](configuration.md#settings-of-the-web-interface).
**Reset settings** at the bottom returns the preferences to their defaults.

### General

| Preference | Default | Effect |
| --- | --- | --- |
| **Copilot autonomy** | level 2 of 4, **Read freely** | how far the copilot acts without asking. Level 1 **Plan first**: actions run only after the plan is confirmed. Level 2 **Read freely**: read-only analyses run freely, writing or irreversible actions need confirmation. Level 3 **Mostly free**: everything except destructive actions runs freely. Level 4 **Autonomous**. |
| **Language** | see [Choose the interface language](../get-started/install.md#choose-the-interface-language) | the language of the interface and of the texts that the server writes for it. |
| **Default corpus** | **Last active corpus** | the corpus that the interface opens when it loads and the address names no corpus. |
| **Results per page** | 100 | how many concordance lines a search loads before you scroll. For `freedom` in the English sample corpus, a search loads 300 lines with 100 and 200 lines with 50. |
| **Confirm deletion** | on | asks before a bookmark, all bookmarks, a line annotation, a saved subcorpus, or a saved analysis is deleted. |
| **Enable keyboard shortcuts** | on | turns the keyboard shortcuts of the interface on or off, including <kbd>?</kbd> for the list of shortcuts and undo. |
| **Background research** | on | lets the copilot search documents and run semantic searches in the background while it answers. |
| **Product tour** | | **Restart tour** starts the short introduction again. |

The section **Privacy and operation** states that CandyConc sends no
telemetry. It has no settings.

### Appearance

| Preference | Default | Effect |
| --- | --- | --- |
| **Color scheme** | | **Light**, **Dark**, **System** (the operating system setting), or **Pink** with rose backgrounds and pink controls. |
| **Highlight color** | yellow | the color of the hits in the concordance: yellow, blue, green, or purple. |
| **Typeface** | **System** | **System** or **Monospace** for the displayed text. |
| **Font size** | the middle size | three sizes of the displayed text. |

**Preview** shows two concordance lines with the chosen settings.

### Other tabs

| Tab | Content |
| --- | --- |
| **Corpora** | the corpus manager, the same as **Manage corpora** in the top bar |
| **Embeddings** | the local semantic index of the active corpus for passage search, with the estimated size and the button **Build**. See [Search passages by meaning](../guides/count-and-measure/similar-words-and-semantic-search.md#search-passages-by-meaning). |
| **Model connection** | endpoint and model of the language model for the copilot, with two prepared connections. See [Connect a language model](../guides/copilot/connect-a-model.md). |
| **System** | the version of the server, its uptime, the state of the passage index, the corpus of the server, and the cache with the button **Clear**. |
