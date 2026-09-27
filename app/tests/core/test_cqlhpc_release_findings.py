"""Regression tests for CQLHPC release findings 17, 20, 21, 35.

These exercise the CQL parser and the predicate/engine layer directly against
the in-memory toy corpus so they do not depend on a built Fast Index.

Findings:
- 17: ``[attr="value"]`` with regex/alternation/char-class metacharacters must
      regex-match the lexicon (CWB-style), not silently return zero hits. A
      regex ``!=`` must fail loudly (unsupported), never silently wrong.
- 20: structural ``within``/``where`` near-misses must raise a clear, consistent
      ``ParseError`` (4xx), never crash; the accepted form is named in the error.
- 21: truncated CQL (``[pos=``, ``[pos``) routes to the CQL parser and surfaces a
      ``ParseError`` rather than a silent empty literal search.
- 35: an out-of-tagset value on the enumerable ``pos`` attribute raises a clear
      error naming the valid inventory, instead of the silent no-hits path.
"""

from __future__ import annotations

import pytest

from cqlhpc.corpus import build_toy_corpus
from cqlhpc.engine import QueryEngine, SearchOptions
from cqlhpc.parser import ParseError, parse_cql


_OPTS = SearchOptions(max_matches=100, within_sentences_by_default=False)


@pytest.fixture()
def engine() -> QueryEngine:
    return QueryEngine(build_toy_corpus())


def _matched_words(corpus, matches):
    word_lex = corpus.lexicon("word")
    words = corpus.attr("word")
    out = []
    for m in matches:
        out.append(
            " ".join(word_lex.id_to_str[int(words[p])] for p in range(m.start, m.end))
        )
    return out


# --------------------------------------------------------------------------- #
# Finding 17: in-bracket attribute regex                                       #
# --------------------------------------------------------------------------- #
def test_finding17_regex_dotstar_matches_like_glob(engine):
    # toy "geh*" tokens: gehe, gehst, gehen, gehen
    matches = engine.search('[word="geh.*"]', _OPTS)
    got = sorted(set(_matched_words(engine.corpus, matches)))
    assert got == ["gehe", "gehen", "gehst"]
    assert len(matches) >= 3  # not the old silent zero


def test_finding17_regex_alternation_and_charclass(engine):
    alt = _matched_words(engine.corpus, engine.search('[word="gehe|gehst"]', _OPTS))
    assert sorted(set(alt)) == ["gehe", "gehst"]
    cc = _matched_words(engine.corpus, engine.search('[word="geh[en]+"]', _OPTS))
    assert "gehe" in cc and "gehen" in cc


def test_finding17_anchored_regex(engine):
    # fullmatch semantics: ^nach$ matches only the exact token
    matches = engine.search('[word="^nach$"]', _OPTS)
    assert set(_matched_words(engine.corpus, matches)) == {"nach"}


def test_finding17_exact_literal_without_metachars_unchanged(engine):
    # No metacharacters -> stays on the exact-id path (no regression).
    matches = engine.search('[word="nach"]', _OPTS)
    assert _matched_words(engine.corpus, matches) == ["nach", "nach"]


def test_finding17_regex_not_equals_fails_loudly(engine):
    # Negated regex set is unsupported by the NFA -> loud error, never silent.
    with pytest.raises(ValueError) as exc:
        engine.search('[word!="geh.*"]', _OPTS)
    msg = str(exc.value)
    assert "!=" in msg
    # Must NOT be swallowed as an empty-match by the cql_engine boundary.
    assert "liefert keine Treffer" not in msg


# --------------------------------------------------------------------------- #
# Finding 20: structural within/where diagnostics                              #
# --------------------------------------------------------------------------- #
def test_finding20_within_canonical_form_parses():
    node = parse_cql('within(<s>, [pos="NN"])')
    assert type(node).__name__ == "Within"


@pytest.mark.parametrize(
    "query",
    [
        "within <s>",        # the form that previously crashed with HTTP 500
        "within(s)",
        "within(<s>)",
        '[pos="NN"] within s',
    ],
)
def test_finding20_within_near_miss_raises_clear_parse_error(query):
    with pytest.raises(ParseError) as exc:
        parse_cql(query)
    msg = str(exc.value)
    # Rendered string is prefixed so the HTTP boundary maps it to a 400.
    assert "Parse" in msg
    # One consistent, actionable hint naming the accepted form.
    assert "within(<s>" in msg and "within(<doc>" in msg


# --------------------------------------------------------------------------- #
# Finding 21: truncated CQL is a parse error, not a silent empty result        #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("query", ["[pos=", "[pos", '[pos="NN"'])
def test_finding21_truncated_bracket_raises_parse_error(query):
    with pytest.raises(ParseError) as exc:
        parse_cql(query)
    assert "Parse" in str(exc.value)


# --------------------------------------------------------------------------- #
# Finding 35: out-of-tagset pos value                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", ["NOUN", "GARBAGE123"])
def test_finding35_oov_pos_value_raises_with_hint(engine, bad):
    # The toy corpus uses STTS tags, so UPOS "NOUN" / garbage are out-of-tagset.
    with pytest.raises(ValueError) as exc:
        engine.search(f'[pos="{bad}"]', _OPTS)
    msg = str(exc.value)
    assert "pos" in msg and bad in msg
    # Lists at least one valid tag and is not the swallowed empty-match error.
    assert "Gültige Werte" in msg
    assert "liefert keine Treffer" not in msg


def test_finding35_valid_pos_value_unaffected(engine):
    # A legitimate (in-tagset) pos value still returns its hits.
    matches = engine.search('[pos="NN"]', _OPTS)
    assert _matched_words(engine.corpus, matches) == ["hause"]


def test_finding35_open_class_zero_result_not_treated_as_tagset_error(engine):
    # word/lemma are open-class: a genuinely absent value must NOT raise the
    # closed-class "Unbekanntes pos-Tag" error (scoping guard for finding 35).
    # At the raw engine level an OOV literal raises the *recognised* empty-match
    # error, which the cql_engine HTTP boundary swallows to an empty result.
    with pytest.raises(ValueError) as exc:
        engine.search('[word="totallyabsentword"]', _OPTS)
    msg = str(exc.value)
    assert "liefert keine Treffer" in msg
    assert "Unbekanntes pos-Tag" not in msg


def test_finding35_pos_in_set_all_oov_raises_but_mixed_is_ok(engine):
    with pytest.raises(ValueError):
        engine.search('[pos in {"NOUN","ZZZ"}]', _OPTS)
    # A set with at least one valid tag is a normal query.
    mixed = engine.search('[pos in {"NN","NOUN"}]', _OPTS)
    assert _matched_words(engine.corpus, mixed) == ["hause"]
