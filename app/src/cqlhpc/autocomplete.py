from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .capabilities import (
    language_service_meta_operators,
    language_service_snippets,
    language_service_token_attributes,
    language_service_token_operators,
)
from .errors import lt
from .lexer import Token, lex, token_at
from .corpus import Corpus


@dataclass(frozen=True, slots=True)
class Suggestion:
    label: str
    insert_text: str
    kind: str  # 'snippet'|'keyword'|'attr'|'op'|'value'|'fix'
    start: int
    end: int
    score: float = 0.0
    detail: str = ''
    builder_node: Optional[Dict[str, Any]] = None

def complete(
    text: str,
    cursor: int,
    corpus: Optional[Corpus] = None,
    limit: int = 50,
    docset_mask: Optional[Any] = None,
    where_fields: Optional[Sequence[str]] = None,
) -> List[Suggestion]:
    """Completion suggestions for ``text`` at ``cursor``.

    ``where_fields`` are the metadata fields of ``corpus`` that tell documents
    apart, the most general first. The caller chooses them (candyconc uses
    ``candyconc.core.meta_index.descriptive_fields``), so that cqlhpc does not
    depend on candyconc. With a corpus and no such field the where() snippet
    is left out, without a corpus it keeps its generic form.
    """
    toks = lex(text)
    cur = token_at(toks, cursor)
    if cur is None:
        # cursor at end of token
        for t in reversed(toks):
            if t.end == cursor:
                cur = t
                break

    # String literal completion (value completion inside quotes)
    if cur is not None and cur.kind in {'STRING', 'STRING_UNTERM'} and cur.start < cursor:
        start = cur.start + 1
        end = cursor
        prefix = text[start:end]
        attr = _infer_attr_before(toks, cur.start)
        out: List[Suggestion] = []

        if cur.kind == 'STRING_UNTERM':
            out.append(Suggestion('"', '"', 'fix', cursor, cursor, score=1e9, detail=lt('String schließen', 'Close string')))

        if corpus is not None and attr is not None and corpus.has_attr(attr):
            lexicon = corpus.lexicon(attr)
            docset_idx = None
            if docset_mask is not None and hasattr(corpus, "docset_index"):
                docset_idx = corpus.docset_index(attr)
            for s, tid in lexicon.suggest(prefix, limit=limit):
                # Replace only the typed fragment, keep quotes.
                base = 0.0
                if getattr(lexicon, "freqs", None) is not None:
                    base = float(lexicon.freqs[tid])
                elif hasattr(lexicon, "get_freq"):
                    base = float(lexicon.get_freq(int(tid)))
                if docset_idx is not None:
                    ds = float(docset_idx.count_in_mask(int(tid), docset_mask))
                    sc = ds * 1000000.0 + base
                else:
                    sc = base
                out.append(Suggestion(s, s, 'value', start, end, score=sc))

        return _rank(out)[:limit]

    ctx = _infer_context(toks, cursor, corpus=corpus)
    rs, re, prefix = ctx['replace_start'], ctx['replace_end'], ctx.get('prefix', '')

    out: List[Suggestion] = []

    if ctx['state'] == 'top':
        for snippet in language_service_snippets():
            insert_text = snippet.insert_text
            if corpus is not None and insert_text.startswith('where('):
                example = _where_example(corpus, where_fields)
                if example is None:
                    # where() needs a metadata index with a field to filter by.
                    continue
                insert_text = f'where({example[0]}="{_esc(example[1])}", $1)'
            out.append(
                Suggestion(
                    insert_text,
                    insert_text,
                    'snippet',
                    rs,
                    re,
                    score=100.0,
                    detail=snippet.detail,
                )
            )
        out.append(Suggestion('|', ' | ', 'keyword', rs, re, score=10.0))
        out.append(Suggestion('within', 'within(<s>, )', 'snippet', rs, re, score=9.0, detail='Wrapper'))
        return _rank(out)[:limit]

    if ctx['state'] == 'tok_attr':
        attrs = sorted(corpus.attrs.keys()) if corpus is not None else ['lemma', 'pos', 'word']
        for attr in language_service_token_attributes():
            if attr not in attrs:
                attrs.append(attr)
        if ctx.get('has_sim') and not ctx.get('has_k') and 'k' not in attrs:
            attrs.append('k')
        for a in attrs:
            if not prefix or a.startswith(prefix):
                out.append(Suggestion(a, a, 'attr', rs, re, score=50.0))
        return _rank(out)[:limit]

    if ctx['state'] == 'tok_op':
        for o in language_service_token_operators():
            if not prefix or o.startswith(prefix):
                ins = f" {o} " if o == 'in' else o
                out.append(Suggestion(o, ins, 'op', rs, re, score=50.0))
        return _rank(out)[:limit]

    if ctx['state'] == 'tok_val':
        attr = ctx.get('attr')
        if corpus is not None and attr and corpus.has_attr(attr):
            lexicon = corpus.lexicon(attr)
            docset_idx = None
            if docset_mask is not None and hasattr(corpus, "docset_index"):
                docset_idx = corpus.docset_index(attr)
            for s, tid in lexicon.suggest(prefix, limit=limit):
                base = 0.0
                if getattr(lexicon, "freqs", None) is not None:
                    base = float(lexicon.freqs[tid])
                elif hasattr(lexicon, "get_freq"):
                    base = float(lexicon.get_freq(int(tid)))
                if docset_idx is not None:
                    ds = float(docset_idx.count_in_mask(int(tid), docset_mask))
                    sc = ds * 1000000.0 + base
                else:
                    sc = base
                out.append(Suggestion(s, f"\"{_esc(s)}\"", 'value', rs, re, score=sc))
        out.append(Suggestion('"..."', '"$1"', 'snippet', rs, re, score=5.0, detail=lt('Stringliteral', 'String literal')))
        out.append(Suggestion('{"..."}', '{ "$1", "$2" }', 'snippet', rs, re, score=4.0, detail=lt('Set-Literal', 'Set literal')))
        return _rank(out)[:limit]

    if ctx['state'] == 'tok_after_val':
        out.append(Suggestion('&', ' & ', 'keyword', rs, re, score=50.0, detail=lt('weitere Bedingung', 'Another condition')))
        if ctx.get('has_sim') and not ctx.get('has_k'):
            out.append(
                Suggestion(
                    'k',
                    ' & k=20',
                    'snippet',
                    rs,
                    re,
                    score=49.5,
                    detail=lt('Anzahl ähnlicher Wörter', 'Number of similar words'),
                )
            )
        out.append(Suggestion(']', ']', 'keyword', rs, re, score=49.0, detail=lt('Tokenklausel schließen', 'Close token clause')))
        return out[:limit]

    if ctx['state'] == 'within_scope':
        for sc in ['s', 'doc']:
            if not prefix or sc.startswith(prefix):
                out.append(Suggestion(sc, sc, 'value', rs, re, score=50.0))
        return out[:limit]

    if ctx['state'] == 'where_field':
        keys = set()
        backend = getattr(corpus, "backend", None) if corpus is not None else None
        meta_index = getattr(backend, "meta_index", None) if backend is not None else None
        if meta_index is not None:
            keys.update(meta_index.fields.keys())
        elif corpus is not None and corpus.doc_meta:
            for m in corpus.doc_meta[: min(50, len(corpus.doc_meta))]:
                keys.update(m.keys())
        for k in sorted(keys):
            if not prefix or k.startswith(prefix):
                out.append(Suggestion(k, k, 'value', rs, re, score=20.0))
        return _rank(out)[:limit]

    if ctx['state'] == 'where_op':
        for o in language_service_meta_operators():
            if not prefix or o.startswith(prefix):
                out.append(Suggestion(o, o, 'op', rs, re, score=20.0))
        return out[:limit]

    if ctx['state'] == 'where_val':
        out.append(Suggestion('"..."', '"$1"', 'snippet', rs, re, score=5.0, detail=lt('Stringliteral', 'String literal')))
        out.append(Suggestion('123', '123', 'value', rs, re, score=4.0, detail=lt('Zahl', 'Number')))
        return out[:limit]

    return []


def _esc(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _where_example(corpus: Corpus, where_fields: Optional[Sequence[str]]) -> Optional[Tuple[str, str]]:
    """A metadata field of the corpus and its most frequent value, for where().

    The field is the first of ``where_fields`` with string values in the
    corpus metadata index. ``None`` when the corpus has no metadata index or
    none of the fields has string values.
    """
    if not where_fields:
        return None
    backend = getattr(corpus, "backend", None)
    meta_index = getattr(backend, "meta_index", None)
    fields = getattr(meta_index, "fields", None)
    if not fields:
        return None
    for name in where_fields:
        field = fields.get(name)
        if field is None:
            continue
        # Numeric-only fields have no string values to offer.
        values = field.sample_str_values()
        if values:
            # max() keeps the first of equally frequent values.
            return name, max(values, key=lambda item: item[1])[0]
    return None


def _rank(suggs: List[Suggestion]) -> List[Suggestion]:
    # Deduplicate by insert_text+range
    best: Dict[Tuple[int, int, str], Suggestion] = {}
    for s in suggs:
        k = (s.start, s.end, s.insert_text)
        cur = best.get(k)
        if cur is None or s.score > cur.score:
            best[k] = s
    out = list(best.values())
    out.sort(key=lambda s: (s.score, len(s.label)), reverse=True)
    return out


def _infer_attr_before(toks: List[Token], pos: int) -> Optional[str]:
    # Look backwards for IDENT that plausibly is an attribute.
    for t in reversed(toks):
        if t.end <= pos:
            if t.kind == 'IDENT':
                return t.value
            if t.kind in {'LBRACK', 'RBRACK', 'PIPE', 'LPAREN', 'RPAREN', 'COMMA'}:
                break
    return None


def _looks_like_within_scope(toks: List[Token], cursor: int) -> bool:
    # within ( < ...
    # Find "within" keyword before cursor without hitting a ')' first.
    seen_rparen = False
    for t in reversed(toks):
        if t.start >= cursor:
            continue
        if t.kind == 'RPAREN':
            seen_rparen = True
        if t.kind == 'KW' and t.value == 'within' and not seen_rparen:
            return True
        if t.kind == 'LPAREN' and seen_rparen:
            # we crossed a completed (...) group
            break
    return False


def _infer_context(toks: List[Token], cursor: int, corpus: Optional[Corpus] = None) -> Dict[str, Any]:
    cur = token_at(toks, cursor)
    replace_start = cursor
    replace_end = cursor
    prefix = ''
    if cur is not None and cur.start < cursor and cur.kind in {'IDENT', 'KW', 'NUMBER'}:
        replace_start = cur.start
        replace_end = cursor
        prefix = cur.value[: max(0, cursor - cur.start)]
    elif cur is None:
        # Cursor can sit exactly at token end; treat that as being "inside" for completion.
        for t in reversed(toks):
            if t.end == cursor and t.kind in {'IDENT', 'KW', 'NUMBER'}:
                replace_start = t.start
                replace_end = t.end
                prefix = t.value
                break

    # Are we inside a token clause [ ... ]?
    depth = 0
    last_lbrack = None
    for idx, t in enumerate(toks):
        if t.start >= cursor:
            break
        if t.kind == 'LBRACK':
            depth += 1
            last_lbrack = idx
        elif t.kind == 'RBRACK' and depth > 0:
            depth -= 1
            if depth == 0:
                last_lbrack = None

    if depth == 0:
        # within(<...>) scope placeholder
        if _looks_like_within_scope(toks, cursor):
            return {'state': 'within_scope', 'replace_start': replace_start, 'replace_end': replace_end, 'prefix': prefix}
        # where( meta_expr ...)
        if _looks_like_where_meta(toks, cursor):
            return _infer_where_context(toks, cursor, replace_start, replace_end, prefix)
        return {'state': 'top', 'replace_start': replace_start, 'replace_end': replace_end, 'prefix': prefix}

    seg = []
    if last_lbrack is not None:
        seg = [t for t in toks[last_lbrack + 1:] if t.start < cursor and t.kind != 'EOF']

    has_sim = _clause_has_ident(seg, 'sim')
    has_k = _clause_has_ident(seg, 'k')

    if not seg or seg[-1].kind in {'LBRACK', 'AMP'}:
        return {
            'state': 'tok_attr',
            'replace_start': replace_start,
            'replace_end': replace_end,
            'prefix': prefix,
            'has_sim': has_sim,
            'has_k': has_k,
        }

    last = seg[-1]

    # After (potential) attribute
    if last.kind == 'IDENT':
        # If the identifier already is a known attribute and the cursor is at its end,
        # suggest operators. Otherwise we assume the user is still typing the attribute name.
        known_attrs = _known_attr_names(corpus)
        if last.value.lower() in known_attrs and replace_start == last.start and replace_end >= last.end:
            return {'state': 'tok_op', 'replace_start': cursor, 'replace_end': cursor, 'prefix': '', 'attr': last.value.lower()}
        return {
            'state': 'tok_attr',
            'replace_start': replace_start,
            'replace_end': replace_end,
            'prefix': prefix,
            'has_sim': has_sim,
            'has_k': has_k,
        }

    # After op
    if last.kind == 'OP' or (last.kind == 'KW' and last.value == 'in'):
        return {'state': 'tok_val', 'replace_start': cursor, 'replace_end': cursor, 'prefix': '' , 'attr': _last_ident(seg)}

    # After value
    if last.kind in {'STRING', 'NUMBER', 'RBRACE'}:
        return {
            'state': 'tok_after_val',
            'replace_start': cursor,
            'replace_end': cursor,
            'prefix': '',
            'has_sim': has_sim,
            'has_k': has_k,
        }

    return {
        'state': 'tok_attr',
        'replace_start': replace_start,
        'replace_end': replace_end,
        'prefix': prefix,
        'has_sim': has_sim,
        'has_k': has_k,
    }


def _known_attr_names(corpus: Optional[Corpus]) -> set[str]:
    names = set(language_service_token_attributes(include_parameters=True))
    if corpus is not None:
        names.update(str(a).lower() for a in corpus.attrs.keys())
    return names


def _clause_has_ident(seg: List[Token], name: str) -> bool:
    needle = name.lower()
    for t in seg:
        if t.kind == 'IDENT' and t.value.lower() == needle:
            return True
    return False


def _last_ident(seg: List[Token]) -> Optional[str]:
    for t in reversed(seg):
        if t.kind == 'IDENT':
            return t.value
        if t.kind in {'LBRACK', 'RBRACK'}:
            break
    return None


def _looks_like_where_meta(toks: List[Token], cursor: int) -> bool:
    # Rough detection: we are inside a where( ... , ... ) and before the comma.
    seen_where = False
    depth = 0
    for t in toks:
        if t.start >= cursor:
            break
        if t.kind == 'KW' and t.value == 'where':
            seen_where = True
        if not seen_where:
            continue
        if t.kind == 'LPAREN':
            depth += 1
        elif t.kind == 'RPAREN' and depth > 0:
            depth -= 1
        elif t.kind == 'COMMA' and depth == 1:
            # comma separating meta expr and query
            return False
    return seen_where


def _infer_where_context(toks: List[Token], cursor: int, rs: int, re: int, prefix: str) -> Dict[str, Any]:
    # Minimal: field -> op -> value.
    # We find the last significant token before cursor within where(...
    # and classify.
    # This is intentionally heuristic, but stable under partial input.
    # Find last non-space token before cursor.
    prev: Optional[Token] = None
    for t in reversed(toks):
        if t.start >= cursor:
            continue
        if t.kind == 'EOF':
            continue
        prev = t
        break
    if prev is None:
        return {'state': 'where_field', 'replace_start': rs, 'replace_end': re, 'prefix': prefix}

    if prev.kind in {'LPAREN', 'AMP', 'PIPE'}:
        return {'state': 'where_field', 'replace_start': rs, 'replace_end': re, 'prefix': prefix}
    if prev.kind == 'IDENT':
        # If the cursor sits inside the field token, we complete fields.
        if rs == prev.start and re == cursor:
            return {'state': 'where_field', 'replace_start': rs, 'replace_end': re, 'prefix': prefix}
        return {'state': 'where_op', 'replace_start': cursor, 'replace_end': cursor, 'prefix': ''}
    if prev.kind == 'OP':
        return {'state': 'where_val', 'replace_start': cursor, 'replace_end': cursor, 'prefix': ''}
    if prev.kind in {'STRING', 'NUMBER'}:
        return {'state': 'where_field', 'replace_start': cursor, 'replace_end': cursor, 'prefix': ''}
    return {'state': 'where_field', 'replace_start': rs, 'replace_end': re, 'prefix': prefix}
