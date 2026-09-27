from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Tuple, Union


# --- Token clause -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Cond:
    """A single condition inside a token clause.

    Examples:
        lemma = "gehen"
        pos in {"NN","NE"}
        word != "der"

    Operators:
        '=' | '!=' | '~' | 'in'

    Flags:
        ``flags`` carries IMS-CWB-style trailing modifiers on the value.
        Currently only ``"c"`` (case-insensitive, ``%c``) is recognised; an
        empty string means the default, case-sensitive matching. Kept as a
        plain string so the field stays hashable for cache keys and frozen.

    Notes:
        This reference keeps the operator set small on purpose.
    """

    attr: str
    op: str
    value: Any
    flags: str = ""


@dataclass(frozen=True, slots=True)
class TokenClause:
    conds: Tuple[Cond, ...]


@dataclass(frozen=True, slots=True)
class Tok:
    clause: TokenClause


# --- Structural nodes -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Seq:
    parts: Tuple["Node", ...]


@dataclass(frozen=True, slots=True)
class Alt:
    options: Tuple["Node", ...]


@dataclass(frozen=True, slots=True)
class Quant:
    node: "Node"
    m: int
    n: int | None


@dataclass(frozen=True, slots=True)
class Within:
    scope: str  # 's' or 'doc'
    node: "Node"


# --- Metadata expression (WHERE) -------------------------------------------


def normalize_meta_value(value: Any) -> Any:
    """EINE Wertnormalisierung fuer JEDEN Eingang einer Metabedingung.

    Sie lag in ``candyconc.core.meta_filters`` und damit oberhalb des
    Parsers, der sie deshalb nicht benutzen konnte. Der ``where()``-Eingang
    hat sich seinen eigenen Streifen gebaut, der nur Zeichenketten
    abdeckte, waehrend ``parse_value`` DREI Gestalten liefert: Zeichenkette,
    Zahl und Mengenliteral. Getrennte Implementierungen derselben Regel
    laufen auseinander, das ist hier zweimal passiert. Sie liegt jetzt im
    AST-Modul, das jeder Auswerter ohnehin importiert.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (list, tuple, set)):
        out: list[Any] = []
        for item in value:
            normalized = normalize_meta_value(item)
            if normalized is not None:
                out.append(normalized)
        return out or None
    return value


def meta_cond_menge(cond: "MetaCond") -> Union[list, None]:
    """Die Werte einer Mengenbedingung, oder None bei einem Skalar.

    ``where(split={"test","train"}, ...)`` means membership. Treating the
    list like a scalar would make ``mask_for_cond`` compare against
    ``str(["test"])``, i.e. against ``"['test']"``, and ``_eval_meta_cond``
    against the list itself. Neither ever matches a document. On a small
    test index:

        where(split="test",    [word="und"])   262
        where(split={"test"},  [word="und"])     0
        where(split!={"test "},[word="und"])   797  (the WHOLE result)

    That is the class "a filter does nothing and reports success", and with
    ``!=`` it returns the full number, which looks like a result. The dict
    input folds a list into an OR of equalities (``build_meta_expr``). The
    set notation means the same and is evaluated the same way.
    """
    if isinstance(cond.value, (list, tuple, set)):
        return [v for v in cond.value]
    return None


@dataclass(frozen=True, slots=True)
class MetaCond:
    field: str
    op: str  # '=', '!=', '>=', '<=', '>', '<'
    value: Any


@dataclass(frozen=True, slots=True)
class MetaExpr:
    kind: str  # 'cond'|'and'|'or'
    parts: Tuple[Union["MetaExpr", MetaCond], ...]


@dataclass(frozen=True, slots=True)
class Where:
    expr: MetaExpr
    node: "Node"


Node = Union[Tok, Seq, Alt, Quant, Within, Where]
