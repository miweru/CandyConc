from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Literal


CapabilityStatus = Literal["supported", "partial", "planned", "unsupported", "not_applicable"]
CapabilityLevel = Literal[1, 2, 3]
CQLF_CAPABILITY_CONTRACT_VERSION = "cqlf-capabilities-v1"
CQLF_CURRENT_LEVEL = "2-"


@dataclass(frozen=True, slots=True)
class CapabilitySnippet:
    insert_text: str
    detail: str


@dataclass(frozen=True, slots=True)
class Capability:
    """Machine-readable CQLF contract for parser, engine, tooling, and Copilot."""

    id: str
    title: str
    level: CapabilityLevel
    syntax: CapabilityStatus
    execution: CapabilityStatus
    diagnostics: CapabilityStatus
    explain: CapabilityStatus
    tests: CapabilityStatus
    ast_nodes: tuple[str, ...] = ()
    token_operators: tuple[str, ...] = ()
    meta_operators: tuple[str, ...] = ()
    token_attributes: tuple[str, ...] = ()
    language_service_attributes: tuple[str, ...] = ()
    language_service_parameters: tuple[str, ...] = ()
    snippets: tuple[CapabilitySnippet, ...] = ()
    requires: tuple[str, ...] = ()
    limits: tuple[str, ...] = ()
    notes: str = ""

    @property
    def is_declared_supported(self) -> bool:
        """True only when the feature is executable and covered by tests."""

        return (
            self.syntax in {"supported", "not_applicable"}
            and self.execution == "supported"
            and self.tests == "supported"
        )


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        id="cqlf.level1.token_clause",
        title="Token clauses",
        level=1,
        syntax="supported",
        execution="supported",
        diagnostics="supported",
        explain="partial",
        tests="supported",
        ast_nodes=("Tok", "TokenClause", "Cond"),
        notes="Basic bracketed token conditions are the foundation for KWIC queries.",
    ),
    Capability(
        id="cqlf.level1.token_attributes.core",
        title="Core token attributes",
        level=1,
        syntax="supported",
        execution="supported",
        diagnostics="partial",
        explain="partial",
        tests="supported",
        token_attributes=("word", "lemma", "pos"),
        snippets=(
            CapabilitySnippet('[lemma="$1"]', "Token: lemma equals"),
            CapabilitySnippet('[word="$1"]', "Token: word equals"),
            CapabilitySnippet('[pos="$1"]', "Token: pos equals"),
        ),
        requires=("Fast Index token attributes",),
        limits=("Corpus/index must expose the queried attribute.",),
        notes="word, lemma, and pos are treated as the stable core attribute set.",
    ),
    Capability(
        id="cqlf.level1.operator.equals",
        title="Equality operator",
        level=1,
        syntax="supported",
        execution="supported",
        diagnostics="supported",
        explain="partial",
        tests="supported",
        token_operators=("=",),
    ),
    Capability(
        id="cqlf.level1.sequence",
        title="Token sequences",
        level=1,
        syntax="supported",
        execution="supported",
        diagnostics="supported",
        explain="partial",
        tests="supported",
        ast_nodes=("Seq",),
        notes="Simple sequences can use shifted postings intersection.",
    ),
    Capability(
        id="cqlf.level2.token_attributes.extended",
        title="Extended token attributes",
        level=2,
        syntax="supported",
        execution="partial",
        diagnostics="partial",
        explain="partial",
        tests="partial",
        token_attributes=("ent", "ner"),
        requires=("Corpus/index must expose the queried extended attribute.",),
        limits=("Extended attributes are optional and corpus-specific.",),
        notes="Autocomplete keeps common entity attributes visible, but execution depends on index availability.",
    ),
    Capability(
        id="cqlf.level1.kwic",
        title="KWIC rendering for CQL hits",
        level=1,
        syntax="not_applicable",
        execution="supported",
        diagnostics="not_applicable",
        explain="partial",
        tests="partial",
        notes="KWIC is a product behavior built on match arrays, not a syntax node.",
    ),
    Capability(
        id="cqlf.level2.operator.not_equals",
        title="Negated equality operator",
        level=2,
        syntax="supported",
        execution="supported",
        diagnostics="supported",
        explain="partial",
        tests="supported",
        token_operators=("!=",),
        limits=(
            "A value with an unescaped regular expression character is rejected: "
            "a negated regular expression is not executed.",
        ),
    ),
    Capability(
        id="cqlf.level2.operator.regex",
        title="Regex token operator",
        level=2,
        syntax="supported",
        execution="partial",
        diagnostics="partial",
        explain="partial",
        tests="partial",
        token_operators=("~",),
        requires=("Fast Index lexicon regex lookup",),
        limits=("Regex execution is bounded by max type and max frequency limits.",),
        notes="Implemented, but still needs per-attribute conformance coverage.",
    ),
    Capability(
        id="cqlf.level2.case_insensitive_flag",
        title="Case-insensitive value flag (%c)",
        level=2,
        syntax="supported",
        execution="supported",
        diagnostics="partial",
        explain="partial",
        tests="supported",
        token_operators=("=", "!=", "in", "~"),
        snippets=(
            CapabilitySnippet('[word="$1"%c]', "Token: word equals (case-insensitive)"),
        ),
        limits=(
            "Applies to =, !=, in and ~ (regex). With != it excludes every "
            "spelling of the value.",
            "%d (diacritic fold) is rejected at parse time and never "
            "silently collapsed to %c.",
        ),
        notes=(
            "IMS-CWB-style trailing flag: `[word=\"merkel\"%c]` matches merkel, "
            "Merkel, MERKEL (lowercase comparison, ß and ss stay distinct). "
            "Default matching stays case-sensitive."
        ),
    ),
    Capability(
        id="cqlf.level2.semantic_similarity_macro",
        title="Semantic similarity macro",
        level=2,
        syntax="supported",
        execution="partial",
        diagnostics="partial",
        explain="partial",
        tests="partial",
        language_service_attributes=("sim",),
        language_service_parameters=("k",),
        snippets=(CapabilitySnippet('[sim="$1"&k=20]', "Token: semantic similarity"),),
        requires=("CandyConc sim macro expansion", "Semantic search artifacts"),
        limits=("Expanded to a concrete word-in set before CQLHPC execution.",),
        notes="This is a CandyConc macro surfaced in CQL tooling, not a native CQLHPC predicate.",
    ),
    Capability(
        id="cqlf.level2.operator.in_set",
        title="Set membership operator",
        level=2,
        syntax="supported",
        execution="supported",
        diagnostics="supported",
        explain="partial",
        tests="supported",
        token_operators=("in",),
        snippets=(CapabilitySnippet('[lemma in {"$1","$2"}]', "Token: lemma set"),),
    ),
    Capability(
        id="cqlf.level2.token_clause.any_token",
        title="Empty token clause (any token)",
        level=2,
        syntax="supported",
        execution="supported",
        diagnostics="supported",
        explain="partial",
        tests="supported",
        ast_nodes=("TokenClause",),
        snippets=(
            CapabilitySnippet("[]", "Token: any token (wildcard)"),
            CapabilitySnippet("[]{1,3}", "Gap: 1 to 3 arbitrary tokens"),
        ),
        notes=(
            "`[]` matches any single token; combined with quantifiers it expresses "
            "gap queries such as `[word=\"x\"] []{1,3} [word=\"y\"]`."
        ),
    ),
    Capability(
        id="cqlf.level2.token_clause.conjunction",
        title="Conjunctive token conditions",
        level=2,
        syntax="supported",
        execution="supported",
        diagnostics="supported",
        explain="partial",
        tests="supported",
        token_operators=("&",),
        notes="`&` combines multiple conditions inside one token clause.",
    ),
    Capability(
        id="cqlf.level2.grouping",
        title="Grouping",
        level=2,
        syntax="supported",
        execution="supported",
        diagnostics="supported",
        explain="partial",
        tests="supported",
        snippets=(CapabilitySnippet("($1)", "Group"),),
    ),
    Capability(
        id="cqlf.level2.alternation",
        title="Alternation",
        level=2,
        syntax="supported",
        execution="supported",
        diagnostics="supported",
        explain="partial",
        tests="supported",
        ast_nodes=("Alt",),
    ),
    Capability(
        id="cqlf.level2.quantifiers",
        title="Quantifiers and bounded gaps",
        level=2,
        syntax="supported",
        execution="partial",
        diagnostics="partial",
        explain="partial",
        tests="partial",
        ast_nodes=("Quant",),
        limits=("Unbounded quantifiers need scope warnings and execution guards.",),
        notes="Parser covers ?, *, +, {m}, {m,n}, {m,}; execution needs a full conformance matrix.",
    ),
    Capability(
        id="cqlf.level2.within",
        title="Sentence/document scope with within()",
        level=2,
        syntax="supported",
        execution="supported",
        diagnostics="supported",
        explain="partial",
        # tests/core/test_cqlf_within_conformance.py is the test matrix. It
        # counts by hand on a twelve-token index that the default is
        # sentence-internal, that <s> repeats it and that <doc> relaxes it.
        #
        # Why this matters: only capabilities that are supported in ALL
        # dimensions go into the example syntax of the system prompt. With
        # tests="partial" a model wrote "Die CQL-Abfrage dieses Motors kann es
        # nicht" and fell back to position arithmetic, a factor of three (12
        # against 38 instances).
        tests="supported",
        ast_nodes=("Within",),
        snippets=(
            CapabilitySnippet("within(<s>, $1)", "Wrapper: within sentence"),
            # Der WICHTIGERE der beiden: <s> ist die Vorgabe, <doc> ist die
            # einzige Art, ueber eine Satzgrenze zu suchen.
            CapabilitySnippet("within(<doc>, $1)", "Wrapper: across sentences"),
        ),
        requires=("Sentence/document boundaries",),
        limits=("Currently scoped to <s> and <doc>.",),
    ),
    Capability(
        id="cqlf.level2.where.metadata",
        title="Metadata filters with where()",
        level=2,
        syntax="supported",
        execution="supported",
        diagnostics="partial",
        explain="partial",
        # tests/core/test_cqlf_where_conformance.py checks counts and denominators
        # on a four-document, two-register fixture, including both nestings with
        # within(<doc>, ...). A missing metadata index raises an error. Mark the
        # operator supported so the system prompt includes its executable syntax.
        tests="supported",
        ast_nodes=("Where", "MetaExpr", "MetaCond"),
        # Diese sechs sind die Flaeche, die der PARSER fuehrt
        # (parser.py:456), und der Deckungstest prueft genau das
        # (test_cqlf_capabilities.py: cover_current_parser_operators).
        # Ausfuehrbar sind vier. Alle sechs sind gemessen, in
        # tests/core/test_cqlf_where_conformance.py (WhereOperatoren),
        # und die zwei Befunde stehen unten in limits.
        meta_operators=("=", "!=", ">=", "<=", ">", "<"),
        # KONKRETE Bedingung statt where($1, $2). Letzteres rendert zu
        # "where(x, y)" und verschweigt, dass das erste Argument feld="wert"
        # ist. Der Feldname ist beispielhaft, welche Felder es gibt steht in
        # ui_context, und der Prompt verlangt zwei Zeilen weiter genau das.
        snippets=(
            CapabilitySnippet(
                'where(model="x", $1)', "Wrapper: metadata filter + query"
            ),
        ),
        requires=("Fast Index Meta Index",),
        # Alle vier Zeilen sind gemessen (test_cqlf_where_conformance.py).
        # Die dritte Zeile der Vorfassung sagte dasselbe wie die erste noch
        # einmal aus der Gegenrichtung und ist deshalb weg. Die letzten
        # beiden sind neu und halten die Operatorenbefunde fest: sie stehen
        # HIER, weil die Liste sechs Operatoren an die
        # Autovervollstaendigung weitergibt und vier davon tragen.
        limits=(
            "where(...) must wrap the whole query. Branch-local where(...) raises.",
            "Missing Meta Index raises instead of silently counting the full corpus.",
            "Only = and != execute. Ordering needs numeric meta values, and the "
            "build path stores every metadata column as a string.",
            "> and < never reach the meta parser: the lexer maps them to "
            "LANGLE/RANGLE for region syntax.",
        ),
    ),
    Capability(
        id="cqlf.level2.normalization",
        title="Stable query normalization",
        level=2,
        syntax="not_applicable",
        execution="supported",
        diagnostics="not_applicable",
        explain="partial",
        tests="supported",
        notes="Normalization stabilizes cache keys, planning, and builder output.",
    ),
    Capability(
        id="cqlf.level2.builder_roundtrip",
        title="Builder JSON round-trip",
        level=2,
        syntax="not_applicable",
        execution="supported",
        diagnostics="not_applicable",
        explain="partial",
        tests="supported",
    ),
    Capability(
        id="cqlf.level2.language_service",
        title="Autocomplete and diagnostics",
        level=2,
        syntax="not_applicable",
        execution="not_applicable",
        diagnostics="partial",
        explain="partial",
        tests="partial",
        notes="Language-service behavior exists but is not yet fully generated from this contract.",
    ),
    Capability(
        id="cqlf.level2.query_trace",
        title="Structured query trace",
        level=2,
        syntax="not_applicable",
        execution="partial",
        diagnostics="not_applicable",
        explain="planned",
        tests="unsupported",
        notes="Needed for replay, analysis reports, and virtual cursor grounding.",
    ),
    Capability(
        id="cqlf.level3.capability_negotiation",
        title="Backend capability negotiation",
        level=3,
        syntax="not_applicable",
        execution="planned",
        diagnostics="planned",
        explain="planned",
        tests="unsupported",
        notes="The present module is the first local contract; backend negotiation is not implemented yet.",
    ),
    Capability(
        id="cqlf.level3.engine_independent_ir",
        title="Engine-independent CQLF IR",
        level=3,
        syntax="planned",
        execution="planned",
        diagnostics="planned",
        explain="planned",
        tests="unsupported",
        notes="CQLHPC is still the semantic center; an engine-independent IR is future work.",
    ),
    Capability(
        id="cqlf.level3.labels_captures",
        title="Labels and captures",
        level=3,
        syntax="unsupported",
        execution="unsupported",
        diagnostics="planned",
        explain="planned",
        tests="unsupported",
        notes="Required before reports can reference named spans produced by one query.",
    ),
    Capability(
        id="cqlf.level3.capture_constraints",
        title="Capture constraints",
        level=3,
        syntax="unsupported",
        execution="unsupported",
        diagnostics="planned",
        explain="planned",
        tests="unsupported",
        notes="Depends on labels/captures and a verifier that returns capture spans.",
    ),
    Capability(
        id="cqlf.level3.region_algebra",
        title="Structural region algebra",
        level=3,
        syntax="unsupported",
        execution="unsupported",
        diagnostics="planned",
        explain="planned",
        tests="unsupported",
        requires=("General structural-region index",),
        notes="Current scope support is limited to sentence/document boundaries.",
    ),
)


def all_capabilities() -> tuple[Capability, ...]:
    return CAPABILITIES


def capability_ids() -> tuple[str, ...]:
    return tuple(cap.id for cap in CAPABILITIES)


def capability_by_id(capability_id: str) -> Capability:
    for cap in CAPABILITIES:
        if cap.id == capability_id:
            return cap
    raise KeyError(f"unknown CQLF capability: {capability_id}")


def capabilities_by_level(level: CapabilityLevel) -> tuple[Capability, ...]:
    return tuple(cap for cap in CAPABILITIES if cap.level == level)


def capabilities_covering_ast_node(node_name: str) -> tuple[Capability, ...]:
    return tuple(cap for cap in CAPABILITIES if node_name in cap.ast_nodes)


def covered_ast_nodes() -> frozenset[str]:
    return frozenset(_flatten(cap.ast_nodes for cap in CAPABILITIES))


def covered_token_operators() -> frozenset[str]:
    return frozenset(_flatten(cap.token_operators for cap in CAPABILITIES))


def covered_meta_operators() -> frozenset[str]:
    return frozenset(_flatten(cap.meta_operators for cap in CAPABILITIES))


def supported_capabilities() -> tuple[Capability, ...]:
    return tuple(cap for cap in CAPABILITIES if cap.is_declared_supported)


def language_service_snippets() -> tuple[CapabilitySnippet, ...]:
    return tuple(snippet for cap in CAPABILITIES for snippet in cap.snippets if cap.syntax == "supported")


def language_service_token_attributes(*, include_parameters: bool = False) -> tuple[str, ...]:
    attrs: list[str] = []
    for cap in CAPABILITIES:
        if cap.syntax != "supported":
            continue
        attrs.extend(cap.token_attributes)
        attrs.extend(cap.language_service_attributes)
        if include_parameters:
            attrs.extend(cap.language_service_parameters)
    return _unique_preserving_order(attrs)


def language_service_token_operators() -> tuple[str, ...]:
    return _ordered_subset(covered_token_operators() - {"&"}, ("=", "!=", "~", "in"))


def language_service_meta_operators() -> tuple[str, ...]:
    return _ordered_subset(covered_meta_operators(), ("=", "!=", ">=", "<=", ">", "<"))


def build_cqlf_capability_contract() -> dict[str, object]:
    capabilities = [_capability_payload(cap) for cap in CAPABILITIES]
    fingerprint_payload = {
        "version": CQLF_CAPABILITY_CONTRACT_VERSION,
        "current_level": CQLF_CURRENT_LEVEL,
        "capabilities": capabilities,
    }
    encoded = json.dumps(
        fingerprint_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        **fingerprint_payload,
        "fingerprint_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def copilot_cqlf_capability_summary() -> str:
    contract = build_cqlf_capability_contract()
    supported_set = {cap.id for cap in supported_capabilities()}
    partial = [
        cap.id
        for cap in CAPABILITIES
        if cap.syntax == "supported"
        and cap.id not in supported_set
        and (cap.execution in {"supported", "partial"} or cap.tests != "supported")
    ]
    # SYNTAX STATT NAMEN.
    #
    # A user dictated a query literally: "das Wort nicht unmittelbar gefolgt
    # von nur, dann bis zu acht beliebige Token, dann sondern unmittelbar
    # gefolgt von auch". When quantifiers appear in this text only as
    # identifiers in a list called "Partial/guarded", without a single line
    # of syntax, the model answers with 0 hits and thus claims that the
    # construction does not occur. On the same index
    #
    #     [word="nicht"] [word="nur"] []{0,8} [word="sondern"] [word="auch"]
    #
    # returns 45,599 hits in 3.7 seconds. The engine can answer the question,
    # but the model cannot ASK it without the syntax.
    #
    # The snippets live in the registry (cqlf.level2.token_clause.any_token
    # has "[]{1,3}" with an explanation), and the generator renders them.
    #
    # OFFSET, not appended: the system prompt has a hard character budget,
    # and prompt size is paid in every prefill. Two lines are dropped in
    # return, both duplicates. The Level 3 list names five identifiers for
    # things that the prompt forbids three lines further down, in German and
    # more completely ("Erfinde keine Labels, Captures, Capture-Constraints
    # oder Region-Algebra"), and the English sentence below it says literally
    # the same again.
    beispiele = [
        snippet.insert_text.replace("$1", "x").replace("$2", "y")
        for cap in CAPABILITIES
        if cap.id in supported_set
        for snippet in (cap.snippets or ())
    ]
    lines = [
        f"CQLF capability contract: {contract['version']} ({str(contract['fingerprint_sha256'])[:12]})",
        f"Current claimed level: {contract['current_level']} (early Level 2; do not claim Level 3).",
        # Die Liste der UNTERSTUETZTEN Bezeichner faellt weg: die
        # Beispielsyntax eine Zeile tiefer zeigt dieselben Faehigkeiten in
        # einer Form, die das Modell benutzen kann. Die PARTIAL-Liste bleibt,
        # ihre Eintraege haben keine Schnipsel und tragen eine Warnung.
        "Partial/guarded CQLF capabilities: " + ", ".join(partial),
        "Beispielsyntax: " + "  ".join(beispiele),
        'Abstand NUR mit Quantor: [word="a"] []{1,8} [word="b"] = a und b mit '
        "1 bis 8 Token dazwischen. Ohne Quantor findet die Sequenz nur den "
        "direkten Anschluss.",
        # WARUM DIESE ZEILE UNVERZICHTBAR IST. Die Engine liefert
        # leftmost-longest NICHT UEBERLAPPENDE Treffer (nfa.py:
        # find_nonoverlapping_matches). Ein breiteres Fenster kann deshalb
        # WENIGER Treffer ergeben: der linke Treffer wird laenger und
        # verschluckt einen rechten Kandidaten. Gemessen auf einem
        # Miniaturkorpus: {0,3} liefert 4, {0,4} liefert 3. Ohne diese Zeile
        # liest ein Modell die sinkende Zahl als "die Konstruktion wird
        # seltener", und das waere eine erfundene Entwicklung.
        "Treffer sind leftmost-longest und ueberlappen nie. Ein groesseres "
        "Fenster kann daher WENIGER Treffer liefern, weil ein linker Treffer "
        "laenger wird und einen rechten verschluckt. Eine Zahl ist immer eine "
        "Zahl NICHT UEBERLAPPENDER Vorkommen, nie die aller Paare.",
        "Use only corpus_attributes that are visible in ui_context; otherwise use plain-text search.",
    ]
    return "\n".join(lines)


def capabilities_markdown_table(capabilities: Iterable[Capability] = CAPABILITIES) -> str:
    header = "| ID | Level | Syntax | Execution | Diagnostics | Explain | Tests |\n"
    sep = "| --- | --- | --- | --- | --- | --- | --- |\n"
    rows = [
        (
            f"| `{cap.id}` | {cap.level} | {cap.syntax} | {cap.execution} | "
            f"{cap.diagnostics} | {cap.explain} | {cap.tests} |"
        )
        for cap in capabilities
    ]
    return header + sep + "\n".join(rows)


def _flatten(groups: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(item for group in groups for item in group)


def _capability_payload(cap: Capability) -> dict[str, object]:
    return {
        "id": cap.id,
        "title": cap.title,
        "level": cap.level,
        "syntax": cap.syntax,
        "execution": cap.execution,
        "diagnostics": cap.diagnostics,
        "explain": cap.explain,
        "tests": cap.tests,
        "ast_nodes": list(cap.ast_nodes),
        "token_operators": list(cap.token_operators),
        "meta_operators": list(cap.meta_operators),
        "token_attributes": list(cap.token_attributes),
        "language_service_attributes": list(cap.language_service_attributes),
        "language_service_parameters": list(cap.language_service_parameters),
        "snippets": [
            {"insert_text": snippet.insert_text, "detail": snippet.detail}
            for snippet in cap.snippets
        ],
        "requires": list(cap.requires),
        "limits": list(cap.limits),
        "notes": cap.notes,
    }


def _ordered_subset(values: Iterable[str], preferred_order: tuple[str, ...]) -> tuple[str, ...]:
    value_set = set(values)
    ordered = [value for value in preferred_order if value in value_set]
    ordered.extend(sorted(value for value in value_set if value not in preferred_order))
    return tuple(ordered)


def _unique_preserving_order(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return tuple(out)
