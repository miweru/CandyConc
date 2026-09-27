"""Polishing preserves copyable search queries inside code blocks."""

from candyconc.candyconc_copilot import recipe_runtime as rr

_SUCHE = '[word="nicht"%c] [word="nur"] []{0,8} [word="sondern"%c] [word="auch"]'


def test_suche_im_codeblock_bleibt_unveraendert():
    text = f"Die Suche:\n\n```cql\n{_SUCHE}\n```\n"
    assert rr._wrap_naked_query_lines(text) == text


def test_nackte_suche_ausserhalb_des_blocks_wird_weiter_markiert():
    assert rr._wrap_naked_query_lines(_SUCHE) == f"Query: `{_SUCHE}`"
