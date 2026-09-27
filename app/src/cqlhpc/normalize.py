from __future__ import annotations

from typing import List, Tuple

from .ast import Alt, MetaCond, MetaExpr, Node, Quant, Seq, Tok, TokenClause, Within, Where


def normalize(node: Node) -> Node:
    """Return a canonicalized AST.

    Goals:
    - stable cache keys
    - deterministic builder JSON
    - simplification: flatten nested seq/alt, sort alts, sort clause conditions

    NOTE: This normalization is deliberately conservative.
    """

    if isinstance(node, Tok):
        # Sort conditions in a stable way (flags participate so a %c condition
        # is distinct from its case-sensitive twin).
        conds = tuple(
            sorted(
                node.clause.conds,
                key=lambda c: (c.attr, c.op, _value_key(c.value), getattr(c, "flags", "")),
            )
        )
        return Tok(clause=TokenClause(conds=conds))

    if isinstance(node, Seq):
        parts: List[Node] = []
        for p in node.parts:
            pn = normalize(p)
            if isinstance(pn, Seq):
                parts.extend(pn.parts)
            else:
                parts.append(pn)
        if len(parts) == 1:
            return parts[0]
        return Seq(parts=tuple(parts))

    if isinstance(node, Alt):
        opts: List[Node] = []
        for o in node.options:
            on = normalize(o)
            if isinstance(on, Alt):
                opts.extend(on.options)
            else:
                opts.append(on)
        # Sort by a simple structural key
        opts_sorted = tuple(sorted(opts, key=_node_key))
        if len(opts_sorted) == 1:
            return opts_sorted[0]
        return Alt(options=opts_sorted)

    if isinstance(node, Quant):
        inner = normalize(node.node)
        # normalize quant forms
        m, n = node.m, node.n
        if n is not None and n < m:
            # keep as-is; evaluation will yield no matches.
            return Quant(node=inner, m=m, n=n)
        return Quant(node=inner, m=m, n=n)

    if isinstance(node, Within):
        return Within(scope=node.scope, node=normalize(node.node))

    if isinstance(node, Where):
        return Where(expr=_norm_meta(node.expr), node=normalize(node.node))

    raise TypeError(f"unsupported node: {type(node)}")


def _norm_meta(expr: MetaExpr) -> MetaExpr:
    if expr.kind == 'cond':
        # single MetaCond
        return expr
    parts: List[object] = []
    for p in expr.parts:
        if isinstance(p, MetaExpr):
            parts.append(_norm_meta(p))
        else:
            parts.append(p)
    # flatten and/or of same kind
    flat: List[object] = []
    for p in parts:
        if isinstance(p, MetaExpr) and p.kind == expr.kind:
            flat.extend(p.parts)
        else:
            flat.append(p)
    # sort for deterministic form
    flat_sorted = tuple(sorted(flat, key=_meta_part_key))
    return MetaExpr(kind=expr.kind, parts=flat_sorted)


def _meta_part_key(p: object) -> Tuple:
    if isinstance(p, MetaExpr):
        return ('expr', p.kind, tuple(_meta_part_key(x) for x in p.parts))
    assert isinstance(p, MetaCond)
    return ('cond', p.field, p.op, _value_key(p.value))


def _value_key(v) -> Tuple:
    if isinstance(v, list):
        return ('set', tuple(sorted((_value_key(x) for x in v))))
    if isinstance(v, str):
        return ('str', v)
    if isinstance(v, (int, float)):
        return ('num', float(v))
    return ('other', repr(v))


def _node_key(n: Node) -> Tuple:
    if isinstance(n, Tok):
        return ('tok', tuple((c.attr, c.op, _value_key(c.value), getattr(c, "flags", "")) for c in n.clause.conds))
    if isinstance(n, Seq):
        return ('seq', tuple(_node_key(p) for p in n.parts))
    if isinstance(n, Alt):
        return ('alt', tuple(_node_key(o) for o in n.options))
    if isinstance(n, Quant):
        return ('q', n.m, n.n, _node_key(n.node))
    if isinstance(n, Within):
        return ('within', n.scope, _node_key(n.node))
    if isinstance(n, Where):
        return ('where', _meta_part_key(n.expr), _node_key(n.node))
    return ('unknown',)
