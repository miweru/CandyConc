from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal


class OperationRunSnapshot(BaseModel):
    """Observable lifecycle snapshot for backend-owned ProductOperations."""

    run_id: str = Field(..., description="Stable operation-run identifier.")
    job_id: str = Field(..., description="Compatibility alias for lifecycle consumers expecting a job id.")
    operation_id: str = Field(..., description="ProductOperation that owns this run.")
    source_id: str = Field(..., description="Operation-specific source or target id.")
    kind: str = Field(default="operation")
    label: str = Field(default="")
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "stale"]
    phase: str = Field(default="")
    progress: Optional[int] = Field(default=None, ge=0, le=100)
    message: str = Field(default="")
    error: Optional[str] = None
    result_ref: Optional[str] = None
    readiness: str = Field(default="pending")
    warnings: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    finished_at: Optional[str] = None


class OperationRunLaunchResponse(BaseModel):
    """Acknowledgement returned by long-running operation start endpoints."""

    status: Literal["queued"]
    run_id: str
    job_id: str
    status_url: str
    operation_id: str


class LoginRequest(BaseModel):
    username: str = Field(..., description="User name.", examples=["admin"])
    password: str = Field(..., description="Password.", examples=["********"])


class AuthSessionResponse(BaseModel):
    schema_version: str = Field(default="auth-session-v1")
    authenticated: bool
    token_present: bool
    username: Optional[str] = None
    role: Optional[str] = None
    effective_role: Optional[str] = None
    rbac_enabled: bool
    security_mode: str
    release_mode: bool
    unsafe_token_transport: bool
    dev_token_available: bool
    can_access_all_roles: bool


class ProductCapabilityBackendRouteDescriptorResponse(BaseModel):
    path: str
    methods: List[Literal["GET", "POST", "PUT", "PATCH", "DELETE", "WS"]]
    mutates: bool = False
    requires_corpus_features: List[str] = Field(default_factory=list)
    access: Optional[Literal["public", "user", "manager", "admin", "owner_or_admin"]] = None
    required_role: Optional[str] = None
    transport: Literal["http", "websocket"] = "http"
    route_class: Optional[
        Literal[
            "product_surface",
            "admin_surface",
            "infrastructure",
            "deprecated",
            "unclassified",
        ]
    ] = None


class ProductOperationLifecycleResponse(BaseModel):
    kind: Literal["analysis_job", "corpus_import_job", "system_status_job", "websocket_job", "operation_run"]
    job_id_field: str
    status_operation_id: str = ""
    cancel_operation_id: str = ""
    rows_operation_id: str = ""
    reports_operation_id: str = ""
    status_url_field: str = ""
    rows_url_field: str = ""
    websocket_url_field: str = ""
    polling: Literal["http_poll", "websocket", "none"]
    status_field: str = "status"
    progress_field: str = "progress"
    message_field: str = "message"
    error_field: str = "error"
    rows_state_field: str = ""
    readiness_field: str = ""
    warnings_field: str = ""
    result_available_field: str = ""
    result_discarded_field: str = ""
    result_discard_reason_field: str = ""
    terminal_statuses: List[str] = Field(default_factory=list)


class ProductCapabilityOperationResponse(BaseModel):
    id: str
    capability_id: str
    label: str
    description: str = ""
    route: ProductCapabilityBackendRouteDescriptorResponse
    effects: List[Literal["read", "write", "destructive", "long_running"]] = Field(default_factory=list)
    copilot_tools: List[str] = Field(default_factory=list)
    surface_slot: str = ""
    priority: int = 100
    input_schema_ref: str = ""
    required_context: List[str] = Field(default_factory=list)
    response_shape: Literal["data", "job", "stream", "file", "image", "void", "mixed", "unknown"] = "data"
    run_semantics: Literal[
        "instant",
        "bounded_sync",
        "job_lifecycle",
        "stream",
        "file_export",
        "fire_and_forget",
    ] = "instant"
    ui_execution_policy: Literal["contextual_ui", "confirmed_contextual_ui", "none"] = "contextual_ui"
    requires_parameters: bool = True
    lifecycle: Optional[ProductOperationLifecycleResponse] = None


class ProductCapabilityResponse(BaseModel):
    id: str
    title: str
    area: str
    maturity: Literal["stable", "guarded", "experimental", "planned", "unsupported"]
    visibility: Literal["first_class_ui", "expert_api", "hidden_experimental"]
    backend_routes: List[str] = Field(default_factory=list)
    backend_route_descriptors: List[ProductCapabilityBackendRouteDescriptorResponse] = Field(default_factory=list)
    operations: List[ProductCapabilityOperationResponse] = Field(default_factory=list)
    action_types: List[str] = Field(default_factory=list)
    copilot_tools: List[str] = Field(default_factory=list)
    preconditions: List[str] = Field(default_factory=list)
    requires_corpus_features: List[str] = Field(default_factory=list)
    limits: List[str] = Field(default_factory=list)
    notes: str = ""


class ProductCqlfCapabilitySnippetResponse(BaseModel):
    insert_text: str
    detail: str


class ProductCqlfCapabilityResponse(BaseModel):
    id: str
    title: str
    level: Literal[1, 2, 3]
    syntax: Literal["supported", "partial", "planned", "unsupported", "not_applicable"]
    execution: Literal["supported", "partial", "planned", "unsupported", "not_applicable"]
    diagnostics: Literal["supported", "partial", "planned", "unsupported", "not_applicable"]
    explain: Literal["supported", "partial", "planned", "unsupported", "not_applicable"]
    tests: Literal["supported", "partial", "planned", "unsupported", "not_applicable"]
    ast_nodes: List[str] = Field(default_factory=list)
    token_operators: List[str] = Field(default_factory=list)
    meta_operators: List[str] = Field(default_factory=list)
    token_attributes: List[str] = Field(default_factory=list)
    language_service_attributes: List[str] = Field(default_factory=list)
    language_service_parameters: List[str] = Field(default_factory=list)
    snippets: List[ProductCqlfCapabilitySnippetResponse] = Field(default_factory=list)
    requires: List[str] = Field(default_factory=list)
    limits: List[str] = Field(default_factory=list)
    notes: str = ""


class ProductCqlfCapabilityContractResponse(BaseModel):
    version: str
    current_level: str
    fingerprint_sha256: str
    capabilities: List[ProductCqlfCapabilityResponse] = Field(default_factory=list)


class ProductCopilotControlToolResponse(BaseModel):
    """A copilot tool that steers the turn instead of reading the corpus."""

    name: str
    role: str
    label: str
    description: str


class ProductCapabilityContractResponse(BaseModel):
    version: str
    scope: str
    cqlf_capability_contract: ProductCqlfCapabilityContractResponse
    capabilities: List[ProductCapabilityResponse]
    copilot_control_tools: List[ProductCopilotControlToolResponse] = []
    fingerprint_sha256: str


class QueryAnalyseRequest(BaseModel):
    query: str = Field(
        ...,
        description="Query for analysis and autocomplete. Prefix query language expressions with cql:.",
        examples=["cql:[lemma=\"freedom\"]", "freedom AND peace"],
    )
    corpus: Optional[str] = Field(
        default=None,
        description="Corpus identifier for lexicon and index based analysis. Without a value, the active default corpus is used.",
        examples=["default", "demo_corpus"],
    )


class LexiconSuggestRequest(BaseModel):
    attr: str = Field(
        ...,
        description="Token attribute (word, lemma, pos, ent/ner, morph, rel).",
        examples=["pos", "word", "lemma", "morph", "rel"],
    )
    prefix: str = Field(
        default="",
        description="Prefix for suggestions (for example 'AD').",
        examples=["AD", "free"],
    )
    limit: int = Field(
        default=20,
        description="Maximum number of suggestions.",
        ge=1,
        le=200,
    )
    corpus: Optional[str] = Field(
        default=None,
        description="Corpus identifier for suggestion values. Without a value, the active default corpus is used.",
        examples=["default", "demo_corpus"],
    )


# ---------------------------------------------------------------------------
# Dokumentierte Request-Bodies (OpenAPI) für Routen mit handgeschriebener
# Validierung. Beide Modelle sind ABSICHTLICH permissiv (alle Felder optional,
# Werte untypisiert, extra erlaubt): die handgeschriebenen 422-Prüfungen der
# Routen bleiben die einzige Validierungswahrheit, byte-gleich zu vorher. Die
# OpenAPI-Typen kommen über json_schema_extra und sind reine Dokumentation.
# ---------------------------------------------------------------------------
class AnalysisTrendRequest(BaseModel):
    """Body of POST /analysis/trend (frequency over a date field)."""

    query: Optional[Any] = Field(
        default=None,
        description="Search term. Required if cql is missing.",
        json_schema_extra={"type": "string"},
        examples=["freedom"],
    )
    cql: Optional[Any] = Field(
        default=None,
        description="Query language expression (the prefix cql: is added automatically). Alternative to query.",
        json_schema_extra={"type": "string"},
        examples=['[pos="NOUN"]'],
    )
    date_field: Optional[Any] = Field(
        default=None,
        description="Metadata field with date values. Required.",
        json_schema_extra={"type": "string"},
        examples=["date"],
    )
    granularity: Optional[Any] = Field(
        default=None,
        description="Period granularity: year or month. Default year.",
        json_schema_extra={"type": "string", "enum": ["year", "month"]},
    )
    docset_id: Optional[Any] = Field(
        default=None,
        description="Optional restriction to a document set.",
        json_schema_extra={"type": "string"},
    )
    corpus: Optional[Any] = Field(
        default=None,
        description="Corpus identifier. Without a value, the active default corpus is used.",
        json_schema_extra={"type": "string"},
    )
    period_values: Optional[Any] = Field(
        default=None,
        description=(
            "When true, every dated period lists in values the metadata values of "
            "date_field that form it. A metadata filter on these values selects the "
            "documents of the period."
        ),
        json_schema_extra={"type": "boolean"},
    )

    model_config = {"extra": "allow"}


class ConcordanceExportRequest(BaseModel):
    """Body of POST /export/concordance (full concordance export)."""

    query: Optional[Any] = Field(
        default=None,
        description="Search term or cql: expression. Required.",
        json_schema_extra={"type": "string"},
        examples=["freedom"],
    )
    corpus: Optional[Any] = Field(
        default=None,
        description="Corpus identifier. Without a value, the active default corpus is used.",
        json_schema_extra={"type": "string"},
    )
    docset_id: Optional[Any] = Field(
        default=None,
        description="Optional restriction to a document set.",
        json_schema_extra={"type": "string"},
    )
    sort: Optional[Any] = Field(
        default=None,
        description="Sort key of the concordance lines (sorted on the server).",
        json_schema_extra={"type": "string"},
    )
    sort_dir: Optional[Any] = Field(
        default=None,
        description="Sort direction asc or desc (alias: sortDir). Default asc.",
        json_schema_extra={"type": "string", "enum": ["asc", "desc"]},
    )
    case_insensitive: Optional[Any] = Field(
        default=None,
        description="Ignore case (alias: caseInsensitive). Default true.",
        json_schema_extra={"type": "boolean"},
    )
    ctx: Optional[Any] = Field(
        default=None,
        description="Context width in tokens. Default 5.",
        json_schema_extra={"type": "integer"},
    )
    format: Optional[Any] = Field(
        default=None,
        description="Export format: csv, tsv, json, jsonl or xlsx. Default csv.",
        json_schema_extra={"type": "string", "enum": ["csv", "tsv", "json", "jsonl", "xlsx"]},
    )
    excel_de: Optional[Any] = Field(
        default=None,
        description="Excel-friendly CSV dialect (alias: excelDe). Only with format=csv.",
        json_schema_extra={"type": "boolean"},
    )
    dialect: Optional[Any] = Field(
        default=None,
        description="CSV dialect: excel-de or default.",
        json_schema_extra={"type": "string", "enum": ["excel-de", "default"]},
    )

    model_config = {"extra": "allow"}


def request_body_as_dict(payload: Any) -> Dict[str, Any]:
    """Permissiven Request-Body in das dict-Format der Handprüfungen bringen.

    FastAPI liefert das Pydantic-Modell, direkte Aufrufer (Tests) übergeben
    weiterhin ein dict. ``exclude_unset`` reproduziert exakt die gesendeten
    Schlüssel (inklusive extra-Feldern wie camelCase-Aliassen), sodass die
    handgeschriebene Validierung byte-gleich arbeitet.
    """

    if isinstance(payload, BaseModel):
        return payload.model_dump(exclude_unset=True)
    return dict(payload or {})


class KWICRow(BaseModel):
    """One KWIC hit."""

    left: str = Field(..., description="Left context.")
    kw: str = Field(..., description="Hit word.")
    right: str = Field(..., description="Right context.")
    pos: Optional[int] = Field(default=None, description="Token position.")
    doc_id: Optional[int] = Field(default=None, description="Document ID.")
    doc: Optional[str] = Field(default=None, description="Document path or label.")
    meta: Optional[Dict[str, Any]] = Field(default=None, description="Metadata.")
    token_starts: Optional[Dict[str, List[int]]] = Field(
        default=None,
        description=(
            "Only when the corpus index stores the original spacing (whitespace_after.bin): "
            "for left, kw and right, the offset of every token in the field, in Unicode "
            "code points. left, kw and right then show the text as written."
        ),
    )
    ws_before_kw: Optional[bool] = Field(
        default=None, description="With token_starts: a space separates left and kw."
    )
    ws_after_kw: Optional[bool] = Field(
        default=None, description="With token_starts: a space separates kw and right."
    )

    model_config = {"extra": "allow"}


class FrequencyRow(BaseModel):
    word: str = Field(..., description="Token.")
    f: int = Field(..., description="Frequency.")

    model_config = {"extra": "allow"}


class CollocateRow(BaseModel):
    word: str = Field(..., description="Collocate.")
    # Expose the engine association measures to typed clients. This path
    # uses pair marginals R1+C1 with C1=m*f, so describe that denominator.
    # delta_p_nc/delta_p_cn are the directional measures from Gries (2013).
    logdice: Optional[float] = Field(
        default=None,
        description=(
            "logDice = 14 + log2(2*O11 / (R1+C1)) in the pair event space "
            "(C1 = m*f). Default ranking measure WITHIN one collocate list. "
            "Not comparable across nodes or corpora."
        ),
    )
    dice: Optional[float] = Field(
        default=None,
        description="Dice coefficient 2*O11 / (R1+C1) in the pair event space.",
    )
    delta_p_nc: Optional[float] = Field(
        default=None,
        description="Delta P node->collocate (directional association, Gries 2013), [-1,1].",
    )
    delta_p_cn: Optional[float] = Field(
        default=None,
        description="Delta P collocate->node (directional association, Gries 2013), [-1,1].",
    )
    mi: Optional[float] = Field(default=None, description="Mutual Information (log2 O/E).")
    lmi: Optional[float] = Field(default=None, description="LMI (O * MI).")
    npmi: Optional[float] = Field(default=None, description="Normalized PMI.")
    z: Optional[float] = Field(default=None, description="Z-Score.")
    chi2_cell: Optional[float] = Field(
        default=None,
        description="Chi-square cell contribution ((O - E)^2 / E).",
    )
    observed: Optional[int] = Field(default=None, description="Observed co-occurrences O11.")
    expected: Optional[float] = Field(default=None, description="Expected co-occurrences E11.")
    t: Optional[float] = Field(default=None, description="t Score.")
    ll: Optional[float] = Field(
        default=None,
        description=(
            "Full 2x2 log-likelihood ratio G² over the contingency table. "
            "Do not confuse it with the single chi2_cell contribution."
        ),
    )
    rank: Optional[int] = Field(default=None, description="Rank.")
    f: Optional[int] = Field(default=None, description="Frequency.")
    one_sided: Optional[bool] = Field(
        default=None,
        description="True if the collocation test is evaluated one-sided (attraction only).",
    )

    model_config = {"extra": "allow"}


class NgramRow(BaseModel):
    ngram: str = Field(..., description="N-gram text.")
    freq: int = Field(..., description="Frequency.")
    n: int = Field(..., description="N-gram length.")

    model_config = {"extra": "allow"}


class AnalysisLimitation(BaseModel):
    code: Optional[str] = Field(default=None, description="Stable code of the limitation.")
    message: Optional[str] = Field(default=None, description="User-visible limitation.")
    detail: Optional[str] = Field(default=None, description="Technical detail for diagnostics.")

    model_config = {"extra": "allow"}


class DispersionAnalysisResponse(BaseModel):
    term: str = Field(..., description="Analyzed search term or query language expression.")
    partitions: List[int] = Field(
        ...,
        description="Hit count per document (same order as doc_sizes).",
    )
    doc_sizes: Optional[List[int]] = Field(
        default=None,
        description="Token count per document. Basis of the expected proportions.",
    )
    unit: Optional[str] = Field(
        default=None,
        description="Partition unit of the dispersion (default: 'documents').",
    )
    dp: float = Field(
        ...,
        description=(
            "Raw Gries DP over document boundaries. Range ~[0,1]: "
            "0 = evenly distributed, 1 = strongly clustered. "
            "Expected proportion per document = doc_size_i / N."
        ),
    )
    dpnorm: Optional[float] = Field(
        default=None,
        description="Normalized Gries DP = dp / (1 - min_i(expected_i)).",
    )
    dp_min: Optional[float] = Field(
        default=None,
        description=(
            "Smallest DP that these document sizes allow for this hit count "
            "(largest remainder method). This value is not necessarily 0."
        ),
    )
    dp_erwartet: Optional[float] = Field(
        default=None,
        description=(
            "DP under purely random scattering proportional to document length. "
            "The reference against which dp is read. It can exceed the "
            "threshold 0.8 above which the profile strongly_clustered is "
            "assigned. The label then no longer discriminates. "
            "Computed analytically, not simulated."
        ),
    )
    dp_max: Optional[float] = Field(
        default=None,
        description="Largest attainable DP = 1 - min_i(expected_i).",
    )
    juilland_d: Optional[float] = Field(
        default=None,
        description=(
            "Juilland's D = 1 - VC/sqrt(n-1) over the document partition "
            "(1 = even, 0 = strongly clustered)."
        ),
    )
    carroll_d2: Optional[float] = Field(
        default=None,
        description=(
            "Carroll's D2 = normalized entropy H/ln(n) (1 = even, "
            "0 = all occurrences in one part)."
        ),
    )
    range: Optional[int] = Field(
        default=None,
        description="Range: number of documents with at least one occurrence.",
    )
    range_prop: Optional[float] = Field(
        default=None,
        description="Range normalized by the number of documents (share of parts reached).",
    )
    vc: Optional[float] = Field(
        default=None,
        description="Coefficient of variation of the normalized part frequencies v_i = o_i/s_i.",
    )
    classification: Optional[str] = Field(
        default=None,
        description="Qualitative label: even, fairly_even, fairly_clustered, clustered.",
    )
    method: Optional[MethodBlock] = Field(
        default=None,
        description="Statistical provenance (Track F1) including the dispersion family.",
    )
    positional_dp_windowed: Optional[float] = Field(
        default=None,
        description=(
            "Optional legacy DP over equally wide position-based windows "
            "(set only when partitions>0 is requested)."
        ),
    )
    positional_window_count: Optional[int] = Field(
        default=None,
        description="Number of position-based windows for positional_dp_windowed.",
    )
    basis: Optional[str] = Field(default=None, description="Basis of the computation: global, docset_local or a fallback basis.")
    token_count: Optional[int] = Field(default=None, description="Token basis, if it can be determined reliably.")
    fallback: Optional[bool] = Field(default=None, description="True if a fallback was used.")
    partial: Optional[bool] = Field(default=None, description="True if the result is restricted.")
    limitations: List[AnalysisLimitation] = Field(default_factory=list, description="Visible methodological limitations.")

    model_config = {"extra": "allow"}


class JobLaunchResponse(BaseModel):
    """Response of every async analysis job-launch route.

    DT-VERTRAEGE: the job-launch contract is pinned as snake_case
    (``job_id``/``status_url``/``rows_url``/``ws_url``) across ALL analysis job
    endpoints, so a typed client never has to guess between snake_case and
    camelCase variants. ``extra='allow'`` keeps any per-job additive field
    contract-safe.
    """

    job_id: str = Field(..., description="ID of the created job.")
    status_url: str = Field(..., description="REST URL for the job status.")
    rows_url: Optional[str] = Field(
        default=None, description="REST URL for paginated result rows."
    )
    ws_url: Optional[str] = Field(
        default=None, description="WebSocket URL for the live job stream."
    )

    model_config = {"extra": "allow"}


class DocsetFromSearchResponse(BaseModel):
    docset_id: str = Field(..., description="Document set ID.")
    doc_count: int = Field(..., description="Number of documents in the document set.")
    hit_doc_count: Optional[int] = Field(
        default=None, description="Documents of the document set with a hit of their own."
    )
    ref_doc_count: Optional[int] = Field(
        default=None,
        description="Reference documents whose families were added (0 without families).",
    )
    token_count: Optional[int] = Field(
        default=None,
        description="Number of tokens in the document set (if available).",
    )
    # Ohne dieses Feld im Modell striche pydantic es still, wie zuvor die
    # Kappungsfelder unten.
    familien: Optional[bool] = Field(
        default=None,
        description=(
            "True if the document set contains, besides the documents with "
            "hits, their variant families (reference document and AI variants, "
            "also without a hit of their own). doc_count minus hit_doc_count is "
            "the number of documents added this way."
        ),
    )
    # Ein gesetztes limit kappt den TREFFERSCAN, und dieses Modell kannte
    # die drei Felder nicht: pydantic hat sie stillschweigend gestrichen.
    # Die Antwort auf limit=100 war damit byte-gleich zu der ohne jede
    # Kappungsmeldung, {'doc_count': 24, 'hit_doc_count': 24,
    # 'ref_doc_count': 24, 'token_count': 632}, obwohl dieselbe Abfrage
    # ungedeckelt 1995 Dokumente und 56.080 Tokens ergibt. Ein Feld, das
    # im Response-Modell verloren geht, zaehlt nicht.
    truncated: Optional[bool] = Field(
        default=None,
        description=(
            "True if the hit scan reached the limit. The document set "
            "is then a prefix of the query hits, not a slice of the corpus."
        ),
    )
    scan_limit: Optional[int] = Field(
        default=None, description="The limit at which the scan stopped."
    )
    truncation_note: Optional[str] = Field(
        default=None, description="Plain-text note about the truncation."
    )


class QueryAnalyseResponse(BaseModel):
    errors: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    hints: List[str] = Field(default_factory=list)
    kinds: List[str] = Field(default_factory=list)
    spans: List[List[int]] = Field(default_factory=list)
    builder: Optional[Dict[str, Any]] = Field(default=None)
    warnings: List[str] = Field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = Field(default_factory=list)


class LexiconSuggestResponse(BaseModel):
    values: List[str] = Field(default_factory=list)


class KeynessRow(BaseModel):
    word: str = Field(..., description="Token.")
    target_freq: Optional[int] = Field(default=None, description="Frequency in the target.")
    reference_freq: Optional[int] = Field(default=None, description="Frequency in the reference.")
    target_per_million: Optional[float] = Field(default=None, description="Target frequency per million tokens.")
    reference_per_million: Optional[float] = Field(default=None, description="Reference frequency per million tokens.")
    diff_per_million: Optional[float] = Field(default=None, description="Target minus reference per million tokens.")
    direction: Optional[str] = Field(default=None, description="Dominant side: target or reference.")
    chi2_cell: Optional[float] = Field(
        default=None,
        description="Chi-square cell contribution ((O - E)^2 / E).",
    )
    ll: Optional[float] = Field(default=None, description="Log-likelihood/G² score.")
    chi2_cell_signed: Optional[float] = Field(
        default=None,
        description="Directional chi-square cell contribution; sign follows diff_per_million.",
    )
    chi2: Optional[float] = Field(
        default=None,
        description="Full 2x2 Pearson chi-square (df=1), all four cells; not the single-cell chi2_cell.",
    )
    chi2_signed: Optional[float] = Field(
        default=None,
        description="Directional full 2x2 Pearson chi-square; sign follows diff_per_million.",
    )
    ll_signed: Optional[float] = Field(default=None, description="Directional Log-likelihood/G² score.")
    log_ratio: Optional[float] = Field(
        default=None,
        description="Hardie Log Ratio (log2 relative-risk effect size).",
    )
    log_ratio_ci_low: Optional[float] = Field(
        default=None,
        description="Lower bound of the log ratio confidence interval.",
    )
    log_ratio_ci_high: Optional[float] = Field(
        default=None,
        description="Upper bound of the log ratio confidence interval.",
    )
    lrc: Optional[float] = Field(
        default=None,
        description=(
            "Conservative Log Ratio (Evert 2022): the bound of the log ratio "
            "confidence interval closer to zero, with the sign of the log ratio, "
            "0 when the interval contains zero."
        ),
    )
    bic: Optional[float] = Field(
        default=None,
        description="Bayesian information criterion approximation for keyness.",
    )
    p_value: Optional[float] = Field(default=None, description="p-value of the keyness test.")
    q_value: Optional[float] = Field(
        default=None,
        description="q-value corrected for multiple comparisons (FDR).",
    )
    expected_min: Optional[float] = Field(
        default=None,
        description="Smallest expected 2x2 cell count E_min (basis for reliability).",
    )
    low_reliability: Optional[bool] = Field(
        default=None,
        description=(
            "True if the smallest expected 2x2 cell is < 5 (E>=5 rule). "
            "The chi-square and G² tests are then unreliable (FT-KEYNESS-RESEARCH)."
        ),
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Statistical provenance method block (Track F1)
# ---------------------------------------------------------------------------
class MethodStatistic(BaseModel):
    """One statistic's provenance descriptor (mirrors analysis_defaults.METHOD_META)."""

    key: str = Field(..., description="Response field name the formula refers to.")
    name: str = Field(..., description="Human-readable name of the statistic.")
    latex_formula: str = Field(..., description="LaTeX formula of the implemented computation.")
    smoothing: str = Field(..., description="Smoothing or correction note ('none' if exact).")
    sort_key: str = Field(..., description="Field by which the default sort orders rows in descending order.")

    model_config = {"extra": "allow"}


class MethodBlock(BaseModel):
    """Top-level statistical provenance that accompanies every analysis response."""

    family: str = Field(..., description="Analysis family (keyness, collocates, ngrams, ...).")
    statistics: List[MethodStatistic] = Field(
        default_factory=list, description="Ordered descriptions of the statistics."
    )
    default_sort: Optional[str] = Field(
        default=None, description="Field of the default sort of the rows."
    )
    indexFingerprint: Optional[str] = Field(
        default=None,
        description="Corpus cache signature of the index state (changes on rebuild).",
    )
    target_total: Optional[int] = Field(
        default=None, description="Token basis of the target (if known)."
    )
    reference_total: Optional[int] = Field(
        default=None, description="Token basis of the reference (if known)."
    )
    window: Optional[int] = Field(default=None, description="Collocation window (tokens).")
    within_sentence: Optional[bool] = Field(
        default=None, description="True if the window is clipped at sentence boundaries."
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Paged response envelopes (Track D12 / DT-VERTRAEGE): rows + bounded-result
# meta. The bounded-result meta keys (row_limit/total_candidates/truncated)
# are computed by ``server._bounded_result_meta`` and were previously only
# carried through ``extra='allow'`` (undocumented). They are now TYPED on the
# envelope so a client can rely on them; extra='allow' still keeps further
# additive fields (method/limitations/group_by/basis/...) contract-safe.
# ---------------------------------------------------------------------------
class BoundedMeta(BaseModel):
    """Bounded-result pagination meta surfaced by every paged analysis route."""

    row_limit: Optional[int] = Field(
        default=None,
        description="Maximum number of rows on this page (server-side limit).",
    )
    total_candidates: Optional[int] = Field(
        default=None,
        description="Total number of candidate rows before pagination.",
    )
    truncated: Optional[bool] = Field(
        default=None,
        description="True if further rows exist beyond this page.",
    )


class PagedResponse(BoundedMeta):
    """Common rows+meta envelope for paged analysis endpoints."""

    rows: List[Dict[str, Any]] = Field(default_factory=list, description="Result rows.")
    method: Optional[MethodBlock] = Field(
        default=None, description="Statistical provenance (Track F1)."
    )

    model_config = {"extra": "allow"}


class PagedFrequencyResponse(PagedResponse):
    rows: List[FrequencyRow] = Field(default_factory=list)


class PagedCollocatesResponse(PagedResponse):
    rows: List[CollocateRow] = Field(default_factory=list)


class PagedKeynessResponse(PagedResponse):
    rows: List[KeynessRow] = Field(default_factory=list)


class PagedNgramsResponse(PagedResponse):
    rows: List[NgramRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Lexical diversity (Track F4)
# ---------------------------------------------------------------------------
class LexicalDiversityMetrics(BaseModel):
    """TTR/STTR/Guiraud/MATTR over a set of tokens."""

    ttr: float = Field(..., description="Type-token ratio V/N (confounded with text length).")
    sttr: Optional[float] = Field(
        default=None,
        description="Standardized TTR: mean TTR over windows (None if the stream is shorter than one window).",
    )
    sttr_window: int = Field(..., description="STTR window size in tokens.")
    sttr_n_windows: Optional[int] = Field(
        default=None, description="Number of averaged STTR windows."
    )
    guiraud: float = Field(..., description="Guiraud's R = V/sqrt(N).")
    mattr: Optional[float] = Field(
        default=None, description="Moving-average TTR (only when requested)."
    )
    mattr_window: Optional[int] = Field(
        default=None, description="MATTR window size in tokens."
    )
    n_tokens: int = Field(..., description="Number of counted tokens (N).")
    n_types: int = Field(..., description="Number of distinct types (V).")
    analyst_tokens_only: Optional[bool] = Field(
        default=None,
        description="True if empty, punctuation and marker tokens are excluded.",
    )
    analyst_token_policy: Optional[str] = Field(
        default=None,
        description="Explicit filter rule of the token basis used for the statistics.",
    )

    model_config = {"extra": "allow"}


class LexicalDiversityResponse(LexicalDiversityMetrics):
    """Response of the /analysis/lexical-diversity endpoint.

    One-sided: metrics directly at the top level. Two-sided (target and reference
    document set): additionally ``per_side`` with both sides and an optional
    ``size_warning``.
    """

    basis: Optional[str] = Field(
        default=None, description="Basis of the computation: corpus or docset."
    )
    indexFingerprint: Optional[str] = Field(
        default=None, description="Corpus cache signature of the index state."
    )
    method: Optional[MethodBlock] = Field(
        default=None, description="Statistical provenance (Track F1)."
    )
    per_side: Optional[Dict[str, LexicalDiversityMetrics]] = Field(
        default=None, description="Two-sided comparison (target/reference)."
    )
    size_warning: Optional[str] = Field(
        default=None,
        description="Warning when the sides differ in token count (raw TTR not comparable).",
    )

    model_config = {"extra": "allow"}


class CollocationNetworkNode(BaseModel):
    """A node in the collocation network."""

    id: str = Field(..., description="Word form or lemma of the node (the seed has depth=0).")
    freq: Optional[int] = Field(
        default=None,
        description="Co-occurrence frequency of the collocate (None for the seed node).",
    )
    depth: Optional[int] = Field(
        default=None,
        description="Distance from the seed: 0=seed, 1=first order, 2=second order (ego network).",
    )

    model_config = {"extra": "allow"}


class CollocationNetworkEdge(BaseModel):
    """An edge in the collocation network."""

    source: str = Field(..., description="Source node ID.")
    target: str = Field(..., description="Target node ID.")
    weight: float = Field(..., description="Edge weight = association measure (see measure).")
    measure: str = Field(..., description="Association measure of the weight (for example logdice).")

    model_config = {"extra": "allow"}


class CollocationNetworkResponse(BaseModel):
    """Serializable collocation network (nodes and edges)."""

    term: str = Field(..., description="Seed term of the network (cql: prefix removed).")
    measure: str = Field(
        ...,
        description="Chosen association measure for the edge weights. Default logdice.",
    )
    nodes: List[CollocationNetworkNode] = Field(
        default_factory=list, description="Nodes of the network."
    )
    edges: List[CollocationNetworkEdge] = Field(
        default_factory=list, description="Edges of the network."
    )
    diagnostics: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Diagnostics: node_count, edge_count, first_order_count, "
            "second_order_count, expand_depth, max_nodes, window, min_count, truncated."
        ),
    )

    model_config = {"extra": "allow"}


class WordSketchRow(BaseModel):
    word: str = Field(..., description="Collocate.")
    f: Optional[int] = Field(default=None, description="Frequency.")
    frequency: Optional[int] = Field(default=None, description="Frequency.")
    score: Optional[float] = Field(default=None, description="Score.")
    score_key: Optional[str] = Field(default=None, description="Score metric.")
    rank: Optional[int] = Field(default=None, description="Rank within the relation.")
    chi2_cell: Optional[float] = Field(
        default=None,
        description="Chi-square cell contribution ((O - E)^2 / E).",
    )
    t: Optional[float] = Field(default=None, description="T-Score.")
    ll: Optional[float] = Field(default=None, description="Log-likelihood-like statistic.")

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Sketch difference (Track FT-SKETCH-DIFF-DISTRIBUTION)
# ---------------------------------------------------------------------------
class SketchDiffSharedRow(BaseModel):
    """A collocate present in BOTH sketches of one grammatical relation."""

    word: str = Field(..., description="Collocate shared by both sides in this relation.")
    score_a: Optional[float] = Field(default=None, description="Score on side A.")
    score_b: Optional[float] = Field(default=None, description="Score on side B.")
    delta: Optional[float] = Field(
        default=None,
        description="score_a - score_b (positive = stronger on side A).",
    )
    f_a: Optional[int] = Field(default=None, description="Frequency on side A.")
    f_b: Optional[int] = Field(default=None, description="Frequency on side B.")
    score_key: Optional[str] = Field(
        default=None, description="Score metric of the compared values (for example score)."
    )

    model_config = {"extra": "allow"}


class SketchDiffRelation(BaseModel):
    """One grammatical relation diffed across two word sketches."""

    only_a: List[WordSketchRow] = Field(
        default_factory=list,
        description="Collocates that occur in this relation only on side A.",
    )
    only_b: List[WordSketchRow] = Field(
        default_factory=list,
        description="Collocates that occur in this relation only on side B.",
    )
    common: List[SketchDiffSharedRow] = Field(
        default_factory=list,
        description="Collocates of both sides with score delta (sorted by |delta|).",
    )

    model_config = {"extra": "allow"}


class SketchDiffResponse(BaseModel):
    """Difference between two word sketches.

    Two modes share this shape:
      - two terms in one (sub)corpus: ``term_a`` vs ``term_b``;
      - one term across two docsets: ``term`` with ``docset_a``/``docset_b``.

    ``relations`` maps each grammatical relation to its ``only_a``/``only_b``/
    ``common`` partition. The label of each side is carried in ``label_a`` /
    ``label_b`` so the frontend can title the two columns.
    """

    label_a: str = Field(..., description="Label of side A (term or document set).")
    label_b: str = Field(..., description="Label of side B (term or document set).")
    relations: Dict[str, SketchDiffRelation] = Field(
        default_factory=dict,
        description="Relation -> difference partition (only_a/only_b/common).",
    )
    relation_labels: Dict[str, str] = Field(
        default_factory=dict,
        description="Relation -> human-readable label of the same relation codes.",
    )
    score_key: str = Field(
        default="score",
        description="Score metric on which the delta is based.",
    )
    method: Optional[MethodBlock] = Field(
        default=None, description="Statistical provenance (Track F1)."
    )
    limitations: List[AnalysisLimitation] = Field(
        default_factory=list, description="Visible methodological limitations."
    )

    model_config = {"extra": "allow"}
