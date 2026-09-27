from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from typing import Literal

from cqlhpc.capabilities import build_cqlf_capability_contract
from candyconc.i18n import bilingual_form, lt
from candyconc.services.backend.route_matrix import (
    policy_for_path,
    required_role_for_access,
)


ProductCapabilityMaturity = Literal["stable", "guarded", "experimental", "planned", "unsupported"]
ProductCapabilityVisibility = Literal["first_class_ui", "expert_api", "hidden_experimental"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "WS"]
ProductRouteAccess = Literal["public", "user", "manager", "admin", "owner_or_admin"]
ProductRouteTransport = Literal["http", "websocket"]
ProductRouteClass = Literal["product_surface", "admin_surface", "infrastructure", "deprecated", "unclassified"]
ProductOperationEffect = Literal["read", "write", "destructive", "long_running"]
ProductOperationUiExecutionPolicy = Literal["contextual_ui", "confirmed_contextual_ui", "none"]
ProductOperationResponseShape = Literal["data", "job", "stream", "file", "image", "void", "mixed", "unknown"]
ProductOperationRunSemantics = Literal["instant", "bounded_sync", "job_lifecycle", "stream", "file_export", "fire_and_forget"]
ProductOperationLifecycleKind = Literal["analysis_job", "corpus_import_job", "system_status_job", "websocket_job", "operation_run"]
ProductOperationLifecyclePolling = Literal["http_poll", "websocket", "none"]

PRODUCT_CAPABILITY_CONTRACT_VERSION = "product-capabilities-v1"

# Tools that steer the copilot's turn instead of reading the corpus. They have
# no ProductOperation and yield no corpus evidence, a call ends the tool phase.
# This is the one list: tooling.tool_selection and the MCP tool status read it,
# the contract hands it to the UI (``copilot_control_tools``).
COPILOT_CONTROL_TOOLS: tuple[dict[str, str], ...] = (
    {
        "name": "deutung_abgeben",
        "role": "turn_control",
        "label": lt("Untersuchung abgeschlossen", "Investigation complete"),
        "description": lt(
            "Der Copilot beendet die Werkzeugphase und übergibt seine Deutung "
            "an die Antwort. Der Aufruf liefert keine Korpus-Evidenz.",
            "The copilot ends the tool phase and passes its interpretation "
            "on to the answer. The call returns no corpus evidence.",
        ),
    },
)
COPILOT_TURN_CONTROL_TOOLS: frozenset[str] = frozenset(
    tool["name"] for tool in COPILOT_CONTROL_TOOLS if tool["role"] == "turn_control"
)


def _analysis_job_lifecycle() -> ProductOperationLifecycle:
    return ProductOperationLifecycle(
        kind="analysis_job",
        job_id_field="job_id",
        status_operation_id="analysis.async_jobs.status",
        cancel_operation_id="analysis.async_jobs.cancel",
        rows_operation_id="analysis.async_jobs.rows",
        status_url_field="status_url",
        rows_url_field="rows_url",
        rows_state_field="rows_state",
        readiness_field="result_readiness",
        warnings_field="result_warnings",
        result_available_field="result_available",
        result_discarded_field="result_discarded",
        result_discard_reason_field="result_discard_reason",
    )


def _corpus_import_job_lifecycle() -> ProductOperationLifecycle:
    return ProductOperationLifecycle(
        kind="corpus_import_job",
        job_id_field="job_id",
        status_operation_id="corpus.import.job_status",
        cancel_operation_id="corpus.import.job_cancel",
        reports_operation_id="corpus.import.job_reports",
        readiness_field="readiness",
        warnings_field="import_warnings",
    )


def _embedding_download_lifecycle() -> ProductOperationLifecycle:
    return ProductOperationLifecycle(
        kind="operation_run",
        job_id_field="run_id",
        status_operation_id="settings.embedding_management.download_status",
        status_url_field="status_url",
        readiness_field="readiness",
        warnings_field="warnings",
        terminal_statuses=("succeeded", "failed", "cancelled", "stale"),
    )


def _local_semantic_index_lifecycle() -> ProductOperationLifecycle:
    return ProductOperationLifecycle(
        kind="operation_run",
        job_id_field="run_id",
        status_operation_id="settings.embedding_management.local_index_status",
        cancel_operation_id="settings.embedding_management.local_index_cancel",
        status_url_field="status_url",
        readiness_field="readiness",
        warnings_field="warnings",
        terminal_statuses=("succeeded", "failed", "cancelled", "stale"),
    )


@dataclass(frozen=True, slots=True)
class ProductBackendRoute:
    path: str
    methods: tuple[HttpMethod, ...]
    mutates: bool = False
    requires_corpus_features: tuple[str, ...] = ()
    access: ProductRouteAccess | None = None
    required_role: str | None = None
    transport: ProductRouteTransport = "http"
    route_class: ProductRouteClass | None = None


BackendRouteClaim = str | ProductBackendRoute


@dataclass(frozen=True, slots=True)
class ProductOperationLifecycle:
    kind: ProductOperationLifecycleKind
    job_id_field: str
    status_operation_id: str = ""
    cancel_operation_id: str = ""
    rows_operation_id: str = ""
    reports_operation_id: str = ""
    status_url_field: str = ""
    rows_url_field: str = ""
    websocket_url_field: str = ""
    polling: ProductOperationLifecyclePolling = "http_poll"
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
    terminal_statuses: tuple[str, ...] = ("done", "error", "cancelled")


@dataclass(frozen=True, slots=True)
class ProductOperation:
    id: str
    label: str
    route: BackendRouteClaim
    description: str = ""
    effects: tuple[ProductOperationEffect, ...] | None = None
    copilot_tools: tuple[str, ...] = ()
    surface_slot: str | None = None
    priority: int | None = None
    input_schema_ref: str | None = None
    response_shape: ProductOperationResponseShape | None = None
    requires_parameters: bool = True
    lifecycle: ProductOperationLifecycle | None = None


def operation(
    id: str,
    label: str,
    route: BackendRouteClaim,
    description: str = "",
    **kwargs: object,
) -> ProductOperation:
    return ProductOperation(id=id, label=label, route=route, description=description, **kwargs)


@dataclass(frozen=True, slots=True)
class ProductCopilotToolOperationBinding:
    tool_name: str
    capability_id: str
    operation_id: str
    route: ProductBackendRoute
    effects: tuple[ProductOperationEffect, ...]


@dataclass(frozen=True, slots=True)
class ProductCapability:
    id: str
    title: str
    area: str
    maturity: ProductCapabilityMaturity = "guarded"
    visibility: ProductCapabilityVisibility = "expert_api"
    backend_routes: tuple[BackendRouteClaim, ...] = ()
    operations: tuple[ProductOperation, ...] = ()
    action_types: tuple[str, ...] = ()
    copilot_tools: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    limits: tuple[str, ...] = ()


def ui_capability(id: str, title: str, area: str, **kwargs: object) -> ProductCapability:
    return ProductCapability(id=id, title=title, area=area, visibility="first_class_ui", **kwargs)


def route_capability(
    id: str,
    title: str,
    area: str,
    *backend_routes: BackendRouteClaim,
    maturity: ProductCapabilityMaturity = "guarded",
    visibility: ProductCapabilityVisibility = "expert_api",
    copilot_tools: tuple[str, ...] = (),
    limits: tuple[str, ...] = (),
) -> ProductCapability:
    return ProductCapability(
        id=id,
        title=title,
        area=area,
        maturity=maturity,
        visibility=visibility,
        backend_routes=backend_routes,
        copilot_tools=copilot_tools,
        limits=limits,
    )


def operation_capability(
    id: str,
    title: str,
    area: str,
    operation: ProductOperation,
    **kwargs: object,
) -> ProductCapability:
    return ProductCapability(id=id, title=title, area=area, operations=(operation,), **kwargs)


PRODUCT_OPERATION_REQUIRED_CONTEXT_BY_SCHEMA_ID: dict[str, tuple[str, ...]] = {
    "query.kwic.request": ("active_query",),
    "query.cqlf.analyse.request": ("active_query",),
    "analysis.term_job_request": ("active_query",),
    "analysis.term_docset_pair_request": ("active_query",),
    "analysis.collocates_diff_job_request": ("active_query",),
    "analysis.wordsketch_request": ("active_query",),
    "analysis.wordsketch_diff_request": ("active_query",),
    "analysis.semantic_search_request": ("active_query",),
    "research.annotations.row_mutation": ("selected_rows",),
    "research.replay_export.request": ("active_query",),
    "research.replay_export.concordance_request": ("active_query",),
    "research.replay_export.evidence_package_request": ("active_query",),
}



def _route_group(
    methods: tuple[HttpMethod, ...],
    paths: str,
    **route_kwargs: object,
) -> dict[str, ProductBackendRoute]:
    return {path: ProductBackendRoute(path, methods, **route_kwargs) for path in paths.split()}


PRODUCT_BACKEND_ROUTE_METADATA: dict[str, ProductBackendRoute] = {
    **_route_group(('GET',), """
        /api/v1/analysis/collocates /api/v1/analysis/collocates/kwic /api/v1/analysis/dispersion
        /api/v1/analysis/dispersion_offsets /api/v1/analysis/frequency_list
        /api/v1/analysis/jobs/{job_id} /api/v1/analysis/jobs/{job_id}/rows
        /api/v1/analysis/lexical-diversity /api/v1/analysis/meta_schema
        /api/v1/annotations /api/v1/annotations/agreement /api/v1/annotations/multi
        /api/v1/auth/dev-token /api/v1/auth/session /api/v1/capabilities /api/v1/corpora
        /api/v1/corpora/import-methods /api/v1/corpora/imports/{job_id}
        /api/v1/corpora/imports/{job_id}/reports /api/v1/corpora/{corpus}/build-report
        /api/v1/corpora/{corpus}/capabilities /api/v1/doc/snippet /api/v1/docs/search
        /api/v1/document/{doc_id} /api/v1/download/{file_id} /api/v1/embeddings/list
        /api/v1/embeddings/local-index/preflight /api/v1/embeddings/local-index/builds/{run_id}
        /api/v1/metrics /api/v1/prefs /api/v1/query
        /api/v1/query/count /api/v1/query/stream /api/v1/system/info
        /mcp/tools
    """
    ),
    **_route_group(('POST',), """
        /api/v1/analysis/collocates/job /api/v1/analysis/collocates_diff/job
        /api/v1/analysis/docset_from_meta /api/v1/analysis/docset_from_search
        /api/v1/analysis/docset_intersection /api/v1/analysis/frequency_list/job
        /api/v1/analysis/frequency_diff/job
        /api/v1/analysis/jobs/{job_id}/cancel /api/v1/ws-ticket /api/v1/analysis/keyness/job
        /api/v1/analysis/ngrams/job /api/v1/analysis/ngrams_diff/job /api/v1/annotations/import
        /api/v1/chat /api/v1/chat/stream /api/v1/copilot/action/approve /api/v1/copilot/action/reject
        /api/v1/copilot/clarify/answer /api/v1/copilot/context /api/v1/copilot/continue
        /api/v1/corpora/imports/{job_id}/cancel /api/v1/corpora/register
        /api/v1/corpora/{corpus}/activate /api/v1/embeddings/download /api/v1/embeddings/remove
        /api/v1/embeddings/local-index/build /api/v1/embeddings/local-index/builds/{run_id}/cancel
        /api/v1/login /api/v1/logout
        /api/v1/projects/create /api/v1/projects/{proj}/analysis-presets/{preset_id}/touch
        /api/v1/prefs/update /api/v1/settings/embeddings /api/v1/system/clear-cache
        /api/v1/system/rebuild-index /api/v1/subcorpora/{name}/resolve
        /mcp/call
    """,
        mutates=True
    ),
    **_route_group(('POST',), """
        /api/v1/analysis/contrast /api/v1/analysis/keyness /api/v1/analysis/meta_counts
        /api/v1/analysis/meta_values /api/v1/analysis/ngrams /api/v1/corpora/import-preflight
        /api/v1/export/evidence-package /api/v1/export/docx /api/v1/export/pdf
        /api/v1/query/lexicon/suggest /api/v1/semantic/cluster /api/v1/semantic/cluster_words
        /api/v1/semantic/outline /api/v1/semantic/recluster
    """
    ),
    **_route_group(('WS',), """
        /api/v1/ws/analysis/{job_id} /api/v1/ws/faiss/{job_id}
    """,
        transport="websocket"
    ),
    **_route_group(('DELETE',), """
        /api/v1/corpora/{corpus}/registration
    """,
        mutates=True
    ),
    **_route_group(('POST',), """
        /api/v1/analysis/alignment/ref_doc /api/v1/analysis/parallel_groups
    """,
        requires_corpus_features=("alignment.parallel_groups", )
    ),
    **_route_group(('POST',), """
        /api/v1/analysis/wordsketch /api/v1/analysis/wordsketch_diff
    """,
        requires_corpus_features=("token_attributes.rel", )
    ),
    **_route_group(('DELETE', 'PATCH'), """
        /api/v1/projects/{proj}/analysis-presets/{preset_id}
    """,
        mutates=True
    ),
    **_route_group(('DELETE', 'PUT'), """
        /api/v1/annotations/{row_id}
    """,
        mutates=True
    ),
    **_route_group(('POST',), """
        /api/v1/annotations/scheme/preview
    """,
        access="manager",
        required_role="manager",
    ),
    **_route_group(('GET',), """
        /api/v1/operation-runs/{run_id}
    """,
        access="admin",
        route_class="admin_surface"
    ),
    # Lesen und Umstellen teilen sich einen Pfad. Das Verzeichnis ist nach Pfad
    # geschluesselt, deshalb steht hier EIN Eintrag mit beiden Methoden, so wie
    # bei /api/v1/projects/{proj}/clusters.
    **_route_group(('GET', 'POST'), """
        /api/v1/settings/model-route
    """,
        mutates=True
    ),
    **_route_group(('GET', 'POST', 'PUT'), """
        /api/v1/projects/{proj}/clusters
    """,
        mutates=True
    ),
    **_route_group(('PATCH',), """
        /api/v1/projects/{proj}/clusters/rename
    """,
        mutates=True
    ),
    **_route_group(('POST',), """
        /api/v1/analysis/kwic_parallel
    """,
        requires_corpus_features=("alignment.parallel_kwic", )
    ),
    **_route_group(('POST',), """
        /api/v1/analysis/embedding_search
    """,
        requires_corpus_features=("semantic.passage_search", )
    ),
    **_route_group(('PUT',), """
        /api/v1/semantic/clusters/apply
    """,
        mutates=True
    ),
}


ANNOTATION_SCHEME_READ = ProductBackendRoute("/api/v1/annotations/scheme", ("GET",), access="user", required_role="user")
ANNOTATION_SCHEME_WRITE = ProductBackendRoute("/api/v1/annotations/scheme", ("PUT",), mutates=True, access="manager", required_role="manager")
ANNOTATION_SCHEME_PREVIEW = ProductBackendRoute("/api/v1/annotations/scheme/preview", ("POST",), access="manager", required_role="manager")
ANNOTATION_SETTINGS_READ = ProductBackendRoute("/api/v1/annotations/settings", ("GET",), access="user", required_role="user")
ANNOTATION_SETTINGS_WRITE = ProductBackendRoute("/api/v1/annotations/settings", ("PUT",), mutates=True, access="manager", required_role="manager")


PRODUCT_CAPABILITIES: tuple[ProductCapability, ...] = (
    ui_capability("query.kwic", lt("KWIC-Suche und Seitennavigation", "KWIC search and pagination"), "search",
        maturity="stable",
        operations=(
            operation('query.kwic.page', lt("KWIC-Trefferseite", "KWIC hit page"), '/api/v1/query', input_schema_ref='query.kwic.request', copilot_tools=('run_cqlf_query',)),
            operation('query.kwic.stream', lt("KWIC-Stream", "KWIC stream"), '/api/v1/query/stream', effects=('read', 'long_running'), copilot_tools=('run_cqlf_query',), input_schema_ref='query.kwic.request', response_shape='stream'),
            operation('query.kwic.count', lt("KWIC-Zählung", "KWIC hit count"), '/api/v1/query/count', input_schema_ref='query.kwic.request', copilot_tools=('query_count',)),
        ),
        action_types=(
            "query/execute",
            "query/loadMore",
            "query/setFilters",
            "query/clear",
            "kwic/scrollToRow",
            "kwic/selectRows",
            "kwic/highlightRow",
            "kwic/expandContext",
        ),
    ),
    ui_capability("query.cqlf", lt("Abfrageerstellung, Diagnose und Ausführung", "Query authoring, diagnostics, and execution"), "search",
        operations=(
            operation('query.cqlf.analyse', lt("CQLF-Diagnostik", "Query diagnostics"), ProductBackendRoute('/api/v1/query/analyse', ('POST',)), input_schema_ref='query.cqlf.analyse.request', surface_slot='query.cqlf.diagnostics'),
            operation('query.cqlf.lexicon_suggest', lt("CQLF-Lexikonvorschläge", "Query lexicon suggestions"), '/api/v1/query/lexicon/suggest', input_schema_ref='query.cqlf.lexicon_suggest.request', surface_slot='query.cqlf.suggestions'),
        ),
        action_types=("query/execute",),
        copilot_tools=("run_cqlf_query", "query_count"),
    ),
    ui_capability("query.document_access", lt("Dokumentabruf, Textausschnitte und Volltext", "Document lookup, snippets, and full text"), "search",
        maturity="stable",
        operations=(
            operation('query.document_access.snippet', lt("Dokument-Snippet", "Document snippet"), '/api/v1/doc/snippet', copilot_tools=('document_search', 'kwic_context', 'documentation_search')),
            operation('query.document_access.full_text', lt("Dokument öffnen", "Open document"), '/api/v1/document/{doc_id}', copilot_tools=('document_text',)),
        ),
        action_types=("nav/openDocument",),
        copilot_tools=("document_text", "document_search", "kwic_context", "documentation_search"),
    ),
    # Der Korpusleser ist eine EIGENE Faehigkeit, nicht eine Umdeutung von
    # query.document_access. Diese fuehrt die Dokumentbelege UNTER der
    # KWIC-Ansicht, und ein Test haelt genau das fest ("keeps document
    # access scoped to KWIC evidence instead of advertising a standalone
    # document browser"). Der Test hat recht: eine Faehigkeit kann nicht
    # zugleich eine Belegschicht und eine eigene Ansicht sein.
    #
    # Bis heute konnte man in CandyConc jedes Wort zaehlen und keinen Text
    # lesen. Die Dokumentsuche verlangt einen Suchbegriff, der Volltext
    # verlangt eine Dokumentnummer. Wer nur wissen wollte, was im Korpus
    # steht, hatte keinen Weg.
    ui_capability("query.corpus_reader", lt("Korpusleser: Dokumente durchblättern und lesen", "Corpus reader: browse and read documents"), "search",
        maturity="stable",
        operations=(
            operation('query.corpus_reader.list', lt("Dokumente durchblättern", "Browse documents"), '/api/v1/docs/list'),
            operation('query.corpus_reader.read', lt("Dokument lesen", "Read document"), '/api/v1/document/{doc_id}', copilot_tools=('document_text',)),
        ),
        action_types=("nav/openDocument",),
        copilot_tools=("document_text",),
    ),
    route_capability("query.document_search_api", lt("API für die Dokumentsuche", "Document search API"), "search", "/api/v1/docs/search"),
    ui_capability("analysis.frequency", lt("Frequenzlisten", "Frequency lists"), "analysis",
        maturity="stable",
        operations=(
            operation('analysis.frequency.list', lt("Frequenzliste", "Frequency list"), '/api/v1/analysis/frequency_list', copilot_tools=('frequency_list',), surface_slot='analysis.frequency.sync'),
            operation('analysis.frequency.job', lt("Frequenzjob", "Frequency job"), '/api/v1/analysis/frequency_list/job', effects=('read', 'long_running'), input_schema_ref='analysis.frequency_job_request', lifecycle=_analysis_job_lifecycle()),
            operation('analysis.frequency.diff_job', lt("Frequenz-Kontrastjob", "Frequency contrast job"), '/api/v1/analysis/frequency_diff/job', effects=('read', 'long_running'), surface_slot='analysis.contrast.frequency_diff', lifecycle=_analysis_job_lifecycle()),
        ),
        action_types=("analysis/frequency",),
    ),
    ui_capability("analysis.async_jobs", lt("Beobachtbare lang laufende Analysejobs", "Observable long-running analysis jobs"), "analysis",
        maturity="stable",
        operations=(
            operation('analysis.async_jobs.status', lt("Analysejob-Status", "Analysis job status"), '/api/v1/analysis/jobs/{job_id}', surface_slot='analysis.jobs.status', lifecycle=_analysis_job_lifecycle()),
            operation('analysis.async_jobs.cancel', lt("Analysejob abbrechen", "Cancel analysis job"), '/api/v1/analysis/jobs/{job_id}/cancel', surface_slot='analysis.jobs.cancel', lifecycle=_analysis_job_lifecycle()),
            operation('analysis.async_jobs.rows', lt("Analysejob-Zeilen", "Analysis job rows"), '/api/v1/analysis/jobs/{job_id}/rows', surface_slot='analysis.jobs.rows'),
        ),
    ),
    route_capability("analysis.realtime_jobs", lt("Echtzeitübertragung für Analysejobs", "Realtime analysis job transport"), "analysis", "/api/v1/ws-ticket", "/api/v1/ws/analysis/{job_id}"),
    ui_capability("analysis.collocations", lt("Kollokationsanalyse", "Collocation analysis"), "analysis",
        maturity="stable",
        operations=(
            operation("analysis.collocations.job", lt("Kollokationsjob", "Collocation job"), "/api/v1/analysis/collocates/job",
                effects=("read", "long_running"),
                copilot_tools=("collocate_stats",),
                input_schema_ref="analysis.term_job_request",
                lifecycle=_analysis_job_lifecycle(),
            ),
            operation('analysis.collocations.kwic', lt("Co-KWIC", "Co-KWIC"), '/api/v1/analysis/collocates/kwic', surface_slot='analysis.collocations.evidence'),
        ),
        action_types=("analysis/collocations",),
    ),
    ui_capability("analysis.collocation_network", lt("Kollokationsnetzwerk", "Collocation network"), "analysis",
        operations=(
            operation('analysis.collocation_network.graph', lt("Kollokationsnetzwerk", "Collocation network"), ProductBackendRoute('/api/v1/analysis/collocation_network', ('GET',)), copilot_tools=('collocation_network',)),
        ),
        action_types=("analysis/collocationNetwork",),
    ),
    ui_capability("analysis.dispersion", lt("Dispersionsanalyse", "Dispersion analysis"), "analysis",
        maturity="stable",
        operations=(
            operation('analysis.dispersion.stats', lt("Dispersionsanalyse", "Dispersion analysis"), '/api/v1/analysis/dispersion'),
            operation('analysis.dispersion.offsets', lt("Dispersions-Offsets", "Dispersion offsets"), '/api/v1/analysis/dispersion_offsets', copilot_tools=('dispersion_offsets',)),
        ),
        action_types=("analysis/dispersion",),
    ),
    ui_capability("analysis.trend", lt("Diachroner Frequenzverlauf", "Diachronic frequency trend"), "analysis",
        operations=(
            operation(
                'analysis.trend.compute',
                lt("Frequenzverlauf (Trend)", "Frequency trend"),
                ProductBackendRoute('/api/v1/analysis/trend', ('POST',)),
                copilot_tools=('trend_analysis',),
            ),
        ),
        limits=(
            lt("Die Trend-Buckets stammen aus einem Datumsfeld der Dokumentmetadaten (führendes YYYY bzw. YYYY-MM). Führt kein Dokument des Korpus das Feld, antwortet die Route mit 422. Dokumente ohne parsbares Datum landen in einem ausdrücklichen Bucket 'undatiert'.", "Trend buckets come from a document-metadata date field (leading YYYY / YYYY-MM). If no document of the corpus has the field, the route answers 422. Documents without a parseable date land in an explicit 'undatiert' bucket."),
        ),
    ),
    ui_capability("analysis.ngrams", lt("N-Gramm-Analyse", "N-gram analysis"), "analysis",
        operations=(
            operation("analysis.ngrams.frequency_job", lt("N-Gramm-Frequenzjob", "N-gram frequency job"), "/api/v1/analysis/ngrams/job",
                effects=("read", "long_running"),
                copilot_tools=("ngram_frequency",),
                surface_slot="analysis.ngrams.job",
                priority=20,
                input_schema_ref="analysis.ngram_job_request",
                lifecycle=_analysis_job_lifecycle(),
            ),
            operation("analysis.ngrams.diff_job", lt("N-Gramm-Kontrastjob", "N-gram contrast job"), "/api/v1/analysis/ngrams_diff/job",
                effects=("read", "long_running"),
                copilot_tools=("ngram_contrast",),
                surface_slot="analysis.ngrams.diff",
                priority=30,
                input_schema_ref="analysis.ngram_diff_job_request",
                lifecycle=_analysis_job_lifecycle(),
            ),
        ),
        action_types=("analysis/ngramFrequency", "analysis/ngramContrast"),
    ),
    ui_capability("analysis.keyness", lt("Keyness mit Inferenzstatistik", "Keyness with inferential statistics"), "analysis",
        operations=(
            operation("analysis.keyness.job", lt("Keyness-Job", "Keyness job"), "/api/v1/analysis/keyness/job",
                effects=("read", "long_running"),
                copilot_tools=("keyness",),
                input_schema_ref="analysis.docset_pair_request",
                lifecycle=_analysis_job_lifecycle(),
            ),
        ),
        action_types=("analysis/keyness",),
        limits=(
            lt("Keyness vergleicht disjunkte Docsets, ein Ziel-Docset mit dem Rest seines Korpus oder ein zweites Korpus. Eine externe deutsche Referenzfrequenzliste wird nicht mitgeliefert.", "Keyness compares disjoint document sets, a target document set with the remainder of its corpus, or a second corpus. There is no bundled external German reference-frequency list."),
            lt("Externe Frequenztabellen bleiben der API vorbehalten und verlangen ein vollständiges Vokabular, eine exakte Gesamtsumme und denselben POS-Umfang, bevor inferenzstatistische Werte ausgegeben werden.", "External frequency maps remain API-only and require a complete vocabulary, an exact total, and matching POS scope before inferential scores are emitted."),
        ),
    ),
    operation_capability(
        "analysis.sync_collocations_api",
        lt("Synchrone Kollokations-API", "Synchronous collocation API"),
        "analysis",
        operation('analysis.sync_collocations_api.stats', lt("Synchrone Kollokationsstatistik", "Synchronous collocation statistics"), '/api/v1/analysis/collocates', surface_slot='analysis.collocations.sync_api'),
    ),
    operation_capability(
        "analysis.sync_ngrams_api",
        lt("Synchrone N-Gramm-API", "Synchronous n-gram API"),
        "analysis",
        operation('analysis.sync_ngrams_api.frequency', lt("Synchrone N-Gramm-Frequenz", "Synchronous n-gram frequency"), '/api/v1/analysis/ngrams', input_schema_ref='analysis.ngram_job_request', surface_slot='analysis.ngrams.sync_api'),
    ),
    operation_capability(
        "analysis.sync_keyness_api",
        lt("Synchrone Keyness-API", "Synchronous keyness API"),
        "analysis",
        operation('analysis.sync_keyness_api.stats', lt("Synchrone Keyness-Statistik", "Synchronous keyness statistics"), '/api/v1/analysis/keyness', input_schema_ref='analysis.docset_pair_request', surface_slot='analysis.keyness.sync_api'),
    ),
    ui_capability("analysis.contrast", lt("Kontrastanalysen mit und ohne Paarung", "Pairing-free and paired contrast analyses"), "analysis",
        operations=(
            operation("analysis.contrast.free_job", lt("Freier Kontrastjob", "Free contrast job"), "/api/v1/analysis/contrast",
                effects=("read", "long_running"),
                surface_slot="analysis.contrast.free",
                input_schema_ref="analysis.term_docset_pair_request",
                lifecycle=_analysis_job_lifecycle(),
            ),
            operation("analysis.contrast.collocations_diff_job", lt("Kollokations-Kontrastjob", "Collocation contrast job"), "/api/v1/analysis/collocates_diff/job",
                effects=("read", "long_running"),
                copilot_tools=("compare_collocates", "contrast_collocates"),
                surface_slot="analysis.contrast.collocations",
                input_schema_ref="analysis.collocates_diff_job_request",
                lifecycle=_analysis_job_lifecycle(),
            ),
            operation('analysis.contrast.lexical_diversity', lt("Lexikalische Diversität", "Lexical diversity"), '/api/v1/analysis/lexical-diversity', copilot_tools=('lexical_diversity',)),
        ),
        action_types=("analysis/freeContrast", "analysis/collocationContrast", "analysis/lexicalDiversity"),
    ),
    ui_capability("analysis.wordsketch", lt("Word Sketches", "Word sketches"), "analysis",
        operations=(
            operation(
                "analysis.wordsketch.profile",
                lt("Word Sketch", "Word sketch"),
                ProductBackendRoute(
                    "/api/v1/analysis/wordsketch",
                    ("POST",),
                    requires_corpus_features=("token_attributes.rel",),
                ),
                input_schema_ref="analysis.wordsketch_request",
                copilot_tools=("word_sketch",),
            ),
            operation(
                "analysis.wordsketch.diff",
                lt("Word-Sketch-Vergleich", "Word sketch comparison"),
                ProductBackendRoute(
                    "/api/v1/analysis/wordsketch_diff",
                    ("POST",),
                    requires_corpus_features=("token_attributes.rel",),
                ),
                input_schema_ref="analysis.wordsketch_diff_request",
            ),
        ),
        action_types=("analysis/wordSketch", "analysis/wordSketchDiff"),
    ),
    ui_capability("analysis.semantic_similarity", lt("Werkzeuge für semantische Ähnlichkeit", "Semantic similarity tools"), "analysis",
        operations=(
            operation("analysis.semantic_similarity.similar_words", lt("Distributioneller Wort-Thesaurus", "Similar words"), ProductBackendRoute("/api/v1/semantic/similar_words", ("GET",), requires_corpus_features=("semantic.word_similarity",)),
                copilot_tools=("similar_words",),
                surface_slot="analysis.semantic_similarity.words",
            ),
            operation("analysis.semantic_similarity.passage_search", lt("Semantische Passagensuche", "Semantic search"),
                ProductBackendRoute(
                    "/api/v1/analysis/embedding_search",
                    ("POST",),
                    requires_corpus_features=("semantic.passage_search",),
                ),
                input_schema_ref="analysis.semantic_search_request",
                copilot_tools=("semantic_search",),
                surface_slot="analysis.semantic_similarity.passages",
            ),
        ),
        action_types=("analysis/semantic",),
        limits=(
            lt("Semantische Passagensuche und Wort-Thesaurus liefern in diesem Release explorative Ergebnisse in der Oberfläche und in Werkzeugen. Für semantische Ergebnislisten gibt es keinen vollständigen Exportweg nach CSV oder EvidencePackage.", "Semantic search and similar words are exploratory in-app/tool results in this release. Semantic result lists do not have a complete CSV/EvidencePackage export path."),
            lt("Der Wort-Thesaurus wird nicht als gespeicherte Analyse oder Workspace-Artefakt angeboten. Für zitierbare Belege oder einen Export die Nachbarwörter zuerst in die KWIC-Suche übernehmen.", "Similar words are not advertised as a saved analysis/workspace artifact. Transfer similar words into KWIC first when citable evidence or export is needed."),
        ),
    ),
    route_capability(
        "analysis.semantic_clustering",
        lt("Abläufe für semantisches Clustering", "Semantic clustering workflows"),
        "analysis",
        "/api/v1/semantic/cluster",
        "/api/v1/semantic/cluster_words",
        "/api/v1/semantic/clusters/apply",
        "/api/v1/semantic/outline",
        "/api/v1/semantic/recluster",
        "/api/v1/projects/{proj}/clusters",
        "/api/v1/projects/{proj}/clusters/rename",
        copilot_tools=(
            "semantic_cluster",
            "semantic_cluster_words",
            "refine_cluster_label",
            "semantic_recluster",
            "cluster_save",
            "cluster_export_md",
        ),
        maturity="experimental",
        visibility="hidden_experimental",
    ),
    ui_capability("settings.model_route", lt("Modellweg", "Model connection"), "settings",
        operations=(
            operation(
                "settings.model_route.read",
                lt("Modellweg laden", "Load model connection"),
                "/api/v1/settings/model-route",
                input_schema_ref="operation.no_input",
                surface_slot="settings.model_route.read",
            ),
            operation(
                "settings.model_route.update",
                lt("Modellweg umstellen", "Change model connection"),
                "/api/v1/settings/model-route",
                effects=("write",),
                surface_slot="settings.model_route.update",
                priority=2,
            ),
        ),
    ),
    ui_capability("settings.embedding_management", lt("Verwaltung der Embedding-Modelle", "Embedding model management"), "settings",
        operations=(
            operation('settings.embedding_management.list', lt("Embedding-Modelle laden", "Load embedding models"), '/api/v1/embeddings/list', input_schema_ref='operation.no_input', surface_slot='settings.embeddings.list'),
            operation(
                "settings.embedding_management.local_index_preflight",
                lt("Lokalen Semantik-Build prüfen", "Check local semantic index build"),
                "/api/v1/embeddings/local-index/preflight",
                input_schema_ref="operation.query_params",
                surface_slot="settings.embeddings.local_index.preflight",
                priority=15,
            ),
            operation(
                "settings.embedding_management.local_index_build",
                lt("Lokalen semantischen Index erstellen", "Build local semantic index"),
                "/api/v1/embeddings/local-index/build",
                effects=("write", "long_running"),
                input_schema_ref="settings.embedding_management.local_index_build_request",
                surface_slot="settings.embeddings.local_index.build",
                priority=16,
                lifecycle=_local_semantic_index_lifecycle(),
            ),
            operation(
                "settings.embedding_management.local_index_status",
                lt("Semantik-Build-Status laden", "Load semantic index build status"),
                "/api/v1/embeddings/local-index/builds/{run_id}",
                surface_slot="settings.embeddings.local_index.status",
                priority=17,
                lifecycle=_local_semantic_index_lifecycle(),
            ),
            operation(
                "settings.embedding_management.local_index_cancel",
                lt("Semantik-Build abbrechen", "Cancel semantic index build"),
                "/api/v1/embeddings/local-index/builds/{run_id}/cancel",
                effects=("write", "destructive"),
                surface_slot="settings.embeddings.local_index.cancel",
                priority=18,
                lifecycle=_local_semantic_index_lifecycle(),
            ),
            operation("settings.embedding_management.download", lt("Embedding-Modell installieren", "Install embedding model"), "/api/v1/embeddings/download",
                effects=("write", "long_running"),
                surface_slot="settings.embeddings.download",
                input_schema_ref="settings.embedding_management.download_request",
                lifecycle=_embedding_download_lifecycle(),
            ),
            operation("settings.embedding_management.download_status", lt("Embedding-Download-Status laden", "Load embedding download status"), "/api/v1/operation-runs/{run_id}",
                surface_slot="settings.embeddings.download.status",
                priority=25,
                lifecycle=_embedding_download_lifecycle(),
            ),
            operation("settings.embedding_management.remove", lt("Embedding-Modell entfernen", "Remove embedding model"), "/api/v1/embeddings/remove",
                effects=("write", "destructive"),
                surface_slot="settings.embeddings.remove",
                priority=30,
                input_schema_ref="settings.embedding_management.remove_request",
            ),
            operation("settings.embedding_management.set_active", lt("Embedding-Backend setzen (spacy oder none)", "Set the embedding backend (spacy or none)"), "/api/v1/settings/embeddings",
                surface_slot="settings.embeddings.active",
                priority=40,
                input_schema_ref="settings.embedding_management.set_active_request",
            ),
            operation(
                "settings.embedding_management.backend",
                lt("Embedding-Backend laden", "Load the embedding backend"),
                ProductBackendRoute("/api/v1/settings/embeddings", ("GET",)),
                surface_slot="settings.embeddings.backend",
                priority=35,
            ),
        ),
        limits=(
            lt(
                "Das Embedding-Backend ist spacy (Vektoren von spaCy-Pipelines: "
                "Passagenindex und Wortcluster nehmen die Pipeline des Korpus, "
                "CANDYCONC_EMB_SPACY_MODEL dient dem Übrigen) oder none "
                "(abgeschaltet). Andere Werte lehnt der Server ab. Eine Umstellung "
                "gilt bis zum Neustart.",
                "The embedding backend is spacy (vectors of spaCy pipelines: the "
                "passage index and word clusters take the pipeline of the corpus, "
                "CANDYCONC_EMB_SPACY_MODEL serves the rest) or none (off). The server "
                "rejects other values. A change lasts until the server stops.",
            ),
            lt(
                "Die Liste der Wortvektorpakete kommt aus vendor/embedding_packages.json "
                "im Paket. Diese Ausgabe liefert die Datei nicht mit, die Liste ist leer. "
                "Ein installiertes Paket liest keine Analyse: Der Wort-Thesaurus nutzt "
                "einen Wortvektorindex im Korpus oder die statischen Wortvektoren der "
                "Pipeline, die das Korpus annotiert hat, die semantische Suche den "
                "lokalen semantischen Index des Korpus.",
                "The list of word vector packages comes from vendor/embedding_packages.json "
                "in the package. This release does not ship the file, so the list is "
                "empty. No analysis reads an installed package: similar words use a "
                "word vector index in the corpus or the static word vectors of the "
                "pipeline that annotated the corpus, semantic search uses the local "
                "semantic index of the corpus.",
            ),
        ),
    ),
    ui_capability("admin.system_operations", lt("Systemstatus und Verwaltungsoperationen", "System status and administrative operations"), "admin",
        operations=(
            operation('admin.system_operations.info', lt("Systeminformationen laden", "Load system information"), '/api/v1/system/info', surface_slot='settings.system.info'),
            operation("admin.system_operations.clear_cache", lt("Systemcache leeren", "Clear system cache"), "/api/v1/system/clear-cache",
                effects=("write", "destructive"),
                surface_slot="settings.system.clear_cache",
                input_schema_ref="operation.no_input",
                requires_parameters=False,
            ),
        ),
    ),
    ui_capability("settings.preferences", lt("Nutzereinstellungen und einfache Speicherung von Arbeitsständen", "User preferences and lightweight workflow persistence"), "settings",
        maturity="stable",
        operations=(
            operation('settings.preferences.read', lt("Nutzereinstellungen laden", "Load user settings"), '/api/v1/prefs', input_schema_ref='operation.no_input'),
            operation('settings.preferences.update', lt("Nutzereinstellungen speichern", "Save user settings"), '/api/v1/prefs/update', input_schema_ref='settings.preferences.update_request'),
        ),
    ),
    ui_capability("corpus.catalogue", lt("Korpuskatalog, Aktivierung und Fähigkeitsangaben je Korpus", "Corpus catalog, activation, and per-corpus capability flags"), "corpus",
        maturity="stable",
        operations=(
            operation('corpus.catalogue.list', lt("Korpuskatalog laden", "Load corpus catalog"), '/api/v1/corpora', input_schema_ref='operation.no_input'),
            operation('corpus.catalogue.register', lt("Bestehenden Korpus registrieren", "Register existing corpus"), '/api/v1/corpora/register', input_schema_ref='corpus.catalogue.register_request'),
            operation('corpus.catalogue.activate', lt("Aktiven Korpus setzen", "Set active corpus"), '/api/v1/corpora/{corpus}/activate'),
            operation('corpus.catalogue.capabilities', lt("Korpusfähigkeiten laden", "Load corpus capabilities"), '/api/v1/corpora/{corpus}/capabilities'),
            operation('corpus.catalogue.unregister', lt("Korpusregistrierung entfernen", "Remove corpus registration"), '/api/v1/corpora/{corpus}/registration'),
        ),
    ),
    ui_capability("corpus.import", lt("Beobachtbarer Korpusimport", "Observable corpus import"), "corpus",
        operations=(
            operation('corpus.import.methods', lt("Importmethoden laden", "Load import methods"), '/api/v1/corpora/import-methods', input_schema_ref='operation.no_input'),
            operation('corpus.import.preflight', lt("Import-Preflight", "Import preflight check"), '/api/v1/corpora/import-preflight', input_schema_ref='corpus.import.preflight_request'),
            operation('corpus.import.jobs_list', lt("Importjobs listen", "List import jobs"), ProductBackendRoute('/api/v1/corpora/imports', ('GET',)), surface_slot='corpus.import.jobs.list', input_schema_ref='operation.no_input'),
            operation("corpus.import.start", lt("Korpusimport starten", "Start corpus import"), ProductBackendRoute("/api/v1/corpora/imports", ("POST",), mutates=True),
                effects=("write", "long_running"),
                input_schema_ref="corpus.import.start_request",
                lifecycle=_corpus_import_job_lifecycle(),
            ),
            operation('corpus.import.job_status', lt("Importjob-Status laden", "Load import job status"), '/api/v1/corpora/imports/{job_id}', surface_slot='corpus.import.job.status', lifecycle=_corpus_import_job_lifecycle()),
            operation('corpus.import.job_cancel', lt("Importjob abbrechen", "Cancel import job"), '/api/v1/corpora/imports/{job_id}/cancel', surface_slot='corpus.import.job.cancel', lifecycle=_corpus_import_job_lifecycle()),
            operation('corpus.import.job_reports', lt("Importjob-Reports laden", "Load import job reports"), '/api/v1/corpora/imports/{job_id}/reports', surface_slot='corpus.import.job.reports'),
            operation('corpus.import.build_report', lt("Korpus-Buildreport laden", "Load corpus build report"), '/api/v1/corpora/{corpus}/build-report'),
        ),
        limits=(
            lt("Die Oberfläche importiert Parquet- und VRT-Dateien, ungepaarte CSV-, JSONL-, Klartext- und Hugging-Face-Daten sowie extern gepaarte Dateien mit Paarschlüssel, jeweils mit Vorprüfung und Fortschrittsanzeige.", "The interface imports Parquet and VRT files, unpaired CSV, JSONL, plain text and Hugging Face data, and externally paired files with a pair key, each with a preflight check and a progress view."),
            lt("Paarungen über Satzeinbettungen (embed- und hybrid-Alignment) laufen nur über Kommandozeile und API, solange die Oberfläche ihre Eingaben, Kosten, Berichte und Prüfung nicht abdeckt.", "Pairings through sentence embeddings (embed and hybrid alignment) run only from the command line and the API, as long as the interface does not cover their inputs, costs, reports, and checks."),
            lt("Die Liste der Importaufträge besteht nur, solange der Server läuft. Sie übersteht keinen Neustart und keinen Server mit mehreren Worker-Prozessen. Dauerhaft festgehalten ist jeder Import in seinem Importbericht und dem Build-Report des Korpus.", "The list of import jobs exists only while the server runs. It does not survive a restart or a server with several worker processes. Each import is kept permanently in its import report and in the build report of the corpus."),
            lt("Hugging-Face-Datensätze werden erst beim Import heruntergeladen, trust_remote_code bleibt immer ausgeschaltet. Die Vorprüfung prüft die Angaben ohne Netzzugriff.", "Hugging Face datasets are downloaded only when the import runs, and trust_remote_code is always off. The preflight check validates the descriptor without network access."),
        ),
    ),
    ui_capability("corpus.alignment_parallel", lt("Alignierungshilfen für Paarkorpora", "Alignment helpers for paired corpora"), "corpus",
        operations=(
            operation('corpus.alignment_parallel.alignment_ref_doc', lt("Alignment-Referenzdokument", "Alignment reference document"), '/api/v1/analysis/alignment/ref_doc', effects=('read', 'long_running'), surface_slot='kwic.workspace.parallel', priority=20),
            operation('corpus.alignment_parallel.parallel_kwic', lt("Parallel-KWIC", "Parallel concordance"), '/api/v1/analysis/kwic_parallel', effects=('read', 'long_running'), copilot_tools=('parallel_kwic',), surface_slot='kwic.row.parallel', priority=10),
            operation("corpus.alignment_parallel.parallel_groups", lt("Parallelgruppen", "Parallel groups"), "/api/v1/analysis/parallel_groups",
                effects=("read", "long_running"),
                copilot_tools=("parallel_groups",),
                surface_slot="workspace.subcorpora.parallel",
            ),
        ),
        copilot_tools=("parallel_groups", "parallel_kwic"),
        limits=(
            lt("Die Parallelhilfen setzen ein Index-Manifest mit Paarungsmerkmalen voraus. Die vollwertige Ausführung folgt weiterhin dem Vertrag legacy_ref_doc_v1.", "Parallel helpers require an index manifest with pairing features. Current first-class execution remains the legacy_ref_doc_v1 contract."),
            lt("Generische Beschriftungen der Paarachsen können als Beleg angezeigt werden, generisches Filtern und Auswählen nach Achsen ist in diesem Release aber kein vollwertiger Analyseablauf.", "Generic pair-axis labels can be displayed as evidence, but generic axis filtering/axis selection is not a first-class analysis workflow in this release."),
        ),
    ),
    ui_capability("research.subcorpora_docsets", lt("Subkorpora, Docsets und Metadaten-Suchbereiche", "Subcorpora, document sets, and metadata scopes"), "research_workflow",
        operations=(
            operation('research.subcorpora_docsets.meta_schema', lt("Metadatenschema laden", "Load metadata schema"), '/api/v1/analysis/meta_schema', surface_slot='research.subcorpora.meta_schema'),
            operation('research.subcorpora_docsets.meta_values', lt("Metadatenwerte laden", "Load metadata values"), '/api/v1/analysis/meta_values', copilot_tools=('metadata_values',), surface_slot='research.subcorpora.meta_values'),
            operation('research.subcorpora_docsets.meta_counts', lt("Metadatenzählungen laden", "Load metadata counts"), '/api/v1/analysis/meta_counts', surface_slot='research.subcorpora.meta_counts'),
            operation('research.subcorpora_docsets.docset_from_meta', lt("Metadaten-Docset bauen", "Build subcorpus from metadata"), '/api/v1/analysis/docset_from_meta', effects=('read', 'long_running'), surface_slot='research.subcorpora.docset_from_meta'),
            operation("research.subcorpora_docsets.docset_from_search", lt("Query-Docset bauen", "Build subcorpus from search"), "/api/v1/analysis/docset_from_search",
                effects=("read", "long_running"),
                copilot_tools=("create_docset",),
                surface_slot="research.subcorpora.docset_from_search",
            ),
            operation('research.subcorpora_docsets.docset_intersection', lt("Docset-Intersection bauen", "Build intersection of subcorpora"), '/api/v1/analysis/docset_intersection', effects=('read', 'long_running'), surface_slot='research.subcorpora.docset_intersection'),
            operation('research.subcorpora_docsets.subcorpora_list', lt("Subkorpora laden", "Load subcorpora"), ProductBackendRoute('/api/v1/subcorpora', ('GET',)), copilot_tools=('list_docsets',), surface_slot='research.subcorpora.list'),
            operation('research.subcorpora_docsets.subcorpora_save', lt("Subkorpus speichern", "Save subcorpus"), ProductBackendRoute('/api/v1/subcorpora', ('POST',), mutates=True), surface_slot='research.subcorpora.save'),
            operation('research.subcorpora_docsets.subcorpora_delete', lt("Subkorpus löschen", "Delete subcorpus"), ProductBackendRoute('/api/v1/subcorpora/{name}', ('DELETE',), mutates=True), surface_slot='research.subcorpora.delete'),
            operation("research.subcorpora_docsets.subcorpora_resolve", lt("Subkorpus frisch auflösen", "Resolve subcorpus again"), "/api/v1/subcorpora/{name}/resolve",
                effects=("read", "long_running"),
                copilot_tools=("resolve_subcorpus",),
                surface_slot="research.subcorpora.resolve",
                input_schema_ref="operation.generic_request",
            ),
        ),
    ),
    ui_capability("research.annotations", lt("Zeilenannotation in KWIC", "KWIC line annotation workflow"), "research_workflow",
        backend_routes=(
            "/api/v1/annotations",
            "/api/v1/annotations/{row_id}",
            ANNOTATION_SCHEME_READ,
            ANNOTATION_SCHEME_PREVIEW,
            ANNOTATION_SCHEME_WRITE,
            ANNOTATION_SETTINGS_READ,
            ANNOTATION_SETTINGS_WRITE,
            "/api/v1/annotations/agreement",
        ),
        operations=(
            operation('research.annotations.read', lt("Annotationen laden", "Load line annotations"), '/api/v1/annotations', input_schema_ref='research.annotations.query', surface_slot='kwic.annotations.read'),
            operation("research.annotations.write", lt("Annotation speichern", "Save line annotation"), ProductBackendRoute("/api/v1/annotations/{row_id}", ("PUT",), mutates=True),
                surface_slot="kwic.annotations.write",
                input_schema_ref="research.annotations.row_mutation",
            ),
            operation("research.annotations.delete", lt("Annotation löschen", "Delete line annotation"), ProductBackendRoute("/api/v1/annotations/{row_id}", ("DELETE",), mutates=True),
                surface_slot="kwic.annotations.delete",
                input_schema_ref="research.annotations.row_mutation",
            ),
            operation('research.annotations.scheme_read', lt("Kodierschema laden", "Load coding scheme"), ANNOTATION_SCHEME_READ, input_schema_ref='research.annotations.query', surface_slot='kwic.annotations.scheme.read', priority=50),
            operation('research.annotations.scheme_preview', lt("Schemaänderung prüfen", "Check coding scheme change"), ANNOTATION_SCHEME_PREVIEW, surface_slot='kwic.annotations.scheme.preview', priority=55, input_schema_ref='research.annotations.scheme_write_request'),
            operation('research.annotations.scheme_write', lt("Kodierschema speichern", "Save coding scheme"), ANNOTATION_SCHEME_WRITE, surface_slot='kwic.annotations.scheme.write', priority=60, input_schema_ref='research.annotations.scheme_write_request'),
            operation('research.annotations.settings_read', lt("Annotationseinstellungen laden", "Load annotation settings"), ANNOTATION_SETTINGS_READ, input_schema_ref='research.annotations.query', surface_slot='kwic.annotations.settings.read', priority=70),
            operation("research.annotations.settings_write", lt("Annotationseinstellungen speichern", "Save annotation settings"), ANNOTATION_SETTINGS_WRITE,
                surface_slot="kwic.annotations.settings.write",
                priority=80,
                input_schema_ref="research.annotations.settings_write_request",
            ),
            operation("research.annotations.agreement", lt("Inter-Annotator-Übereinstimmung laden", "Load inter-annotator agreement"), "/api/v1/annotations/agreement",
                input_schema_ref="research.annotations.query",
                surface_slot="kwic.annotations.agreement",
                priority=90,
            ),
        ),
        limits=(
            lt("Die Oberfläche deckt die Kodierung einzelner Zeilen, die Bearbeitung des Kodierschemas und korpusweite Übereinstimmungsmaße ab.", "The interface supports row-level coding, coding-scheme editing, and corpus-wide agreement metrics."),
            lt("Prüfwarteschlange, Adjudikationsentscheidungen, Konfliktmatrix und Goldstandard-Export sind keine releasefähigen Abläufe der Oberfläche.", "Review queue, adjudication decisions, conflict matrix, and gold-standard export are not release-ready UI workflows."),
        ),
    ),
    operation_capability(
        "research.annotations_multi_api",
        lt("API für die vollständige Annotationstabelle aller Kodierer", "Full multi-coder annotation table API"),
        "research_workflow",
        operation('research.annotations_multi_api.read', lt("Multi-Coder-Annotationen laden", "Load multi-coder annotations"), '/api/v1/annotations/multi', surface_slot='kwic.annotations.multi_api'),
        limits=(lt("Die API stellt die vollständige Annotationstabelle aller Kodierer bereit.", "The API provides the full annotation table across coders."),),
    ),
    route_capability(
        "research.annotations_import",
        lt("Massenimport von Zeilenannotationen", "Line annotation bulk import"),
        "research_workflow",
        "/api/v1/annotations/import",
        limits=(lt("Annotationen lassen sich über die API gesammelt importieren.", "Annotations can be imported in bulk through the API."),),
    ),
    ui_capability("research.bookmarks", lt("Lesezeichen für KWIC-Auswahlen", "KWIC selection bookmarks"), "research_workflow",
        operations=(
            operation('research.bookmarks.read', lt("Lesezeichen laden", "Load bookmarks"), '/api/v1/prefs'),
            operation('research.bookmarks.write', lt("Lesezeichen speichern/löschen", "Save or delete bookmarks"), '/api/v1/prefs/update'),
        ),
        action_types=("bookmark/add", "bookmark/remove", "bookmark/clear"),
    ),
    ui_capability("research.analysis_presets", lt("Analyse-Presets und wiederverwendbare Workspaces", "Saved analyses and reusable workspaces"), "research_workflow",
        backend_routes=(
            ProductBackendRoute("/api/v1/projects/{proj}/analysis-presets", ("GET",)),
            ProductBackendRoute("/api/v1/projects/{proj}/analysis-presets", ("POST",), mutates=True),
            "/api/v1/projects/{proj}/analysis-presets/{preset_id}",
            "/api/v1/projects/{proj}/analysis-presets/{preset_id}/touch",
        ),
        operations=(
            operation('research.analysis_presets.list', lt("Analyse-Presets laden", "Load saved analyses"), ProductBackendRoute('/api/v1/projects/{proj}/analysis-presets', ('GET',))),
            operation('research.analysis_presets.create', lt("Analyse-Preset speichern", "Save analysis"), ProductBackendRoute('/api/v1/projects/{proj}/analysis-presets', ('POST',), mutates=True)),
            operation("research.analysis_presets.update", lt("Analyse-Preset aktualisieren", "Update saved analysis"), ProductBackendRoute("/api/v1/projects/{proj}/analysis-presets/{preset_id}", ("PATCH",), mutates=True),
                input_schema_ref="operation.generic_request",
            ),
            operation('research.analysis_presets.delete', lt("Analyse-Preset löschen", "Delete saved analysis"), ProductBackendRoute('/api/v1/projects/{proj}/analysis-presets/{preset_id}', ('DELETE',), mutates=True)),
            operation('research.analysis_presets.touch', lt("Analyse-Preset zuletzt-verwendet markieren", "Mark saved analysis as last used"), '/api/v1/projects/{proj}/analysis-presets/{preset_id}/touch'),
        ),
    ),
    ui_capability("research.copilot_grounding", lt("Recherche-Copilot", "Research copilot"), "copilot",
        operations=(
            operation('research.copilot_grounding.chat_stream', lt("Copilot-Chat streamen", "Stream copilot chat"), '/api/v1/chat/stream', effects=('read', 'long_running'), surface_slot='research.copilot.chat_stream', response_shape='stream'),
            operation('research.copilot_grounding.action_approve', lt("Copilot-Aktion genehmigen", "Approve copilot action"), '/api/v1/copilot/action/approve', surface_slot='research.copilot.action.approve'),
            operation('research.copilot_grounding.action_reject', lt("Copilot-Aktion ablehnen", "Reject copilot action"), '/api/v1/copilot/action/reject', surface_slot='research.copilot.action.reject'),
            operation('research.copilot_grounding.clarification_answer', lt("Copilot-Rückfrage beantworten", "Answer copilot clarification question"), '/api/v1/copilot/clarify/answer', surface_slot='research.copilot.clarification.answer'),
            operation('research.copilot_grounding.context_update', lt("Copilot-Kontext aktualisieren", "Update copilot context"), '/api/v1/copilot/context', surface_slot='research.copilot.context.update'),
            operation('research.copilot_grounding.continue', lt("Copilot-Orchestrierung fortsetzen", "Continue copilot orchestration"), '/api/v1/copilot/continue', effects=('read', 'long_running'), surface_slot='research.copilot.continue', response_shape='stream'),
        ),
        action_types=(
            "copilot/setAutonomy",
            "copilot/open",
            "copilot/close",
            "copilot/sendMessage",
            "copilot/answerClarification",
            "copilot/continue",
            "ghost/moveTo",
            "ghost/click",
            "ghost/hide",
        ),
    ),
    route_capability(
        "research.copilot_chat_api",
        lt("Copilot-Chat-API ohne Streaming", "Non-streaming copilot chat API"),
        "copilot",
        "/api/v1/chat",
    ),
    ui_capability("research.replay_export", lt("Replay, Laufbelege und Exporte", "Replay, run evidence, and exports"), "research_workflow",
        operations=(
            operation("research.replay_export.concordance", lt("Vollständige Konkordanz exportieren", "Export full concordance"), ProductBackendRoute("/api/v1/export/concordance", ("POST",)),
                effects=("read", "long_running"),
                input_schema_ref="research.replay_export.concordance_request",
                response_shape="file",
            ),
            operation('research.replay_export.evidence_package', lt("EvidencePackage exportieren", "Export evidence package"), '/api/v1/export/evidence-package', effects=('read', 'long_running'), input_schema_ref='research.replay_export.evidence_package_request'),
            operation('research.replay_export.pdf', lt("PDF-Report exportieren", "Export PDF report"), '/api/v1/export/pdf', effects=('read', 'long_running'), input_schema_ref='research.replay_export.report_render_request', response_shape='file'),
            operation('research.replay_export.docx', lt("DOCX-Report exportieren", "Export DOCX report"), '/api/v1/export/docx', effects=('read', 'long_running'), input_schema_ref='research.replay_export.report_render_request', response_shape='file'),
        ),
        action_types=("export/data",),
    ),
    ui_capability("platform.session", lt("Session- und Anmeldestatus", "Session and authentication state"), "platform",
        maturity="stable",
        operations=(
            operation('platform.session.read', lt("Session-Status prüfen", "Check session status"), '/api/v1/auth/session', input_schema_ref='operation.no_input'),
            operation('platform.session.login', lt("Anmelden", "Sign in"), '/api/v1/login', input_schema_ref='platform.session.login_request'),
            operation('platform.session.logout', lt("Abmelden", "Sign out"), '/api/v1/logout', input_schema_ref='operation.no_input'),
        ),
    ),
    route_capability("platform.dev_token_api", lt("Endpunkt für lokale Entwicklungstoken", "Local development token endpoint"), "platform", "/api/v1/auth/dev-token", maturity="experimental", visibility="hidden_experimental"),
    route_capability("product.capability_contract", lt("Endpunkt des Fähigkeitsvertrags", "Product capability contract endpoint"), "platform", "/api/v1/capabilities", maturity="stable"),
    route_capability("corpus.destructive_delete", lt("Endgültiges Löschen eines Korpus", "Destructive corpus deletion"), "corpus", ProductBackendRoute("/api/v1/corpora/{corpus}", ("DELETE",), mutates=True)),
    route_capability("research.subcorpora_direct_lookup", lt("Direktabruf einer Subkorpusdefinition", "Direct subcorpus definition lookup"), "research_workflow", ProductBackendRoute("/api/v1/subcorpora/{name}", ("GET",))),
    route_capability("research.generated_artifact_downloads", lt("Download-Endpunkt für erzeugte Artefakte", "Generated artifact download endpoint"), "research_workflow", "/api/v1/download/{file_id}"),
    route_capability("research.mcp_tool_access", lt("Werkzeug-API", "Tool API"), "copilot", "/mcp/tools", "/mcp/call"),
    route_capability(
        "admin.project_management",
        lt("Projektverwaltung", "Project administration"),
        "admin",
        "/api/v1/projects/create",
        limits=(lt("Projekte lassen sich nur als Administrator über die API anlegen. Die Oberfläche enthält keinen vollwertigen Ablauf für die Projektverwaltung.", "Project creation is admin/API-only. No first-class project-management journey is shipped in the product UI."),),
    ),
    route_capability("admin.faiss_job_stream", lt("WebSocket-Stream für den FAISS-Neuaufbau", "FAISS rebuild WebSocket stream"), "admin", "/api/v1/ws/faiss/{job_id}"),
    route_capability(
        "admin.security_observability",
        lt("Verwaltung der Betriebsbeobachtung", "Operational observability administration"),
        "admin",
        "/api/v1/metrics",
        limits=(
            lt("Die Metriken sind nur lokal verfügbar und Administratoren vorbehalten. Sie enthalten weder Abfragetexte noch Korpusausschnitte.", "Metrics are local-only and admin-gated. No query text or corpus snippets are exposed there."),
            lt("Die Metriken sind eine Beobachtungsfläche für Administratoren und schalten von sich aus keinen externen Telemetrie-Exporter ein.", "Metrics are an admin observability surface and do not enable an external telemetry exporter by themselves."),
        ),
    ),
)


def _route_payload(route: ProductBackendRoute) -> dict[str, object]:
    payload = asdict(route)
    payload["methods"] = list(route.methods)
    payload["requires_corpus_features"] = list(route.requires_corpus_features)
    return payload


def _operation_lifecycle_payload(
    lifecycle: ProductOperationLifecycle | None,
) -> dict[str, object] | None:
    if lifecycle is None:
        return None
    payload = asdict(lifecycle)
    payload["terminal_statuses"] = list(lifecycle.terminal_statuses)
    return payload


def _operation_route_descriptor(operation: ProductOperation) -> ProductBackendRoute:
    return _backend_route_descriptor(operation.route)


def _operation_required_context(operation: ProductOperation) -> tuple[str, ...]:
    route = _operation_route_descriptor(operation)
    context = list(PRODUCT_OPERATION_REQUIRED_CONTEXT_BY_SCHEMA_ID.get(_operation_input_schema_ref(operation), ()))
    for param in re.findall(r"{([^}/]+)}", route.path):
        marker = f"route_param:{param}"
        if marker not in context:
            context.append(marker)
    if route.requires_corpus_features and "corpus_features" not in context:
        context.append("corpus_features")
    return tuple(context)


def _operation_priority(operation: ProductOperation, index: int) -> int:
    if operation.priority is not None:
        return operation.priority
    return (index + 1) * 10


def _operation_surface_slot(operation: ProductOperation) -> str:
    return operation.surface_slot or operation.id


def _operation_input_schema_ref(operation: ProductOperation) -> str:
    if operation.input_schema_ref is not None:
        return operation.input_schema_ref
    route = _operation_route_descriptor(operation)
    if "{" in route.path:
        return "operation.route_params"
    if route.methods == ("GET",):
        return "operation.query_params"
    return "operation.generic_request"


def _operation_ui_execution_policy(operation: ProductOperation) -> ProductOperationUiExecutionPolicy:
    # Product surfaces are already explicit user actions.  Do not turn normal
    # analysis, cancellation, cleanup or annotation work into native-dialog
    # loops; only removing a corpus registration needs a final confirmation.
    if operation.id == "corpus.catalogue.unregister":
        return "confirmed_contextual_ui"
    return "contextual_ui"


def _operation_response_shape(operation: ProductOperation) -> ProductOperationResponseShape:
    if operation.response_shape is not None:
        return operation.response_shape
    if operation.lifecycle is not None:
        return "job"
    return "data"


def _operation_effects(operation: ProductOperation) -> tuple[ProductOperationEffect, ...]:
    if operation.effects is not None:
        return operation.effects
    route = _operation_route_descriptor(operation)
    if route.mutates:
        return ("write",)
    return ("read",)


def _operation_run_semantics(operation: ProductOperation) -> ProductOperationRunSemantics:
    response_shape = _operation_response_shape(operation)
    if operation.lifecycle is not None and response_shape == "job":
        return "job_lifecycle"
    if "long_running" in _operation_effects(operation) and response_shape in {"data", "job"}:
        return "bounded_sync"
    if response_shape == "stream":
        return "stream"
    if response_shape == "file":
        return "file_export"
    return "instant"


def _capability_route_descriptors(capability: ProductCapability) -> list[ProductBackendRoute]:
    return _unique_route_descriptors(
        [
            *[_backend_route_descriptor(route) for route in capability.backend_routes],
            *[_operation_route_descriptor(operation) for operation in capability.operations],
        ]
    )


def _capability_declared_copilot_tools(capability: ProductCapability) -> list[str]:
    if capability.copilot_tools:
        return list(capability.copilot_tools)
    return list(dict.fromkeys(tool for operation in capability.operations for tool in operation.copilot_tools))


def _capability_payload(capability: ProductCapability) -> dict[str, object]:
    route_descriptors = _capability_route_descriptors(capability)
    requires_corpus_features = sorted(
        {
            *(
                feature
                for route in route_descriptors
                for feature in route.requires_corpus_features
            ),
        }
    )
    return {
        "id": capability.id,
        "title": capability.title,
        "area": capability.area,
        "maturity": capability.maturity,
        "visibility": capability.visibility,
        # Legacy field retained for existing clients. New clients should use
        # backend_route_descriptors for method/precondition-aware routing.
        "backend_routes": _unique_route_paths(route_descriptors),
        "backend_route_descriptors": [_route_payload(route) for route in route_descriptors],
        "operations": [
            {
                "id": operation.id,
                "capability_id": capability.id,
                "label": operation.label,
                "description": operation.description,
                "route": _route_payload(_operation_route_descriptor(operation)),
                "effects": list(_operation_effects(operation)),
                "copilot_tools": list(operation.copilot_tools),
                "surface_slot": _operation_surface_slot(operation),
                "priority": _operation_priority(operation, index),
                "input_schema_ref": _operation_input_schema_ref(operation),
                "required_context": list(_operation_required_context(operation)),
                "response_shape": _operation_response_shape(operation),
                "run_semantics": _operation_run_semantics(operation),
                "ui_execution_policy": _operation_ui_execution_policy(operation),
                "requires_parameters": operation.requires_parameters,
                "lifecycle": _operation_lifecycle_payload(operation.lifecycle),
            }
            for index, operation in enumerate(capability.operations)
        ],
        "action_types": list(capability.action_types),
        "copilot_tools": _capability_declared_copilot_tools(capability),
        "preconditions": list(capability.preconditions),
        "requires_corpus_features": requires_corpus_features,
        "limits": list(capability.limits),
        "notes": "",
    }


def _unique_route_paths(routes: list[ProductBackendRoute]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for route in routes:
        if route.path in seen:
            continue
        seen.add(route.path)
        unique.append(route.path)
    return unique


def _unique_route_descriptors(routes: list[ProductBackendRoute]) -> list[ProductBackendRoute]:
    seen: set[tuple[str, tuple[HttpMethod, ...], ProductRouteTransport]] = set()
    unique: list[ProductBackendRoute] = []
    for route in routes:
        key = (route.path, tuple(route.methods), route.transport)
        if key in seen:
            continue
        seen.add(key)
        unique.append(route)
    return unique


def _capability_copilot_tools(capability: ProductCapability) -> set[str]:
    return {
        *capability.copilot_tools,
        *(
            tool
            for operation in capability.operations
            for tool in operation.copilot_tools
        ),
    }


def visible_product_copilot_tools() -> frozenset[str]:
    return frozenset(
        tool
        for capability in PRODUCT_CAPABILITIES
        if capability.visibility == "first_class_ui" and capability.maturity not in {"planned", "unsupported"}
        for tool in _capability_copilot_tools(capability)
    )


def product_copilot_tool_operation_bindings(
    *, visible_only: bool = True,
) -> tuple[ProductCopilotToolOperationBinding, ...]:
    """Return concrete ProductOperation bindings for Product Copilot tools.

    Capability-level `copilot_tools` express broad product ownership. MCP
    dispatch needs the stricter operation-level view so a tool call can be
    audited against route, effects, and future corpus requirements.
    """

    bindings: list[ProductCopilotToolOperationBinding] = []
    for capability in PRODUCT_CAPABILITIES:
        if visible_only and (
            capability.visibility != "first_class_ui"
            or capability.maturity in {"planned", "unsupported"}
        ):
            continue
        for operation in capability.operations:
            route = _operation_route_descriptor(operation)
            for tool_name in operation.copilot_tools:
                bindings.append(
                    ProductCopilotToolOperationBinding(
                        tool_name=tool_name,
                        capability_id=capability.id,
                        operation_id=operation.id,
                        route=route,
                        effects=_operation_effects(operation),
                    )
                )
    return tuple(bindings)


def visible_product_action_types() -> frozenset[str]:
    return frozenset(
        action_type
        for capability in PRODUCT_CAPABILITIES
        if capability.visibility == "first_class_ui" and capability.maturity not in {"planned", "unsupported"}
        for action_type in capability.action_types
    )


def _backend_route_descriptor(route: BackendRouteClaim) -> ProductBackendRoute:
    if isinstance(route, ProductBackendRoute):
        return _route_with_policy(route)
    descriptor = PRODUCT_BACKEND_ROUTE_METADATA.get(route)
    if descriptor is None:
        return _route_with_policy(ProductBackendRoute(route, ()))
    return _route_with_policy(descriptor)


def _route_with_policy(route: ProductBackendRoute) -> ProductBackendRoute:
    """Attach release access-policy metadata without duplicating route truth."""
    policy = policy_for_path(route.path)
    access = route.access or (policy.access.value if policy else None)
    required_role = route.required_role
    if required_role is None and policy is not None:
        required_role = required_role_for_access(policy.access)
    route_class = route.route_class
    if route_class is None:
        route_class = _route_class_for_access(access)
    return replace(
        route,
        access=access,
        required_role=required_role,
        route_class=route_class,
    )


def _route_class_for_access(access: str | None) -> ProductRouteClass:
    if access in {"admin", "manager"}:
        return "admin_surface"
    if access in {"user", "owner_or_admin"}:
        return "product_surface"
    if access == "public":
        return "infrastructure"
    return "unclassified"


def build_product_capability_contract() -> dict[str, object]:
    cqlf_contract = build_cqlf_capability_contract()
    capabilities = [_capability_payload(capability) for capability in PRODUCT_CAPABILITIES]
    payload = {
        "version": PRODUCT_CAPABILITY_CONTRACT_VERSION,
        "scope": "CandyConc product capability contract",
        "cqlf_capability_contract": {
            "version": cqlf_contract["version"],
            "current_level": cqlf_contract["current_level"],
            "fingerprint_sha256": cqlf_contract["fingerprint_sha256"],
            "capabilities": cqlf_contract["capabilities"],
        },
        "capabilities": capabilities,
        "copilot_control_tools": [dict(tool) for tool in COPILOT_CONTROL_TOOLS],
    }
    # The fingerprint covers both languages of every text, so it does not
    # depend on the request language but changes when a translation changes.
    encoded = json.dumps(
        bilingual_form(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return {**payload, "fingerprint_sha256": hashlib.sha256(encoded).hexdigest()}
