from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from .ast import (
    Alt,
    Cond,
    MetaCond,
    MetaExpr,
    Node,
    Quant,
    Seq,
    Tok,
    TokenClause,
    Within,
    Where,
    normalize_meta_value,
)
from . import config
from .errors import lt
from .lexer import Token, lex

# Hard cap on a {m,n} repetition count. An unbounded count (e.g. {0,2000} or the
# 1e26 that int(float(...)) happily parses) blows up NFA construction
# (O(states^2) with Python bignum bitmasks) and hangs the worker. 256 is far
# above any realistic linguistic pattern.
MAX_QUANT_REPEAT = 256

# Default budget for the *product* of nested quantifier upper bounds. A single
# ``{256}`` is fine, but ``([]{200}){164}`` expands to 200*164 = 32 800 token
# instances during the Thompson NFA build -- O(states^2) with Python bignum
# bitmasks -- and hangs the worker (and overflows the int edge tables). We
# estimate the expansion *cheaply at parse time* and reject before any NFA work
# starts. The same ceiling is mirrored as MAX_NFA_PREDS in compile_nfa as a
# defence-in-depth backstop. 2000 is ~8x the largest single-quantifier pattern
# and far above any realistic linguistic query.
DEFAULT_MAX_QUANT_EXPANSION = 2000


def _max_quant_expansion() -> int:
    """Configurable ceiling on the product of nested quantifier upper bounds."""
    return config.get_int("CQLHPC_MAX_QUANT_EXPANSION", DEFAULT_MAX_QUANT_EXPANSION)


def _token_expansion(node: Node) -> int:
    """Estimate how many token *instances* ``node`` expands to in the NFA build.

    This is a cheap upper bound on the work ``_build_thompson`` will do: each
    ``Tok`` is one instance, a sequence/alternation sums its children, and a
    quantifier multiplies its child by its (upper) repeat count. Unbounded
    quantifiers (``*``/``+``/``{m,}``) count as ``m`` for the mandatory copies
    plus one for the looping body -- the loop itself is O(1) extra states, so it
    never drives the blow-up; only *nested bounded* quantifiers multiply.

    Returns a non-negative int; the caller compares it against the expansion
    budget. The estimate is intentionally an over-approximation so it can never
    let a genuinely explosive pattern through.
    """
    if isinstance(node, Tok):
        return 1
    if isinstance(node, Seq):
        return sum(_token_expansion(p) for p in node.parts)
    if isinstance(node, Alt):
        return sum(_token_expansion(o) for o in node.options)
    if isinstance(node, Quant):
        inner = _token_expansion(node.node)
        reps = node.n if node.n is not None else node.m
        # Unbounded with m==0 (``*``) still needs one body copy for the loop.
        reps = max(int(reps), 1)
        return inner * reps
    if isinstance(node, (Within, Where)):
        return _token_expansion(node.node)
    return 1


def _parse_quant_int(tok: Token) -> int:
    """Parse a quantifier bound as a strict non-negative integer.

    The lexer also uses NUMBER for metadata values, so decimal tokens are
    intentionally rejected here instead of changing tokenization globally.
    """
    if not tok.value.isascii() or not tok.value.isdigit():
        raise ParseError(
            lt(
                "Ungültige Wiederholungszahl {value!r}: nur ganze Zahlen sind erlaubt.",
                "Invalid repetition count {value!r}: only whole numbers are allowed.",
            ).format(value=tok.value),
            tok.start,
            tok.end,
        )
    normalized = tok.value.lstrip("0") or "0"
    limit_text = str(MAX_QUANT_REPEAT)
    if len(normalized) > len(limit_text) or (
        len(normalized) == len(limit_text) and normalized > limit_text
    ):
        raise ParseError(
            lt(
                "Wiederholungszahl {value!r} überschreitet das Limit ({limit}).",
                "Repetition count {value!r} exceeds the limit ({limit}).",
            ).format(value=tok.value, limit=MAX_QUANT_REPEAT),
            tok.start,
            tok.end,
        )
    return int(normalized)


_PARSE_ERROR = lt(
    "CQL Parse Fehler: {reason} at {start}:{end}",
    "CQL parse error: {reason} at {start}:{end}",
)


class ParseError(ValueError):
    """A malformed-CQL error.

    Subclasses ``ValueError`` (not just ``Exception``) on purpose: every caller
    that already guards CQL execution with ``except (RuntimeError, ValueError)``
    — including the synchronous ``/query`` server path — must treat a malformed
    query as a *user* error (HTTP 400), not an unhandled crash (HTTP 500).
    Before this, ``ParseError`` derived from bare ``Exception`` and slipped past
    those handlers on the sync path while the stream/``/analyse`` paths caught
    it via their diagnostics flow.

    The rendered string is prefixed with ``CQL Parse Fehler:`` so message-based
    user-error classifiers (which look for ``Parse`` in the text) route it to a
    400 as well. The ``start``/``end`` spans remain available for diagnostics.

    ``reason`` is the bare parser message (German and English pair where the
    parser has one), used by the editor diagnostics. ``message`` is the full
    rendered text as a German and English pair, so
    ``candyconc.i18n.exception_text(exc)`` gives a route both languages while
    ``str(exc)`` stays the German text.
    """

    def __init__(self, reason: str, start: int, end: int) -> None:
        super().__init__(reason, start, end)
        self.reason = reason
        self.start = start
        self.end = end
        self.message = _PARSE_ERROR.format(reason=reason, start=start, end=end)

    def __str__(self) -> str:
        return str.__str__(self.message)


class Parser:
    def __init__(self, tokens: Sequence[Token]):
        self.toks = tokens
        self.i = 0

    def peek(self) -> Token:
        return self.toks[self.i]

    def eat(self, kind: str, value: Optional[str] = None) -> Token:
        t = self.peek()
        if t.kind != kind:
            raise ParseError(f"expected {kind}, got {t.kind}", t.start, t.end)
        if value is not None and t.value != value:
            raise ParseError(f"expected {value}, got {t.value}", t.start, t.end)
        self.i += 1
        return t

    def accept(self, kind: str, value: Optional[str] = None) -> Optional[Token]:
        t = self.peek()
        if t.kind != kind:
            return None
        if value is not None and t.value != value:
            return None
        self.i += 1
        return t

    def parse(self) -> Node:
        n = self.parse_expr()
        self.eat('EOF')
        return n

    # expr := seq ( '|' seq )*
    def parse_expr(self) -> Node:
        parts = [self.parse_seq()]
        while self.accept('PIPE'):
            parts.append(self.parse_seq())
        if len(parts) == 1:
            return parts[0]
        return Alt(options=tuple(parts))

    # seq := term+
    def parse_seq(self) -> Node:
        terms: List[Node] = []
        while True:
            t = self.peek()
            if t.kind in {'EOF', 'PIPE', 'RPAREN', 'RBRACK'}:
                break
            if t.kind == 'COMMA':
                break
            terms.append(self.parse_term())
        if not terms:
            t0 = self.peek()
            raise ParseError("empty sequence", t0.start, t0.end)
        if len(terms) == 1:
            return terms[0]
        return Seq(parts=tuple(terms))

    # term := factor quant?
    def parse_term(self) -> Node:
        f = self.parse_factor()
        t = self.peek()
        if t.kind in {'QMARK', 'STAR', 'PLUS', 'LBRACE'}:
            start = t.start
            m, n = self.parse_quant()
            node = Quant(node=f, m=m, n=n)
            # Cheaply reject explosive *nested* quantifiers (e.g. ``([]{200}){164}``)
            # before any NFA work: the product of inner repeats times the outer
            # repeat blows up the Thompson build. The {m,n}-range check already
            # caps a single quantifier at MAX_QUANT_REPEAT; this catches the
            # multiplicative case the range check cannot see.
            budget = _max_quant_expansion()
            expansion = _token_expansion(node)
            if expansion > budget:
                end = self.toks[self.i - 1].end if self.i > 0 else start
                raise ParseError(
                    lt(
                        "Muster zu komplex: verschachtelte Wiederholungen erzeugen "
                        "~{expansion} Token-Instanzen (Limit {budget}). Bitte die "
                        "Wiederholungszahlen verkleinern.",
                        "Pattern too complex: nested repetitions produce "
                        "~{expansion} token instances (limit {budget}). Reduce "
                        "the repetition counts.",
                    ).format(expansion=expansion, budget=budget),
                    start,
                    end,
                )
            return node
        return f

    def parse_quant(self) -> Tuple[int, int | None]:
        if self.accept('QMARK'):
            return 0, 1
        if self.accept('STAR'):
            return 0, None
        if self.accept('PLUS'):
            return 1, None
        lb = self.eat('LBRACE')
        # ``{,n}`` shorthand: a comma immediately after ``{`` means a lower bound
        # of 0 (i.e. ``{0,n}``), matching the IMS-CWB / regex convention.
        if self.peek().kind == 'COMMA':
            m = 0
        else:
            m_tok = self.eat('NUMBER')
            m = _parse_quant_int(m_tok)
        if self.accept('COMMA'):
            if self.peek().kind == 'NUMBER':
                n_tok = self.eat('NUMBER')
                n = _parse_quant_int(n_tok)
            else:
                n = None
        else:
            n = m
        rb = self.eat('RBRACE')
        if m < 0 or m > MAX_QUANT_REPEAT or (n is not None and n > MAX_QUANT_REPEAT):
            raise ParseError(
                lt(
                    "Wiederholung {{{m},{n}}} überschreitet das "
                    "Limit ({limit}). Bitte kleinere Wiederholungszahlen verwenden.",
                    "Repetition {{{m},{n}}} exceeds the "
                    "limit ({limit}). Use smaller repetition counts.",
                ).format(m=m, n='' if n is None else n, limit=MAX_QUANT_REPEAT),
                lb.start, rb.end,
            )
        if n is not None and n < m:
            raise ParseError(
                lt(
                    "Ungültige Wiederholung {{{m},{n}}}: Obergrenze < Untergrenze.",
                    "Invalid repetition {{{m},{n}}}: upper bound < lower bound.",
                ).format(m=m, n=n),
                lb.start, rb.end,
            )
        return m, n

    # factor := tok_clause | '(' expr ')' | within_call | where_call
    def parse_factor(self) -> Node:
        t = self.peek()
        if t.kind == 'LBRACK':
            return Tok(clause=self.parse_tok_clause())
        if t.kind == 'LPAREN':
            self.eat('LPAREN')
            inner = self.parse_expr()
            self.eat('RPAREN')
            return inner
        if t.kind == 'KW' and t.value == 'within':
            return self.parse_within()
        if t.kind == 'KW' and t.value == 'where':
            return self.parse_where()
        raise ParseError(f"unexpected token {t.kind}:{t.value}", t.start, t.end)

    def parse_tok_clause(self) -> TokenClause:
        self.eat('LBRACK')
        # ``[]`` is the idiomatic "any token" wildcard (matches every token).
        # An empty clause compiles to a zero-condition predicate, which the NFA
        # runner already treats as universally true, so ``[] []{1,3}`` gap
        # queries work without engine changes.
        if self.peek().kind == 'RBRACK':
            self.eat('RBRACK')
            return TokenClause(conds=())
        conds = [self.parse_cond()]
        while self.accept('AMP'):
            conds.append(self.parse_cond())
        self.eat('RBRACK')
        return TokenClause(conds=tuple(conds))

    def parse_cond(self) -> Cond:
        attr_tok = self.eat('IDENT')
        t = self.peek()
        if t.kind == 'KW' and t.value == 'in':
            self.eat('KW', 'in')
            vals = self.parse_set_literal()
            flags = self.parse_value_flags()
            return Cond(attr=attr_tok.value, op='in', value=vals, flags=flags)
        op_tok = self.eat('OP')
        val = self.parse_value()
        flags = self.parse_value_flags()
        return Cond(attr=attr_tok.value, op=op_tok.value, value=val, flags=flags)

    def parse_value_flags(self) -> str:
        """Parse optional trailing value flags.

        ``%c`` requests a case-folded comparison and is the only executable
        flag of this engine. ``%d`` requests diacritic folding, which NO code
        path here performs.

        Folding ``%d`` silently into ``"c"`` would give a user of the usual
        CQP notation a plausible number that contains only case folding. On
        a 273-million-token corpus the difference is large: ``.*flucht.*``
        finds 9,667, the character class variant ``.*fl[uü]cht.*`` finds
        47,533. A number silently too small by a factor of five is worse than
        an error because it looks right.

        The message must not suggest the ASCII transliteration of ``ü``
        inside a character class. Inside ``[...]`` the class ``[uue]`` is the
        SET {u, e} and contains no ``ü``, so it yields the same silently too
        small number. On a small test index ``.*flucht.*`` finds 7 hits,
        ``.*fl[uue]cht.*`` 8 (the only gain: Verflechtungen) and
        ``.*fl[uü]cht.*`` 76. The ASCII transliteration convention ends at
        the boundary of a character class.

        Therefore ``%d`` is REJECTED here instead of folded. Repeated ``c``
        flags still collapse into a single ``"c"``.
        """
        gesehen = ""
        erstes: Optional[Token] = None
        letztes: Optional[Token] = None
        while True:
            ftok = self.accept('FLAG')
            if ftok is None:
                break
            if erstes is None:
                erstes = ftok
            letztes = ftok
            gesehen += str(ftok.value or "")
        if "d" in gesehen and erstes is not None and letztes is not None:
            raise ParseError(
                lt(
                    "%d (Diakritika-Faltung) wird von dieser Engine nicht "
                    "ausgefuehrt und deshalb nicht akzeptiert. Diakritika-"
                    "unempfindlich sucht man mit ~ und einer Zeichenklasse, die "
                    "den Umlaut SELBST enthaelt, etwa "
                    '[word~".*fl[uü]cht.*"%c].',
                    "%d (diacritic folding) is not executed by this engine "
                    "and is therefore not accepted. To search regardless of "
                    "diacritics, use ~ with a character class that contains "
                    "the umlaut ITSELF, for example "
                    '[word~".*fl[uü]cht.*"%c].',
                ),
                erstes.start,
                letztes.end,
            )
        return "c" if "c" in gesehen else ""

    def parse_set_literal(self) -> Tuple[Any, ...]:
        # A nested set would end in a TOKEN condition as "TypeError:
        # unhashable type: 'list'", a raw Python error instead of an input
        # message. The check therefore sits here, at the shared entry of both
        # condition kinds, not only at the meta condition.
        #
        # The outer set is returned as a tuple, immutable and hashable.
        # ``Cond`` is a frozen dataclass that serves as a cache key (ast.py:
        # "plain string so the field stays hashable for cache keys"). Hashing
        # happens only in the memo of the sentence filter, so a list would
        # pass without sentence context and fail only inside one. The four
        # places in predicates.py that check for ``list`` accept both
        # sequence types.
        lbrace = self.eat('LBRACE')
        vals: List[Any] = []
        if self.peek().kind != 'RBRACE':
            vals.append(self.parse_value())
            while self.accept('COMMA'):
                vals.append(self.parse_value())
        self.eat('RBRACE')
        if any(isinstance(v, (list, tuple, set)) for v in vals):
            raise ParseError(
                lt(
                    "verschachtelte Wertmenge: {…} darf nur Skalare enthalten.",
                    "nested value set: {…} may only contain scalars.",
                ),
                lbrace.start,
                lbrace.end,
            )
        return tuple(vals)

    def parse_value(self) -> Any:
        t = self.peek()
        if t.kind == 'STRING':
            self.i += 1
            return t.value
        if t.kind == 'NUMBER':
            self.i += 1
            try:
                return float(t.value) if '.' in t.value else int(t.value)
            except ValueError as exc:
                # Keep the complete malformed literal as the diagnostic span,
                # but never leak Python's conversion error through query routes.
                raise ParseError(
                    lt("ungültige Zahl {value!r}", "invalid number {value!r}").format(value=t.value),
                    t.start,
                    t.end,
                ) from exc
        if t.kind == 'LBRACE':
            return self.parse_set_literal()
        raise ParseError(f"expected value, got {t.kind}:{t.value}", t.start, t.end)

    # The single accepted structural-scope form. Surfaced in every ``within``
    # diagnostic so a user who tried a near-miss (``within s`` / ``within <s>`` /
    # ``[...] within s``) gets ONE consistent, actionable message instead of the
    # old grab-bag of contradictory low-level token errors (finding 20).
    _WITHIN_FORM_HINT = lt(
        "within(...) erwartet die Form within(<s>, <Muster>) oder "
        "within(<doc>, <Muster>), z.B. within(<s>, [pos=\"NOUN\"])",
        "within(...) expects the form within(<s>, <pattern>) or "
        "within(<doc>, <pattern>), e.g. within(<s>, [pos=\"NOUN\"])",
    )

    def parse_within(self) -> Node:
        kw = self.eat('KW', 'within')
        if self.peek().kind != 'LPAREN':
            t = self.peek()
            raise ParseError(self._WITHIN_FORM_HINT, kw.start, t.end)
        self.eat('LPAREN')
        if self.peek().kind != 'LANGLE':
            t = self.peek()
            raise ParseError(self._WITHIN_FORM_HINT, kw.start, t.end)
        self.eat('LANGLE')
        scope_tok = self.eat('IDENT')
        self.eat('RANGLE')
        if self.peek().kind != 'COMMA':
            t = self.peek()
            raise ParseError(self._WITHIN_FORM_HINT, kw.start, t.end)
        self.eat('COMMA')
        inner = self.parse_expr()
        self.eat('RPAREN')
        scope = scope_tok.value
        if scope not in {'s', 'doc'}:
            raise ParseError(
                lt(
                    "within-Scope muss <s> oder <doc> sein. {hint}",
                    "The within scope must be <s> or <doc>. {hint}",
                ).format(hint=self._WITHIN_FORM_HINT),
                scope_tok.start,
                scope_tok.end,
            )
        return Within(scope=scope, node=inner)

    def parse_where(self) -> Node:
        self.eat('KW', 'where')
        self.eat('LPAREN')
        meta = self.parse_meta_expr()
        self.eat('COMMA')
        inner = self.parse_expr()
        self.eat('RPAREN')
        return Where(expr=meta, node=inner)

    # Metadata boolean expression: meta_or
    def parse_meta_expr(self) -> MetaExpr:
        return self.parse_meta_or()

    def parse_meta_or(self) -> MetaExpr:
        parts = [self.parse_meta_and()]
        while self.accept('PIPE'):
            parts.append(self.parse_meta_and())
        if len(parts) == 1:
            return parts[0]
        return MetaExpr(kind='or', parts=tuple(parts))

    def parse_meta_and(self) -> MetaExpr:
        parts = [self.parse_meta_atom()]
        while self.accept('AMP'):
            parts.append(self.parse_meta_atom())
        if len(parts) == 1:
            return parts[0]
        return MetaExpr(kind='and', parts=tuple(parts))

    def parse_meta_atom(self) -> MetaExpr:
        if self.accept('LPAREN'):
            inner = self.parse_meta_or()
            self.eat('RPAREN')
            return inner
        c = self.parse_meta_cond()
        return MetaExpr(kind='cond', parts=(c,))

    def parse_meta_cond(self) -> MetaCond:
        field_tok = self.eat('IDENT')
        op_tok = self.eat('OP')
        val = self.parse_value()
        if op_tok.value not in {'=', '!=', '>=', '<=', '>', '<'}:
            raise ParseError("invalid meta operator", op_tok.start, op_tok.end)
        # THE SAME value normalization as on the dict input. The where()
        # input builds MetaCond directly from the source text and passes it
        # via QueryEngine to THE SAME MetaIndex fast path, past all three
        # guards of the dict input. Without normalization a space in the
        # value is fatal there, on a small test index:
        #     where(split="test",  [word="und"])   197
        #     where(split="test ", [word="und"])     0
        #     where(split!="test ",[word="und"])   797  (the WHOLE result)
        # On a 142M-token index where(register!="encyclopedia ", ...) would
        # return 80,572 instead of 58,996, i.e. everything.
        # ``parse_value`` returns THREE shapes: string, number and set
        # literal, and all three are normalized (a string-only normalization
        # would keep the space in ``where(split={"test "}, ...)``).
        # parse_set_literal catches nested sets for BOTH condition kinds. The
        # dict input rejects them via pruefe_filterform. Here they would
        # become [['a'], 'b']: the set branch then compares a field against
        # a LIST, which never matches, and the filter would silently
        # restrict to 'b' only.
        normalisiert = normalize_meta_value(val)
        if normalisiert is None and isinstance(val, str):
            # Leerer oder reiner Leerraum-Skalar. Dieselbe Sorte wie die
            # leere Menge: er sieht aus wie ein Filter und schraenkt
            # nichts sinnvoll ein.
            raise ParseError(
                lt(
                    "leerer Wert: schraenkt nichts ein. Entweder einen Wert "
                    "angeben oder die Bedingung weglassen.",
                    "empty value: restricts nothing. Either give a value "
                    "or leave out the condition.",
                ),
                field_tok.start,
                field_tok.end,
            )
        if normalisiert is None and isinstance(val, (list, tuple, set)):
            # An EMPTY set is the same error as an empty list on the dict
            # input, which ``pruefe_filterform`` rejects there. Accepted here,
            # ``!=`` would turn it into the WHOLE corpus:
            # where(split!={}, [word="und"]) gives 797 of 797 hits on a small
            # test index, where(split={}, ...) zero. A filter that restricts
            # nothing looks like one.
            raise ParseError(
                lt(
                    "leere Wertmenge: {} schraenkt nichts ein. Entweder Werte "
                    "angeben oder die Bedingung weglassen.",
                    "empty value set: {} restricts nothing. Either give values "
                    "or leave out the condition.",
                ),
                field_tok.start,
                field_tok.end,
            )
        if normalisiert is not None:
            val = normalisiert
        return MetaCond(field=field_tok.value, op=op_tok.value, value=val)


def parse_cql(text: str) -> Node:
    return Parser(lex(text)).parse()
