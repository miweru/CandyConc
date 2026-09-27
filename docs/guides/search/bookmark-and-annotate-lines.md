# Bookmark and annotate concordance lines

Bookmarks keep a search and a selection of its lines, so that you can return
to them. Line annotation assigns a code from your own coding scheme and a
note to single concordance lines, alone or with several coders, and computes
the agreement between coders. This guide covers all three.

## Before you begin

- A search with hits, for example `freedom` in the English sample corpus.

## Bookmark a search and its selected lines

1. Select the lines you want to keep: hold <kbd>Command</kbd> (macOS) or
   <kbd>Control</kbd> (Linux) and click each line. The label next to the hit
   count shows, for example, **2 selected**.
2. In the top bar, click **Bookmarks**.
3. Click **Save current search**.
4. In **Bookmark name...**, enter a name.
5. Click **Save**.

The panel lists the bookmark with its name, the search, the date, and the
number of selected lines.

To return to it later, open **Bookmarks** and click the bookmark. CandyConc
runs the search again, selects the lines, and opens the tab you were on.

A bookmark stores the search, the tab, and the selected lines by their place
in the list. It does not store the corpus, the filter, or the sort order.
Select the same corpus and scope before you restore a bookmark, and restore
it before you sort, so that the same lines are selected. Bookmarks are
stored in the file `prefs.json` in your data folder.

## Create a coding scheme

1. In the toolbar above the concordance, click **Codes & annotations**.

   The dialog **Manage codes** opens.

2. Click **Add code**.
3. In **Code (e.g. metaphor)**, enter a name.
4. Choose a color.
5. Repeat steps 2 to 4 for each additional code.
6. Click **Save**.

The scheme belongs to the active corpus. It applies to every search on that
corpus, whatever the scope. Another corpus has its own scheme, and the codes
of one corpus do not appear on another.

## Annotate a line

1. Point to a line and, in the column **ACTION**, click
   **Annotate line (code + note)**.

   The dialog **Annotate line** shows the line and your codes.

2. Choose a code.
3. Optional: write a note.
4. Click **Save code and note**.

The code appears at the end of the line. Every line has at most one code
and one note per coder. The annotation is stored with the corpus and the
position of the hit, so it stays attached to the line when you sort, draw a
sample, or run the search again later. Annotations are stored in the project
file `proj.ccproj` in your data folder.

```{figure} ../../_static/screenshots/annotate-line-dialog.png
:alt: Annotate line dialog for a line of freedom, with the codes None, political, and economic, political selected, and a note.
:width: 100%

The dialog shows the context of the line, the codes of the scheme, and the note. **Save code and note** stores both.
```

## Code with several coders

1. Click **Codes & annotations**.
2. Open **Advanced: team coding and agreement**.
3. Select **Multiple coders**.
4. In **Coder name**, enter your initials.
5. Click **Save**.
6. Annotate the lines.
7. For the next coder, enter another name in **Coder name**.
8. Click **Save**.
9. Annotate the same lines.

Each coder's code is kept separately for each line. The browser keeps the
coder name when you reload the page. Without a name, the lines show the codes
of the coder `local-annotator`.

## Check the agreement between coders

1. Click **Codes & annotations**.
2. Open **Advanced: team coding and agreement**.
3. Click the button **Reload agreement** (the circular arrow).

The section **Inter-annotator agreement** shows the observed agreement, the
number of lines coded by more than one coder, Cohen's κ for two coders or
Fleiss' κ for more, and the agreement per code. With two coders who agree on
one of two lines, it reads **Observed agreement 50.0%**, **2 lines · 2
coders**, and **Cohen's κ 0.000**. The measures and their interpretation are
in [Inter-annotator agreement](../../methods/inter-annotator-agreement.md).

## Result

Your selections are bookmarked, and the lines carry codes that stay with
them. A CSV export can include the annotations of the loaded lines as a
separate section, see [Export a concordance](../keep-and-share/export-concordances.md).
