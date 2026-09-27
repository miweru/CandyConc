from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str
    start: int
    end: int


_SINGLE = {
    '[': 'LBRACK',
    ']': 'RBRACK',
    '(': 'LPAREN',
    ')': 'RPAREN',
    '{': 'LBRACE',
    '}': 'RBRACE',
    '|': 'PIPE',
    '&': 'AMP',
    ',': 'COMMA',
    '?': 'QMARK',
    '*': 'STAR',
    '+': 'PLUS',
    '<': 'LANGLE',
    '>': 'RANGLE',
}


def lex(text: str) -> List[Token]:
    """Tolerant lexer for CQL.

    Design constraints:
    - Must never throw on partial input.
    - Unterminated strings are returned as STRING_UNTERM so the language service
      can offer a fix.
    - Unknown characters become ERROR tokens (also useful for diagnostics).
    """

    toks: List[Token] = []
    i = 0
    n = len(text)

    def add(kind: str, value: str, s: int, e: int) -> None:
        toks.append(Token(kind=kind, value=value, start=s, end=e))

    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue

        # 2-char operators
        if ch == '!' and i + 1 < n and text[i + 1] == '=':
            add('OP', '!=', i, i + 2)
            i += 2
            continue
        if ch == '>' and i + 1 < n and text[i + 1] == '=':
            add('OP', '>=', i, i + 2)
            i += 2
            continue
        if ch == '<' and i + 1 < n and text[i + 1] == '=':
            add('OP', '<=', i, i + 2)
            i += 2
            continue

        if ch in _SINGLE:
            add(_SINGLE[ch], ch, i, i + 1)
            i += 1
            continue

        # Read a run of CWB value flags as one lowercase token so %cd combines
        # case and diacritic folding. A bare % remains an error token. Flag-like
        # text inside string literals is handled by the string branch.
        if ch == '%':
            j = i + 1
            while j < n and text[j] in {'c', 'd', 'C', 'D'}:
                j += 1
            if j > i + 1:
                add('FLAG', text[i + 1:j].lower(), i, j)
                i = j
                continue
            add('ERROR', ch, i, i + 1)
            i += 1
            continue

        # 1-char operators
        if ch in {'=', '~', '>', '<'}:
            add('OP', ch, i, i + 1)
            i += 1
            continue

        # string literal "..."
        if ch == '"':
            s = i
            i += 1
            buf: List[str] = []
            escaped = False
            while i < n:
                c = text[i]
                if escaped:
                    # Only ``\"`` and ``\\`` are consumed as string-syntax
                    # escapes (embedded quote / literal backslash). Every other
                    # escape sequence is a regex/value escape (``\d``, ``\w``,
                    # ``\.`` …) and MUST keep its backslash so it reaches the
                    # matcher intact.
                    if c == '"' or c == '\\':
                        buf.append(c)
                    else:
                        buf.append('\\')
                        buf.append(c)
                    escaped = False
                    i += 1
                    continue
                if c == '\\':
                    escaped = True
                    i += 1
                    continue
                if c == '"':
                    i += 1
                    add('STRING', ''.join(buf), s, i)
                    break
                buf.append(c)
                i += 1
            else:
                add('STRING_UNTERM', ''.join(buf), s, n)
            continue

        # number
        if ch.isdigit():
            s = i
            i += 1
            while i < n and (text[i].isdigit() or text[i] == '.'):
                i += 1
            add('NUMBER', text[s:i], s, i)
            continue

        # identifier / keyword
        if ch.isalpha() or ch in {'_', '-'}:
            s = i
            i += 1
            while i < n and (text[i].isalnum() or text[i] in {'_', '-', '.'}):
                i += 1
            val = text[s:i]
            kind = 'IDENT'
            if val in {'within', 'where', 'in'}:
                kind = 'KW'
            add(kind, val, s, i)
            continue

        add('ERROR', ch, i, i + 1)
        i += 1

    add('EOF', '', n, n)
    return toks


def token_at(tokens: List[Token], pos: int) -> Optional[Token]:
    for t in tokens:
        if t.start <= pos < t.end:
            return t
    return None
