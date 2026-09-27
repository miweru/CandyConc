from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from typing import List, Optional

from .ast import Alt, Node, Quant, Seq, Tok, Where, Within
from .capabilities import Capability, capability_by_id
from .errors import BRANCH_LOCAL_WHERE as _BRANCH_LOCAL_WHERE, lt
from .lexer import lex
from .parser import parse_cql, ParseError
from .corpus import Corpus


@dataclass(frozen=True, slots=True)
class Fix:
    label: str
    start: int
    end: int
    replacement: str


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: str  # 'error'|'warning'|'info'
    message: str
    start: int
    end: int
    fixes: tuple[Fix, ...] = ()


def diagnose(text: str, corpus: Optional[Corpus] = None) -> List[Diagnostic]:
    """Parse + lexical diagnostics with quick fixes.

    This function is designed for an interactive editor: it must be cheap
    and must not throw.
    """

    diags: List[Diagnostic] = []
    toks = lex(text)

    # lexical errors
    for t in toks:
        if t.kind == 'ERROR':
            diags.append(Diagnostic(
                'error',
                lt("Unerwartetes Zeichen: {value!r}", "Unexpected character: {value!r}").format(value=t.value),
                t.start,
                t.end,
            ))

        if t.kind == 'STRING_UNTERM':
            diags.append(Diagnostic(
                'error',
                lt("Unterminierter Stringliteral", "Unterminated string literal"),
                t.start,
                t.end,
                fixes=(Fix(lt('String schließen', 'Close string'), t.end, t.end, '"'),),
            ))

    # bracket balance (cheap)
    stack: List[tuple[str, int]] = []
    for t in toks:
        if t.kind in {'LBRACK', 'LPAREN', 'LBRACE'}:
            stack.append((t.kind, t.start))
        elif t.kind in {'RBRACK', 'RPAREN', 'RBRACE'}:
            if not stack:
                diags.append(Diagnostic(
                    'error',
                    lt("Unerwartetes schließendes {value}", "Unexpected closing {value}").format(value=t.value),
                    t.start,
                    t.end,
                ))
                continue
            open_kind, open_pos = stack[-1]
            if (open_kind, t.kind) in {('LBRACK', 'RBRACK'), ('LPAREN', 'RPAREN'), ('LBRACE', 'RBRACE')}:
                stack.pop()
            else:
                diags.append(Diagnostic(
                    'error',
                    lt("Klammern sind verschachtelt/inkonsistent", "Brackets are misnested or inconsistent"),
                    open_pos,
                    t.end,
                ))
                stack.pop()

    if stack:
        # Suggest closing at end.
        closes = []
        for kind, _pos in reversed(stack):
            closes.append({
                'LBRACK': ']',
                'LPAREN': ')',
                'LBRACE': '}',
            }[kind])
        diags.append(Diagnostic(
            'error',
            lt("Fehlende schließende Klammer(n)", "Missing closing bracket(s)"),
            len(text),
            len(text),
            fixes=(Fix(lt('Klammern schließen', 'Close brackets'), len(text), len(text), ''.join(closes)),),
        ))

    diags.extend(_unsupported_syntax_capability_diagnostics(toks))

    # parse error (best effort)
    try:
        ast = parse_cql(text)
    except ParseError as e:
        diags.append(Diagnostic('error', e.reason, e.start, e.end))
        return diags
    except Exception:
        # do not crash interactive loop
        return diags

    # semantic checks
    if corpus is not None:
        # unknown attrs inside token clauses: scan tokens around patterns [ IDENT ...
        attrs = set(corpus.attrs.keys())
        extra = {"sim", "k"}
        for i, t in enumerate(toks):
            if t.kind == 'IDENT' and _is_inside_token_clause(toks, i):
                if t.value in extra:
                    continue
                if t.value not in attrs:
                    cand = get_close_matches(t.value, sorted(attrs), n=3, cutoff=0.6)
                    fixes: List[Fix] = []
                    for c in cand:
                        fixes.append(Fix(lt("Ersetze durch {name}", "Replace with {name}").format(name=c), t.start, t.end, c))
                    diags.append(Diagnostic(
                        'error',
                        lt("Unbekanntes Attribut: {name}", "Unknown attribute: {name}").format(name=t.value),
                        t.start,
                        t.end,
                        fixes=tuple(fixes),
                    ))

    diags.extend(_partial_capability_diagnostics(ast))
    if _contains_branch_local_where(ast):
        diags.append(Diagnostic(
            "error",
            _BRANCH_LOCAL_WHERE,
            0,
            len(text),
        ))

    # warning: unbounded quantifiers outside within(<s>, ...)
    if ('STAR' in {t.kind for t in toks} or 'PLUS' in {t.kind for t in toks}) and 'within' not in text:
        # Heuristic; precise analysis would require walking AST.
        diags.append(Diagnostic(
            'warning',
            lt(
                "Unbegrenzter Quantifizierer ohne within(<s>, ...) kann extrem teuer werden",
                "An unbounded quantifier without within(<s>, ...) can become extremely expensive",
            ),
            0,
            0,
            fixes=(Fix('Wrap in within(<s>, ...)', 0, 0, 'within(<s>, '), Fix(')', len(text), len(text), ')')),
        ))

    return diags


def _unsupported_syntax_capability_diagnostics(toks) -> List[Diagnostic]:
    """Surface CQLF features that the current parser/engine deliberately lacks."""

    diags: List[Diagnostic] = []
    labels_cap = capability_by_id("cqlf.level3.labels_captures")
    for i in range(len(toks) - 2):
        cur, colon, after = toks[i], toks[i + 1], toks[i + 2]
        if cur.kind == "IDENT" and colon.kind == "ERROR" and colon.value == ":" and after.kind in {"LBRACK", "LPAREN"}:
            diags.append(Diagnostic(
                "error",
                _capability_message(
                    labels_cap,
                    lt(
                        "Labels/Captures sind aktuell nicht ausführbar; die Query würde keinen belastbaren "
                        "Capture-Span für Bericht oder Replay liefern.",
                        "Labels and captures cannot be executed at present. The query would not return "
                        "a reliable capture span for a report or a replay.",
                    ),
                ),
                cur.start,
                after.end,
            ))
            break
    return diags


def _partial_capability_diagnostics(ast: Node) -> List[Diagnostic]:
    seen: set[str] = set()
    diags: List[Diagnostic] = []

    for node in _walk_ast(ast):
        if isinstance(node, Tok):
            for cond in node.clause.conds:
                if cond.op == "~":
                    _append_once(
                        diags,
                        seen,
                        "cqlf.level2.operator.regex",
                        lt(
                            "Regex ist implementiert, aber noch nur teilweise konformitaetsgetestet; grosse Muster "
                            "werden durch Lexikon- und Frequenzlimits begrenzt.",
                            "Regex is implemented but so far only partly conformance-tested. Large patterns "
                            "are bounded by lexicon and frequency limits.",
                        ),
                    )
        elif isinstance(node, Quant):
            _append_once(
                diags,
                seen,
                "cqlf.level2.quantifiers",
                lt(
                    "Quantifizierer und bounded gaps sind implementiert, aber noch nicht vollständig als "
                    "Level-2-Conformance geschlossen.",
                    "Quantifiers and bounded gaps are implemented but not yet fully closed as "
                    "level 2 conformance.",
                ),
            )
        elif isinstance(node, Where):
            _append_once(
                diags,
                seen,
                "cqlf.level2.where.metadata",
                lt(
                    "where()-Metadatenfilter benötigen einen Fast-Index-Meta-Index; fehlende Indexartefakte "
                    "müssen hart sichtbar werden.",
                    "where() metadata filters require a metadata index. Missing index artifacts "
                    "must be unmistakably visible.",
                ),
            )

    return diags


def _append_once(diags: List[Diagnostic], seen: set[str], capability_id: str, detail: str) -> None:
    if capability_id in seen:
        return
    seen.add(capability_id)
    cap = capability_by_id(capability_id)
    severity = "warning" if cap.execution == "partial" else "info"
    diags.append(Diagnostic(severity, _capability_message(cap, detail), 0, 0))


def _capability_message(capability: Capability, detail: str) -> str:
    return lt(
        "[{id}] CQLF Level {level}: {title} - {detail}",
        "[{id}] CQLF level {level}: {title}. {detail}",
    ).format(id=capability.id, level=capability.level, title=capability.title, detail=detail)


def _walk_ast(node: Node):
    yield node
    if isinstance(node, Seq):
        for part in node.parts:
            yield from _walk_ast(part)
    elif isinstance(node, Alt):
        for option in node.options:
            yield from _walk_ast(option)
    elif isinstance(node, Quant):
        yield from _walk_ast(node.node)
    elif isinstance(node, Where):
        yield from _walk_ast(node.node)
    elif isinstance(node, Within):
        yield from _walk_ast(node.node)


def _contains_branch_local_where(node: Node) -> bool:
    n = node
    while isinstance(n, (Where, Within)):
        n = n.node
    return _contains_where(n)


def _contains_where(node: Node) -> bool:
    if isinstance(node, Where):
        return True
    if isinstance(node, Seq):
        return any(_contains_where(part) for part in node.parts)
    if isinstance(node, Alt):
        return any(_contains_where(option) for option in node.options)
    if isinstance(node, Quant):
        return _contains_where(node.node)
    if isinstance(node, Within):
        return _contains_where(node.node)
    return False


def _is_inside_token_clause(toks, idx: int) -> bool:
    # quick heuristic: find nearest '[' before token without a matching ']' in between.
    depth = 0
    for j in range(idx, -1, -1):
        if toks[j].kind == 'RBRACK':
            depth += 1
        elif toks[j].kind == 'LBRACK':
            if depth == 0:
                return True
            depth -= 1
    return False
