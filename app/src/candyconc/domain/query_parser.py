from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, TypeAlias
import re

from candyconc.core.cql_macros import normalize_query_input
from candyconc.i18n import LocalizedText, lt
from candyconc.utils.text_normalize import normalize_text_basic


def canonicalize_term(term: str) -> str:
    """Single source of truth for query-term normalization (D3).

    Applies NFKC + whitespace canonicalization (``normalize_text_basic``) and
    the CQL entry-form normalization (``normalize_query_input``) so that the
    count path and the KWIC/row path operate on byte-identical term forms.
    Crucially this maps NFD-decomposed umlauts (e.g. ``u`` + combining
    diaeresis) onto the NFC-composed forms stored in the index, so that a
    matched-row count equals the reported hit count.
    """
    if not term:
        return term
    basic = normalize_text_basic(term)
    # The CQL keywords on their own are words once a query is parsed
    # ([word=within], ran >prep where). normalize_query_input would turn them
    # into "cql:within", which matches no token.
    if basic.strip().lower() in _CQL_KEYWORD_WORDS:
        return basic.strip()
    return normalize_query_input(basic)


_CQL_KEYWORD_WORDS = frozenset({"within", "where"})


def casefold_key(term: str) -> str:
    """Single source of truth for case-INSENSITIVE term equivalence (DT-CORE-CASE-FREQ).

    This is the ONE case-folding contract shared by every case-insensitive code
    path so identical inputs give identical hit sets:

    * plain KWIC search (``CorpusIndex.term_positions(case_insensitive=True)``),
    * CQL ``%c`` literal matching (``cqlhpc.predicates._casefold_match_ids``),
    * wildcard / phrase case-insensitive matching,
    * the case-folded frequency list (``CorpusIndex.frequency_list(case_fold=True)``),
    * the collocation engine's casefold id map.

    It is ``canonicalize_term(term).lower()``. Canonicalizing first guarantees
    NFKC/NFC equivalence as well.

    ``str.lower``, not ``str.casefold``: ``"daß".casefold()`` is ``"dass"``.
    On a large German corpus a plain count for "daß" would then report
    551,103 hits against 2,994 for ``[word="daß"]``. Case is not ß against
    ss: ``str.lower`` leaves ß alone and folds the capital sharp s (U+1E9E)
    to ß. The same comparison holds at every seam above, and it agrees with
    ``re.IGNORECASE``, which also keeps ß and ss apart.
    """
    if not term:
        return term
    return canonicalize_term(term).lower()


_SIMPLE_CQL_LITERAL_RE = re.compile(
    r'^\[\s*(?:word|lemma)\s*=\s*"([^"]+)"\s*((?:%[cd]\s*)*)\]$',
    re.IGNORECASE,
)


def simple_cql_literal(term: str) -> tuple[str, bool] | None:
    """Return the literal and case-fold policy for an exact one-token CQL query."""
    raw = (term or "").strip()
    if not raw.lower().startswith("cql:"):
        return None
    match = _SIMPLE_CQL_LITERAL_RE.match(raw[4:].strip())
    if not match:
        return None
    literal = match.group(1).strip()
    if not literal:
        return None
    flags = match.group(2).casefold()
    return literal, ("%c" in flags or "%d" in flags)


def extract_simple_cql_token(term: str) -> str | None:
    """Return the literal from an exact one-token CQL query, if available."""
    parsed = simple_cql_literal(term)
    return parsed[0] if parsed is not None else None


@dataclass
class Term:
    value: str


@dataclass
class Attr:
    key: str
    value: str


@dataclass
class Not:
    node: "Node"


@dataclass
class And:
    left: "Node"
    right: "Node"


@dataclass
class Or:
    left: "Node"
    right: "Node"


@dataclass
class Near:
    left: "Node"
    right: "Node"
    distance: int


@dataclass
class Regex:
    pattern: str


@dataclass
class Wildcard:
    value: str

@dataclass
class Dependency:
    head: "Node"
    dep: "Node"
    rel: str


Node: TypeAlias = (
    Term | Attr | Not | And | Or | Near | Regex | Wildcard | Dependency
)



def _tokenise(query: str) -> List[str]:
    # Operators only as whole tokens. Without the boundary plain search reads
    # "Ordnung" as OR dnung and "notwendig" as NOT wendig: query_count fails
    # or counts the complement (55,582 instead of 5 on a small test index).
    # Single quotes enclose a word like double quotes, but only as a whole
    # token: geht's and 's stay word forms.
    pattern = re.compile(
        r"\[[^\]]+\]|\"[^\"]+\"|'[^']+'(?![^\s()])|(?:NEAR/\d+|AND|OR|NOT)(?![^\s()])|[><]|\(|\)|[^\s()]+",
        re.IGNORECASE,
    )
    return pattern.findall(query)


#: "|" is not OR in this search form. Without this hint a model read
#: "Expected )" as "there is no disjunction" and went on to count single pairs.
#: Only forms verified to count on real indexes are named, also with %c.
ODER_HINWEIS = lt(
    '. "|" verbindet CQL-Zellen: [word="a"] | [word="b"], auch geklammert, '
    'oder als Menge in einer Zelle: [word in {"a","b"}]. Beides geht mit %c. '
    "In der Wortsuche ohne Zellen heisst oder OR.",
    '. "|" joins CQL cells: [word="a"] | [word="b"], also in parentheses, '
    'or as a set in one cell: [word in {"a","b"}]. Both work with %c. '
    "In plain search without cells, write OR.",
)

#: Ein Zellenwert, der genau die Wortform trifft: keine Regex-Metazeichen,
#: keine Anfuehrungszeichen, keine Attribut- oder Abhaengigkeitsschreibweise.
_ZELLENWERT = re.compile(r'[^\s.^$*+?()\[\]{}|\\"<>=~%]+')


def folge_hinweis(tokens: List[str]) -> str | LocalizedText:
    """The counting CQL form of a word sequence without cells, or "".

    query_count("es ist wichtig") ends with "Unexpected token: ist", and
    run_cqlf_query with the same message. Without a hint a model finds the
    counting form only on a second attempt. Plain search does not read a
    word sequence as a sequence in either tool, so the message changes, not
    the meaning of the search. The form is named only when every token is a
    word that plain search reads as a word form, because only then does the
    cell match exactly that form. %c folds like plain search with
    case_insensitive.
    """
    werte: List[str] = []
    for token in tokens:
        try:
            knoten = Parser([token]).parse_primary()
        except ValueError:
            return ""
        if not isinstance(knoten, Term) or not _ZELLENWERT.fullmatch(knoten.value):
            return ""
        werte.append(knoten.value)
    if len(werte) < 2:
        return ""
    zellen = " ".join(f'[word="{wert}" %c]' for wert in werte)
    return lt(
        ". Eine Wortfolge zaehlt in CQL mit einer Zelle je Wort: {zellen}, "
        "ohne %c mit Gross- und Kleinschreibung.",
        ". A word sequence is counted in CQL with one cell per word: {zellen}. "
        "Without %c the cells match case-sensitively.",
    ).format(zellen=zellen)


_ATTRIBUTSCHREIBWEISE = re.compile(r"(word|lemma|pos|tag|morph|ent)(!=|=|~)\"?([^\"]+)\"?", re.IGNORECASE)


def wortsuche_hinweis(wortform: str) -> Optional[LocalizedText]:
    """What a word form without hits means instead of a word form, or None.

    Plain search reads every input as a word form, folded according to
    case_insensitive. "|" stays literal because word forms contain it
    (Evangelisch|er in a real index), and read as OR such a form would count
    every "er". If the literal form does not occur, it was not meant:
    (und|oder), word=und and lemma=und would silently count 0. The message
    names the form that counts.
    """
    teile = wortform.split("|")
    if len(teile) > 1 and all(t.strip() for t in teile):
        oder = " OR ".join(teile)
        zellen = " | ".join(f'[word="{t}"]' for t in teile)
        menge = ",".join(f'"{t}"' for t in teile)
        return lt(
            'Wortsuche: "{wortform}" kommt als Wortform nicht vor, "|" steht hier woertlich. '
            "Oder heisst in der Wortsuche OR: {oder}. Als CQL: {zellen} oder [word in {{{menge}}}], "
            "mit %c ohne Gross- und Kleinschreibung.",
            'Plain search: "{wortform}" does not occur as a word form, "|" is literal here. '
            "In plain search, or is written OR: {oder}. As CQL: {zellen} or [word in {{{menge}}}], "
            "with %c ignoring case.",
        ).format(wortform=wortform, oder=oder, zellen=zellen, menge=menge)
    attribut = _ATTRIBUTSCHREIBWEISE.fullmatch(wortform)
    if attribut:
        name, op, wert = attribut.groups()
        return lt(
            'Wortsuche: "{wortform}" kommt als Wortform nicht vor. Eine Attributsuche steht in '
            'eckigen Klammern, der Wert in doppelten Anfuehrungszeichen: [{name}{op}"{wert}"].',
            'Plain search: "{wortform}" does not occur as a word form. An attribute search is '
            'written in square brackets, with the value in double quotes: [{name}{op}"{wert}"].',
        ).format(wortform=wortform, name=name.lower(), op=op, wert=wert)
    return None


class Parser:
    def __init__(self, tokens: List[str]):
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> Optional[str]:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _match(self, value: str) -> bool:
        token = self._peek()
        if token and token.upper() == value:
            self.pos += 1
            return True
        return False

    def _oder_hinweis(self) -> str | LocalizedText:
        return ODER_HINWEIS if self._peek() == "|" else ""

    def _expect(self, value: str) -> None:
        if not self._match(value):
            raise ValueError(lt("Expected {value}", "Expected {value}").format(value=value) + self._oder_hinweis())

    def parse(self) -> Node:
        node = self.parse_or()
        if self._peek() is not None:
            hinweis = self._oder_hinweis() or folge_hinweis(self.tokens)
            raise ValueError(
                lt("Unexpected token: {token}", "Unexpected token: {token}").format(token=self._peek()) + hinweis
            )
        return node

    # OR is lowest precedence
    def parse_or(self) -> Node:
        node = self.parse_and()
        while self._match("OR"):
            right = self.parse_and()
            node = Or(node, right)
        return node

    def parse_and(self) -> Node:
        node = self.parse_not()
        while self._match("AND"):
            right = self.parse_not()
            node = And(node, right)
        return node

    def parse_not(self) -> Node:
        if self._match("NOT"):
            return Not(self.parse_not())
        return self.parse_near()

    def parse_dep(self) -> Node:
        node = self.parse_primary()
        token = self._peek()
        if token and (token in ("<", ">") or token.startswith("<") or token.startswith(">")):
            direction = token[0]
            rel: str
            if token in ("<", ">"):
                # relation given as separate token
                self.pos += 1
                rel_token = self._peek()
                if rel_token is None:
                    raise ValueError("Expected relation name")
                self.pos += 1
                rel = rel_token
            else:
                # token like '>rel'
                self.pos += 1
                rel = token[1:]
            right = self.parse_primary()
            if direction == ">":
                node = Dependency(node, right, rel)
            else:
                node = Dependency(right, node, rel)
        return node

    def parse_near(self) -> Node:
        node = self.parse_dep()
        while True:
            token = self._peek()
            if token and token.upper().startswith("NEAR/"):
                self.pos += 1
                distance = int(token.split("/")[1])
                right = self.parse_primary()
                node = Near(node, right, distance)
            else:
                break
        return node

    def parse_primary(self) -> Node:
        token = self._peek()
        if token is None:
            raise ValueError("Unexpected end of input")
        if token == "(":
            self.pos += 1
            node = self.parse_or()
            self._expect(")")
            return node
        if token.startswith("[") and token.endswith("]"):
            self.pos += 1
            inner = token[1:-1]
            if "=" not in inner:
                raise ValueError("Invalid attribute filter")
            key, value = inner.split("=", 1)
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            return Attr(key, canonicalize_term(value))
        if token.startswith('"') and token.endswith('"'):
            self.pos += 1
            return Term(canonicalize_term(token[1:-1]))
        if len(token) > 2 and token.startswith("'") and token.endswith("'"):
            # 'und' zaehlte als Wortform 'und' mit Apostrophen still 0.
            self.pos += 1
            return Term(canonicalize_term(token[1:-1]))
        if token.startswith('/') and token.endswith('/'):
            self.pos += 1
            return Regex(token[1:-1])
        if '*' in token or '?' in token:
            self.pos += 1
            return Wildcard(canonicalize_term(token))
        # fullmatch, nicht match: "Ordnung" beginnt mit OR und ist trotzdem ein Wort.
        if re.fullmatch(r"NEAR/\d+|AND|OR|NOT|\)|\(", token, re.IGNORECASE):
            raise ValueError(f"Unexpected token: {token}")
        self.pos += 1
        return Term(canonicalize_term(token))


def parse_query(query: str) -> Node:
    tokens = _tokenise(query)
    parser = Parser(tokens)
    return parser.parse()
