from __future__ import annotations

from typing import Any, Dict, Optional

from .ast import Alt, Cond, MetaCond, MetaExpr, Node, Quant, Seq, Tok, TokenClause, Within, Where


def to_builder_json(node: Node) -> Dict[str, Any]:
    """Convert an AST into a drag-and-drop-friendly JSON structure.

    The JSON is deterministic for a normalized AST: node ids are assigned by
    preorder numbering.
    """

    counter = 0

    def new_id() -> str:
        nonlocal counter
        counter += 1
        return f"n{counter}"

    def enc(n: Node) -> Dict[str, Any]:
        nid = new_id()
        if isinstance(n, Tok):
            return {
                "id": nid,
                "type": "tok",
                "conds": [
                    {"attr": c.attr, "op": c.op, "value": c.value, "flags": c.flags}
                    for c in n.clause.conds
                ],
            }
        if isinstance(n, Seq):
            return {"id": nid, "type": "seq", "parts": [enc(p) for p in n.parts]}
        if isinstance(n, Alt):
            return {"id": nid, "type": "alt", "options": [enc(o) for o in n.options]}
        if isinstance(n, Quant):
            return {"id": nid, "type": "quant", "m": n.m, "n": n.n, "node": enc(n.node)}
        if isinstance(n, Within):
            return {"id": nid, "type": "within", "scope": n.scope, "node": enc(n.node)}
        if isinstance(n, Where):
            return {"id": nid, "type": "where", "expr": _enc_meta(n.expr), "node": enc(n.node)}
        raise TypeError(type(n))

    return enc(node)


def from_builder_json(obj: Dict[str, Any]) -> Node:
    t = obj.get("type")
    if t == "tok":
        conds = []
        for c in obj.get("conds", []):
            conds.append(
                Cond(
                    attr=c["attr"],
                    op=c["op"],
                    value=c.get("value"),
                    flags=c.get("flags", ""),
                )
            )
        return Tok(clause=TokenClause(conds=tuple(conds)))
    if t == "seq":
        return Seq(parts=tuple(from_builder_json(p) for p in obj.get("parts", [])))
    if t == "alt":
        return Alt(options=tuple(from_builder_json(o) for o in obj.get("options", [])))
    if t == "quant":
        return Quant(node=from_builder_json(obj["node"]), m=int(obj.get("m", 0)), n=obj.get("n"))
    if t == "within":
        return Within(scope=str(obj.get("scope", "s")), node=from_builder_json(obj["node"]
        ))
    if t == "where":
        return Where(expr=_dec_meta(obj.get("expr", {})), node=from_builder_json(obj["node"]))
    raise ValueError(f"unknown builder node type: {t}")


def to_cql(node: Node) -> str:
    """Pretty-printer for AST -> CQL string."""
    return _node_to_cql(node, context="root")


def _node_to_cql(node: Node, *, context: str) -> str:
    if isinstance(node, Tok):
        return "[" + " & ".join(_cond_to_cql(c) for c in node.clause.conds) + "]"
    if isinstance(node, Seq):
        rendered = " ".join(_node_to_cql(p, context="seq") for p in node.parts)
        return f"({rendered})" if context == "quant" else rendered
    if isinstance(node, Alt):
        rendered = " | ".join(_node_to_cql(o, context="root") for o in node.options)
        return f"({rendered})"
    if isinstance(node, Quant):
        inner = _node_to_cql(node.node, context="quant")
        q = _quant_to_cql(node.m, node.n)
        return inner + q
    if isinstance(node, Within):
        return f"within(<{node.scope}>, {_node_to_cql(node.node, context='root')})"
    if isinstance(node, Where):
        return f"where({_meta_to_cql(node.expr)}, {_node_to_cql(node.node, context='root')})"
    raise TypeError(type(node))


def _cond_to_cql(c: Cond) -> str:
    flag = f" %{c.flags}" if getattr(c, "flags", "") else ""
    if c.op == 'in':
        vals = ", ".join(_val_to_cql(v) for v in (c.value or []))
        return f"{c.attr} in {{{vals}}}{flag}"
    return f"{c.attr}{c.op}{_val_to_cql(c.value)}{flag}"


def _val_to_cql(v: Any) -> str:
    if isinstance(v, str):
        return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(v, list):
        inner = ", ".join(_val_to_cql(x) for x in v)
        return "{" + inner + "}"
    return str(v)


def _quant_to_cql(m: int, n: Optional[int]) -> str:
    if m == 0 and n == 1:
        return "?"
    if m == 0 and n is None:
        return "*"
    if m == 1 and n is None:
        return "+"
    if n is None:
        return f"{{{m},}}"
    if m == n:
        return f"{{{m}}}"
    return f"{{{m},{n}}}"


def _enc_meta(expr: MetaExpr) -> Dict[str, Any]:
    if expr.kind == 'cond':
        c = expr.parts[0]
        assert isinstance(c, MetaCond)
        return {"kind": "cond", "field": c.field, "op": c.op, "value": c.value}
    return {"kind": expr.kind, "parts": [_enc_meta(p) if isinstance(p, MetaExpr) else {"kind": "cond", "field": p.field, "op": p.op, "value": p.value} for p in expr.parts]}


def _dec_meta(obj: Dict[str, Any]) -> MetaExpr:
    kind = obj.get("kind", "cond")
    if kind == "cond":
        return MetaExpr(kind='cond', parts=(MetaCond(field=obj.get("field", ""), op=obj.get("op", "="), value=obj.get("value")),))
    parts = []
    for p in obj.get("parts", []):
        if p.get("kind") == "cond":
            parts.append(MetaCond(field=p.get("field", ""), op=p.get("op", "="), value=p.get("value")))
        else:
            parts.append(_dec_meta(p))
    return MetaExpr(kind=kind, parts=tuple(parts))


def _meta_to_cql(expr: MetaExpr) -> str:
    if expr.kind == 'cond':
        c = expr.parts[0]
        assert isinstance(c, MetaCond)
        return f"{c.field}{c.op}{_val_to_cql(c.value)}"
    op = " & " if expr.kind == 'and' else " | "
    rendered = []
    for p in expr.parts:
        if isinstance(p, MetaExpr):
            if p.kind != 'cond' and p.kind != expr.kind:
                rendered.append(f"({_meta_to_cql(p)})")
            else:
                rendered.append(_meta_to_cql(p))
        else:
            rendered.append(f"{p.field}{p.op}{_val_to_cql(p.value)}")
    return op.join(rendered)
