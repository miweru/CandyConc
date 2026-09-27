# Semantic similarity

CandyConc has two functions based on vector representations: similar words,
also called the word thesaurus, and semantic passage search. Both return
similarity scores from a vector model, not counts. The vectors come from a
pretrained model, and the corpus decides only which words or passages can be
returned.

The word similarity index and the passage index are FAISS indexes
(Johnson et al. 2021).

## Similar words

**Requirements.** Word vectors that belong to the corpus: a word similarity
index built for it (the files `faiss_word.index` and `word_ids.npy`), or the
static word vectors of the pipeline that annotated it. The `_md` and `_lg`
pipelines of spaCy have static vectors, the `_sm` pipelines and `blank:`
have none. The pipeline must be installed where CandyConc runs. Without word
vectors, the thesaurus view, its HTTP route, and the `sim(...)` operator of
the [query language](../reference/query-language.md#similar-words) are
unavailable, and the capability contract of the corpus states the reason.

**Procedure.**

1. CandyConc computes a vector for the given word, with the vectors that the
   word similarity index was built from if the corpus has one, otherwise with
   the pipeline that annotated the corpus. If the word has no vector, it
   tries the lowercase form.
2. It searches the nearest vectors in the word similarity index, and fills up
   from the vectors of the pipeline, up to 5,000 candidates
   (`CANDYCONC_SIM_MAX_FETCH`).
3. It keeps only words that occur in the corpus, have a cosine similarity of
   at least 0.55 (`CANDYCONC_SIM_MIN_SCORE`), are not stop words of the
   pipeline, and consist of letters.

**Score.** The cosine similarity of the two vectors.

**Corpus frequency.** Each neighbor is listed with its frequency in the
corpus, taken from the frequency list without regard to case.

**Equal scores.** The `_md` pipelines of spaCy map many words to one vector.
Neighbors that share a vector have the same score, and the order among them
carries no information. Which of them a list of $k$ neighbors contains also
depends on $k$. For *freedom* in the State of the Union sample corpus, every
neighbor has the score 1.0, and the list of 10 holds *peace* and *faith*,
while the list of 20 holds *harmony* and *world* instead.

**Interpretation.** The vectors describe word forms as the pretrained model
learned them from its own training data. They are not learned from the
contexts in your corpus. A neighbor tells you that the model considers the
two words similar and that the neighbor occurs in your corpus. To learn how
the words are used in your corpus, compare their concordances or their
collocations.

## Semantic passage search

**Requirements.** Passage vectors and a passage index in the corpus
(`passage_vecs.npy` and `faiss_passage.index`).

**Procedure.**

1. CandyConc embeds the query and normalizes the vector to length 1.
2. It retrieves candidate passages from the passage index. The index stores
   normalized vectors, so the inner product is the cosine similarity. It
   fetches eight times the requested number of results, more when a document
   set restricts the search.
3. It adds passages found by a lexical document search for the query.
4. It keeps one passage per document and orders the documents first by
   lexical criteria, then by the vector score: whether the query occurs as a
   phrase, how many query words occur, how often they occur, and last the
   cosine similarity.

When several passages of one document are among the candidates, the result
keeps one of them. In the current version this is the passage that comes last
in the candidate list, which is the one with the lowest vector score.

**Provenance.** The response states the ordering rule
(`lexical_overlap_then_vector_score`), for each row whether its score is a
cosine or a lexical score (`score_kind`), and whether the vector search was
exact or approximate (`exactness`).

**Kind of number.** A similarity score from a model, combined with a lexical
ordering rule. It is not a count and has no concordance lines behind it. Each
row names the document of its passage.

## Related pages

- [Find similar words and passages](../guides/count-and-measure/similar-words-and-semantic-search.md)
- [Word vectors](../reference/languages.md#word-vectors): which corpora have
  word vectors.
