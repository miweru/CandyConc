# Find similar words and passages

The tab **Semantic** has two functions. **Similar words** lists the words of
the corpus whose word vectors are closest to a given word. **Passages** finds
documents and sentences whose meaning is close to a query, with an embedding
index built for the corpus. This guide shows what each function needs and
how to use it.

## Before you begin

- The tab **Semantic** shows what the active corpus supports. Point to the
  tab to read the reason when a part is missing. **PARTIAL** next to the tab
  means that similar words work and passage search is missing.

## Find similar words

Similar words use word vectors that belong to the corpus: the static word
vectors of the pipeline that annotated it, or a word vector index built at
import. A corpus imported with `--language en` or `--language de` uses
`en_core_web_md` or `de_core_news_md`, which have static vectors. The `_sm`
pipelines and `blank:LANG` have none. The pipeline must be installed where
CandyConc runs, because the vectors are read from it.

For a corpus without word vectors the tab marks similar words as missing and
names the reason. The HTTP API answers such a request with status 422 and
the code `word_vectors.unavailable`. When the corpus records a pipeline with
vectors that is not installed on the server, it answers 503 with the code
`word_vectors.service_error`, and the message names the command that
installs the pipeline, for example `candy pipeline en_core_web_md`.

1. Click the tab **Semantic**.
2. Click **Similar words**.
3. Enter a word.

   Clicking an example word is an alternative to typing.

4. Under **Top**, choose the number of neighbors: 10, 20, 50, or 100.

The result names the number of neighbors, the backend, and that the list is
**restricted to the corpus**: only words that occur in the active corpus are
listed. Each neighbor shows its similarity as a percentage and its frequency
in the corpus. Click a neighbor to search it in the concordance.

The pipeline `en_core_web_md` keeps 20,000 distinct vectors for about
685,000 words, so many words share one vector. In the English sample corpus, *freedom*,
*peace*, *faith*, *harmony*, and *world* have the same vector, and each of
these neighbors of *freedom* shows 100.0%. The order among neighbors with
the same score carries no information. Whether a larger pipeline such as
`en_core_web_lg` gives graded scores is not tested here.

To build a word vector index at import instead, select
**Build the similar words index (word FAISS) after the import** (option `build_word_faiss`)
in the corpus manager. It needs the optional package group `semantic`, see
[Install the Python package](../../get-started/install-python-package.md#optional-features).

```{figure} ../../_static/screenshots/similar-words-freedom.png
:alt: Similar words for freedom in sotu_en, restricted to the corpus, backend spacy, with harmony, world, soul, and ideals at 100.0%.
:width: 100%

The neighbors of *freedom* with their similarity and their frequency in the corpus. Words that share one vector of `en_core_web_md` all show 100.0%.
```

## Search passages by meaning

Passage search needs a local semantic index of the corpus, built with the
embedding model EmbeddingGemma 300M. The build runs on Macs with Apple
silicon and needs the optional package group `semantic`.

1. Open **Settings**.
2. Click the tab **Embeddings**.

   The section **Local semantic index** names the active corpus, the memory
   and free disk space of the computer, and the number of documents and
   sentences. It estimates the size of the index, the free disk space the
   build requires, and the memory the search needs. For the English sample
   corpus it estimates 1.5 GB of free disk space and 1.9 GB of memory.

3. Choose **Documents** or **Documents + sentences**.
4. Click **Build**.

The build is a download and a computation:

- It installs a separate Python runtime for the model in
  `~/.candyconc/runtimes`, with the packages `mlx`, `mlx-embeddings`,
  `transformers`, and `huggingface-hub`, downloaded from the Python Package
  Index.
- It downloads the model `mlx-community/embeddinggemma-300m-4bit` from
  Hugging Face into the Hugging Face cache (`~/.cache/huggingface/hub`, or
  the folder named by `HF_HOME`).
- It computes a vector for every document, and for every sentence if you
  chose so, on your computer. No text leaves the computer during this step.

Without the package group `semantic`, the section shows **The semantic index
needs the optional package faiss.** and how to install it.

**Passages** in the tab **Semantic** is available once the corpus has this
index.

## Result

You can list the words of your corpus that are distributionally close to a
word, and, with a semantic index, find passages by meaning. How similarity is
computed and what the scores mean is described in
[Semantic similarity](../../methods/semantic-similarity.md). What the build
downloads is also listed in [Data and privacy](../../concepts/data-and-privacy.md).
