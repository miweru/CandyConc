import os
import sys
import types

# Unit-Tests fragen kein laufendes LM Studio ab: Die Modellprüfung der
# Chat-Route ist in der Testkulisse aus, bevor candyconc.config sie
# einfriert. Ihre eigenen Tests schalten sie ein
# (tests/services/test_llm_client_streaming.py). Wer die Variable setzt,
# behält seinen Wert.
os.environ.setdefault("CANDYCONC_LM_STUDIO_REQUIRE_LOADED_MODEL", "0")
from pathlib import Path
import importlib
import importlib.util
import json
from collections import Counter
from copy import deepcopy
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Record CANDYCONC_INDEX_PATH before any test module sets a default at import.
import tests.startup_env  # noqa: E402,F401


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _install_stub_if_missing(name: str, module: types.ModuleType) -> None:
    if name not in sys.modules and not _module_available(name):
        sys.modules[name] = module


def _native_unavailable(*_args, **_kwargs):
    raise RuntimeError("fast_index_native is unavailable in collection-only tests")


def _native_stub_getattr(name: str):
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    return _native_unavailable


fast_index_native_mod = types.ModuleType("candyconc.core.fast_index_native")
# ``inspect.getfile()`` must see a real filename when optional torch/spaCy
# imports inspect the active stack during collection.
fast_index_native_mod.__file__ = __file__


def _empty_u32(*_args, **_kwargs):
    import numpy as np

    return np.array([], dtype=np.uint32)


def _empty_i32(*_args, **_kwargs):
    import numpy as np

    return np.array([], dtype=np.int32)


def _false(*_args, **_kwargs):
    return False


def _zero(*_args, **_kwargs):
    return 0


def _empty_list(*_args, **_kwargs):
    return []


for _name in (
    "bitset_positions_limit",
    "decode_roar_positions",
    "doc_search_scores",
    "docset_mask_from_ids",
    "kwic_compact_buffer_rows",
    "kwic_rows_svb",
    "kwic_rows_svb_compact_buffers",
    "lexicon_match_contains",
    "lexicon_match_contains_ids",
    "lexicon_match_prefix",
    "lexicon_match_prefix_ids",
    "lexicon_match_regex",
    "lexicon_match_regex_ids",
    "lexicon_match_suffix",
    "lexicon_match_suffix_ids",
    "roaring_postings_to_bitset",
    "strings_for_ids",
    "union_roar_positions",
    "union_roar_positions_limited",
    "union_sorted",
):
    setattr(fast_index_native_mod, _name, _empty_u32)
for _name in ("decode_svb_block", "dependency_heads", "intersect_shifted", "word_sketch_counts"):
    setattr(fast_index_native_mod, _name, _empty_i32)
fast_index_native_mod.make_svb_range_decoder = lambda *_args, **_kwargs: _empty_u32
fast_index_native_mod.roar_advance_to = _zero
fast_index_native_mod.roar_contains = _false
fast_index_native_mod.__getattr__ = _native_stub_getattr
if not _module_available("candyconc.core._fast_index"):
    sys.modules["candyconc.core.fast_index_native"] = fast_index_native_mod

fast_count_mod = types.ModuleType("candyconc.core._fast_count")
for _name in (
    "count_segments_svb",
    "count_segments_svb_dense",
    "count_segments_svb_pos",
    "count_ngrams_svb",
    "keyness_scores",
    "coverage_sweep_arrays_cy",
    "match_arrays_from_positions",
    "levenshtein_tokens_fast",
    "co_kwic_offset_map",
    "intersect_sorted_limit",
    "union_sorted_limit",
    "count_block_top_svb",
    "count_segments_svb_dual",
    "build_dual_basis_arrays",
    "count_segments_svb_dual_dense",
    "gather_u64_to_f64",
    "subtract_and_compact_dual_counts_u64",
    "filter_sorted_positions_by_docset_mask_u32",
    "filter_sorted_positions_and_values_i64_by_docset_mask_u32",
    "unique_doc_ids_from_sorted_positions_u32",
    "map_positions_to_doc_ids_i64",
    "map_positions_to_doc_ids_i32",
    "position_to_doc_id_i64",
):
    setattr(fast_count_mod, _name, _empty_u32)
_install_stub_if_missing("candyconc.core._fast_count", fast_count_mod)

polars_mod = types.ModuleType("polars")
polars_mod.DataFrame = lambda *args, **kwargs: None
polars_mod.scan_parquet = lambda *args, **kwargs: None
polars_mod.read_parquet = lambda *args, **kwargs: None
_install_stub_if_missing("polars", polars_mod)

yaml_mod = types.ModuleType("yaml")
yaml_mod.safe_load = lambda *_args, **_kwargs: {}
yaml_mod.safe_dump = lambda *_args, **_kwargs: ""
_install_stub_if_missing("yaml", yaml_mod)

remote_embeddings_mod = types.ModuleType("candyconc.services.remote_embeddings")
remote_embeddings_mod.embed_remote = lambda *args, **kwargs: []
sys.modules.setdefault("candyconc.services.remote_embeddings", remote_embeddings_mod)

spacy_mod = types.ModuleType("spacy")
spacy_mod.load = lambda *_args, **_kwargs: None
spacy_cli_mod = types.ModuleType("spacy.cli")
spacy_cli_mod.download = lambda *_args, **_kwargs: None
spacy_util_mod = types.ModuleType("spacy.util")
spacy_util_mod.is_package = lambda *_args, **_kwargs: False
spacy_language_mod = types.ModuleType("spacy.language")
spacy_language_mod.Language = type("Language", (), {})
spacy_mod.cli = spacy_cli_mod
spacy_mod.util = spacy_util_mod
spacy_mod.language = spacy_language_mod
if "spacy" not in sys.modules and not _module_available("spacy"):
    sys.modules["spacy"] = spacy_mod
    sys.modules["spacy.cli"] = spacy_cli_mod
    sys.modules["spacy.util"] = spacy_util_mod
    sys.modules["spacy.language"] = spacy_language_mod


def pytest_configure():
    return None


def _drop_missing_index_env() -> None:
    raw = os.environ.get("CANDYCONC_INDEX_PATH")
    if raw and not Path(raw).expanduser().exists():
        os.environ.pop("CANDYCONC_INDEX_PATH", None)


def _clone_auth_users(auth_mod):
    return _clone_auth_user_mapping(getattr(auth_mod, "_USERS", {}), auth_mod.User)


def _clone_auth_user_mapping(users, user_cls):
    return {
        name: user_cls(user.username, user.password, user.role)
        for name, user in users.items()
    }


@pytest.fixture(autouse=True)
def _isolate_backend_runtime_state():
    """Keep full-suite order from leaking runtime state between tests."""
    _drop_missing_index_env()
    try:
        import candyconc.config as cc_config
        from candyconc.services.backend import auth
    except Exception:
        yield
        _drop_missing_index_env()
        return

    saved_config = deepcopy(getattr(cc_config, "APP_CONFIG", None).__dict__)
    saved_rbac = auth.RBAC_ENABLED
    saved_users = _clone_auth_users(auth)
    saved_tokens = dict(getattr(auth, "_tokens", {}))
    saved_expiry = dict(getattr(auth, "_token_expiry", {}))
    saved_default_admin = getattr(auth, "DEFAULT_ADMIN_TOKEN", None)

    if auth.is_local_dev_unsafe_mode() and auth.using_default_user_file():
        for name, user in auth._load_users(auth.user_file).items():
            auth._USERS.setdefault(name, user)

    try:
        yield
    finally:
        _drop_missing_index_env()
        if saved_config:
            for key, value in saved_config.items():
                setattr(cc_config.APP_CONFIG, key, value)
        auth.RBAC_ENABLED = saved_rbac
        auth._USERS.clear()
        auth._USERS.update(_clone_auth_user_mapping(saved_users, auth.User))
        auth._tokens.clear()
        auth._tokens.update(saved_tokens)
        auth._token_expiry.clear()
        auth._token_expiry.update(saved_expiry)
        auth.DEFAULT_ADMIN_TOKEN = saved_default_admin

# Minimal candyconc_copilot stub for plugin tests

copilot_pkg = types.ModuleType("candyconc_copilot")
copilot_pkg.__path__ = []
sys.modules["candyconc_copilot.prompt_cleaner"] = types.SimpleNamespace(clean_prompt=lambda x: x)

def semantic_search(term: str, top_n: int = 5, ctx: int = 5):
    return [{"left": "", "kw": term, "right": ""}]

def embedding_search(term: str, embeddings: dict[str, list[float]], top_n: int = 3, ctx: int = 5):
    return [{"left": "", "kw": term, "right": ""}]

def validate(query: str) -> dict:
    # Mirrors the real candyconc.candyconc_copilot.validate
    # (src/candyconc/candyconc_copilot/__init__.py:116): suggestions are
    # dicts with text/hint, spans mark the offending range. The previous
    # always-empty stub made server._lightweight_cql_analysis return None,
    # so /query/analyse fell through to the corpus-backed path and answered
    # 503 "corpus missing" in tests/backend/test_query_analyse_api.py.
    errors: list = []
    suggestions: list = []
    spans: list = []
    if '[pos=""]' in query:
        errors.append("Empty POS tag")
        start = query.find('[pos=""]')
        spans.append((start, start + len('[pos=""]')))
        suggestions.append(
            {
                "text": query.replace('[pos=""]', '[pos="NN"]'),
                "hint": "Specify part-of-speech",
            }
        )
    if "“" in query or "”" in query or "'" in query:
        errors.append("Wrong quotes")
        idx = next((i for i, ch in enumerate(query) if ch in "“”'"), 0)
        spans.append((idx, idx + 1))
        clean = query.replace("“", '"').replace("”", '"').replace("'", '"')
        suggestions.append({"text": clean, "hint": "Use straight double quotes"})
    if query.count("[") != query.count("]"):
        errors.append("Unbalanced brackets")
        spans.append((0, len(query)))
        if query.count("[") > query.count("]"):
            diff = query.count("[") - query.count("]")
            suggestions.append(
                {"text": query + "]" * diff, "hint": "Add closing bracket"}
            )
        else:
            diff = query.count("]") - query.count("[")
            corrected = query
            for _ in range(diff):
                corrected = corrected.replace("]", "", 1)
            suggestions.append({"text": corrected, "hint": "Remove extra bracket"})
    return {"errors": errors, "suggestions": suggestions, "spans": spans}

def analyse(query: str) -> dict:
    errors = []
    suggestions = []
    hints = []
    spans = []
    if "[pos=\"\"]" in query:
        errors.append("Empty POS tag")
        suggestions.append(query.replace('[pos=""]', '[pos="NN"]'))
        hints.append("Specify part-of-speech")
        start = query.find("[pos")
        spans.append((start, start + len('[pos=""]')))
    if "\u201c" in query or "\u201d" in query or "'" in query:
        errors.append("Wrong quotes")
        clean = query.replace("\u201c", '"').replace("\u201d", '"').replace("'", '"')
        suggestions.append(clean)
        hints.append("Use straight double quotes")
        idx = query.find("\u201c")
        if idx == -1:
            idx = query.find("\u201d")
        if idx == -1:
            idx = query.find("'")
        if idx != -1:
            spans.append((idx, idx + 1))
    if query.count("[") != query.count("]"):
        errors.append("Unbalanced brackets")
        if query.count("[") > query.count("]"):
            suggestions.append(query + "]" * (query.count("[") - query.count("]")))
            hints.append("Add closing bracket")
            spans.append((0, len(query)))
        else:
            diff = query.count("]") - query.count("[")
            corrected = query
            for _ in range(diff):
                corrected = corrected.replace("]", "", 1)
            suggestions.append(corrected)
            hints.append("Remove extra bracket")
            spans.append((0, len(query)))
    return {"errors": errors, "suggestions": suggestions, "hints": hints, "spans": spans}

def analyse_llm(query: str) -> dict:
    resp = _lm_chat([{"role": "user", "content": query}])
    try:
        data = json.loads(resp.get("content", "{}"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("errors", [])
    data.setdefault("suggestions", [])
    return data

def _heuristic_chat(messages):
    return {"role": "assistant", "content": "ok"}

_lm_chat = _heuristic_chat

copilot_pkg.semantic_search = semantic_search
copilot_pkg.validate = validate
copilot_pkg.analyse = analyse
copilot_pkg.analyse_llm = analyse_llm
copilot_pkg.embedding_search = embedding_search
copilot_pkg._heuristic_chat = _heuristic_chat
copilot_pkg._LM_ENDPOINT = None
copilot_pkg.__path__ = [
    str(Path(__file__).resolve().parent.parent / "src" / "candyconc" / "candyconc_copilot")
]
copilot_pkg.__all__ = [
    "semantic_search",
    "validate",
    "analyse",
    "analyse_llm",
    "embedding_search",
    "run_cqlf_query",
    "collocate_stats",
    "word_sketch",
    "dispersion_offsets",
    "keyness",
    "frequency_list",
    "scientific_agent",
]

# Minimal LLM chat shim used by the generate helper below.  During unit tests
# this function is patched to verify that the caller interacts with the LLM.
def _lm_chat(messages):
    return _heuristic_chat(messages)

copilot_pkg._lm_chat = _lm_chat

def _heuristic_generate(prompt: str) -> str:
    words = prompt.lower().split()
    if len(words) == 3 and words[1] == "before":
        pos = {"verbs": "VB", "nouns": "NN"}.get(words[0], "NN")
        return f'pos="{pos}" "{words[2]}"'
    if len(words) == 3 and words[1] == "after":
        pos = {"adjectives": "JJ"}.get(words[0], "NN")
        return f'"{words[2]}" pos="{pos}"'
    return prompt

def generate(prompt: str) -> str:
    copilot_pkg._lm_chat([{"role": "user", "content": prompt}])
    cand = _heuristic_generate(prompt)
    if not validate(cand)["errors"]:
        return cand
    raise RuntimeError("Invalid response from LLM")

copilot_pkg.generate = generate
copilot_pkg._lm_chat = _lm_chat

TOKENS = "the quick brown fox jumps over the lazy dog the and cat sleep well".split()

def run_cqlf_query(query: str, ctx: int = 5):
    return {"status": "success", "rows": [{"left": "", "kw": query, "right": ""}]}

def collocate_stats(term: str, window: int = 5, *, use_gpu: bool | None = None):
    return pd.DataFrame([{"word": "the", "chi2_cell": 1.0}])

def word_sketch(term: str):
    df = pd.DataFrame([{"word": "the", "chi2_cell": 1.0, "t": 1.0, "ll": 1.0, "rank": 1}])
    return {"dep": df}

def dispersion_offsets(term: str):
    return [i for i, tok in enumerate(TOKENS) if tok == term]

def keyness(target, reference, *, pos_map=None, pos=None):
    return pd.DataFrame([{"word": "the", "chi2_cell": 1.0, "ll": 1.0}])

def frequency_list(stopwords=None, *, corpus=None, use_gpu=None):
    tokens = [t for t in TOKENS if not stopwords or t not in stopwords]
    freq = Counter(tokens)
    df = pd.DataFrame({"word": list(freq.keys()), "f": list(freq.values())})
    df = df.sort_values("f", ascending=False).reset_index(drop=True)
    df.index += 1
    return df

copilot_pkg.run_cqlf_query = run_cqlf_query
copilot_pkg.collocate_stats = collocate_stats
copilot_pkg.word_sketch = word_sketch
copilot_pkg.dispersion_offsets = dispersion_offsets
copilot_pkg.keyness = keyness
copilot_pkg.frequency_list = frequency_list
def scientific_agent(question: str) -> str:
    return "analysis"
copilot_pkg.scientific_agent = scientific_agent

orch_mod = types.ModuleType("candyconc_copilot.orchestrator")

class ReActOrchestrator:
    def __init__(self, *a, **k) -> None:
        self.messages = []

    def run(self, *a, **k) -> str:
        return ""

class State:
    WAITING_LLM = "waiting"
    EXECUTING_TOOL = "executing"
    FINISHED = "finished"

orch_mod.ReActOrchestrator = ReActOrchestrator
orch_mod.State = State

dispatcher_mod = types.ModuleType("candyconc_copilot.dispatcher")

def dispatch(name: str, **kw):
    fn = dispatcher_mod._TOOL_MAP.get(name)
    if fn is None:
        return {"status": "error", "message": f"Unknown tool: {name}"}
    try:
        return fn(**kw)
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

dispatcher_mod._TOOL_MAP = {
    "run_cqlf_query": lambda **kw: run_cqlf_query(kw.get("query", ""), kw.get("ctx", 5)),
    "collocate_stats": lambda **kw: {"status": "success", "rows": collocate_stats(kw.get("term", "")).to_dict("records")},
    "frequency_list": lambda **kw: {"status": "success", "rows": frequency_list().to_dict("records")},
}
dispatcher_mod.dispatch = dispatch

session_mod = types.ModuleType("candyconc_copilot.session_manager")

class SessionManager:
    def __init__(self, *a, **k) -> None:
        self.history = []
        self.summaries = []
        self.memory = memory_store_mod.MemoryStore()
        self._search_results = []

    def summarise(self, project=None) -> None:
        note = "summary"
        self.summaries.append(note)
        self.memory.add(note)

    def append(self, msg, project=None) -> None:
        self.history.append(msg)

    def get_history(self):
        retrieved = [{"role": "system", "content": n} for n in self._search_results]
        summaries = [{"role": "system", "content": s} for s in self.summaries]
        return retrieved + summaries + list(self.history)

    def search(self, query: str, k: int = 3):
        res = self.memory.search(query, k)
        self._search_results = res
        return res

session_mod.SessionManager = SessionManager

obs_mod = types.ModuleType("candyconc_copilot.observability")

class Observability:
    def __init__(self, *a, **k) -> None:
        self.metrics = {}

    def record(self, *a, **k) -> None:
        return None

    def export_metrics(self):
        return self.metrics

obs_mod.Observability = Observability

policy_mod = types.ModuleType("candyconc_copilot.policy_engine")

class PolicyEngine:
    pass

policy_mod.PolicyEngine = PolicyEngine

tw_mod = types.ModuleType("candyconc_copilot.tool_wrappers")


# Mirror the real module's unknown-corpus/docset error class (COPILOT-3) so the
# MCP boundary's 404 mapping resolves the same type under the stub as in prod.
class UnknownResourceError(RuntimeError):
    """Stub mirror of tool_wrappers.UnknownResourceError (bad-request resource)."""


# Mirror the real module's invalid-arguments error class (COPILOT-KEYNESS-
# INCOMPLETE-500) so the MCP boundary's 400 mapping resolves the same type under
# the stub as in prod.
class ToolInputError(ValueError):
    """Stub mirror of tool_wrappers.ToolInputError (bad-request arguments)."""


tw_mod.UnknownResourceError = UnknownResourceError
tw_mod.ToolInputError = ToolInputError
# Stub tool schemas with proper object type parameters
tw_mod.RUN_CQLF_TOOL = {"type": "function", "function": {"name": "run_cqlf_query", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}
tw_mod.COLLOCATE_TOOL = {"type": "function", "function": {"name": "collocate_stats", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}
tw_mod.WORD_SKETCH_TOOL = {"type": "function", "function": {"name": "word_sketch", "parameters": {"type": "object", "properties": {"word": {"type": "string"}}}}}
tw_mod.FREQUENCY_TOOL = {"type": "function", "function": {"name": "frequency_list", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}
tw_mod.DISPERSION_TOOL = {"type": "function", "function": {"name": "dispersion_offsets", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "partitions": {"type": "integer"}}}}}
tw_mod.KEYNESS_TOOL = {"type": "function", "function": {"name": "keyness", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}
tw_mod.SEMANTIC_SEARCH_TOOL = {"type": "function", "function": {"name": "semantic_search", "parameters": {"type": "object", "properties": {"term": {"type": "string"}}}}}
tw_mod.TRANSFORMER_SEARCH_TOOL = {"type": "function", "function": {"name": "transformer_search", "parameters": {"type": "object", "properties": {"term": {"type": "string"}}}}}
tw_mod.DOCUMENT_SEARCH_TOOL = {"type": "function", "function": {"name": "document_search", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}
tw_mod.DOCUMENTATION_SEARCH_TOOL = {"type": "function", "function": {"name": "documentation_search", "parameters": {"type": "object", "properties": {"term": {"type": "string"}}}}}
tw_mod.ALL_TOOLS = [
    tw_mod.RUN_CQLF_TOOL,
    tw_mod.COLLOCATE_TOOL,
    tw_mod.WORD_SKETCH_TOOL,
    tw_mod.FREQUENCY_TOOL,
    tw_mod.DISPERSION_TOOL,
    tw_mod.KEYNESS_TOOL,
    tw_mod.SEMANTIC_SEARCH_TOOL,
    tw_mod.TRANSFORMER_SEARCH_TOOL,
    tw_mod.DOCUMENT_SEARCH_TOOL,
    tw_mod.DOCUMENTATION_SEARCH_TOOL,
]

def run_cqlf_query_tool(query: str, ctx: int = 5):
    return copilot_pkg.run_cqlf_query(query, ctx)

def collocate_stats_tool(term: str, window: int = 5):
    df = copilot_pkg.collocate_stats(term, window)
    return {"status": "success", "rows": df.to_dict("records")}

def compare_collocates_tool(term: str, *args, **kwargs):
    return {
        "status": "success",
        "rows": [{"word": term, "freq_human": 1.0, "freq_ai": 1.0, "log_ratio": 0.0}],
        "diagnostics": {"model_values": [], "text_type_values": [], "has_human_axis": False, "has_ai_axis": False},
    }

def frequency_list_tool(stopwords=None):
    df = copilot_pkg.frequency_list(stopwords=stopwords)
    return {"status": "success", "rows": df.to_dict("records")}

def dispersion_offsets_tool(term: str, partitions: int = 10):
    offsets = copilot_pkg.dispersion_offsets(term)
    counts = [0] * max(1, int(partitions))
    for offset in offsets:
        counts[int(offset) % len(counts)] += 1
    return {
        "status": "success",
        "term": term,
        "offsets": offsets,
        "partitions": counts,
        "dp": 0.0,
        "total_hits": len(offsets),
        "nonzero_partitions": sum(1 for count in counts if count),
        "coverage_ratio": 0.0,
        "peak_partition": 0,
        "peak_share": 0.0,
        "profile": "fairly_even",
    }

def keyness_tool(tgt, ref):
    df = copilot_pkg.keyness(tgt, ref)
    return {"status": "success", "rows": df.to_dict("records")}

def document_search_tool(query: str, top_n: int = 5, snippet: int = 5):
    rows = [{"doc": 1, "snippet": query}]
    return {"status": "success", "rows": rows}

def metadata_values_tool(field: str | None = None, *args, **kwargs):
    return {"status": "success", "field": field, "values": []}

def documentation_search_tool(term: str, top_n: int = 5, snippet: int = 30):
    rows = [{"file": "docs/example.md", "snippet": term}]
    return {"status": "success", "rows": rows}

def semantic_search_tool(term: str, top_n: int = 3):
    return {"status": "success", "rows": copilot_pkg.semantic_search(term, top_n)}

def transformer_search_tool(term: str, top_n: int = 3, context_window: int = 0):
    return semantic_search_tool(term, top_n)

def semantic_cluster_words_tool(*args, **kwargs):
    return {"status": "success", "clusters": []}


tw_mod.run_cqlf_query_tool = run_cqlf_query_tool
tw_mod.collocate_stats_tool = collocate_stats_tool
tw_mod.compare_collocates_tool = compare_collocates_tool
tw_mod.frequency_list_tool = frequency_list_tool
tw_mod.dispersion_offsets_tool = dispersion_offsets_tool
tw_mod.keyness_tool = keyness_tool
tw_mod.document_search_tool = document_search_tool
tw_mod.metadata_values_tool = metadata_values_tool
tw_mod.documentation_search_tool = documentation_search_tool
tw_mod.semantic_search_tool = semantic_search_tool
tw_mod.transformer_search_tool = transformer_search_tool
tw_mod.semantic_cluster_words_tool = semantic_cluster_words_tool
tw_mod._run_cqlf_query = run_cqlf_query
tw_mod._collocate_stats = collocate_stats
tw_mod._compare_collocates = lambda *a, **k: pd.DataFrame([{"word": "the"}])
tw_mod._frequency_list = frequency_list
tw_mod._resolve_docset_doc_ids = lambda *a, **k: (None, None)
tw_mod._get_doc_index = lambda *a, **k: None
tw_mod._get_index = lambda *a, **k: None
tw_mod._document_search = document_search_tool
tw_mod._semantic_search = semantic_search_tool

# Import registry after stub modules are in place

vectorizer_mod = types.ModuleType("candyconc_copilot.vectorizer")

class BERT:
    def __init__(self, *a, **k) -> None:
        self.dim = 16

    def vectorize(self, s: str):
        return [0.0]

    def batch_vectorize(self, s, batch_size=-1):
        return [[0.0] for _ in s]

def _hash_vector(text: str, dim: int = 16):
    import hashlib
    import numpy as np
    digest = hashlib.sha1(text.encode("utf-8")).digest()
    arr = np.frombuffer(digest, dtype=np.uint8)[:dim]
    return arr.astype(np.float32) / 255.0

vectorizer_mod.BERT = BERT
vectorizer_mod.JinaBERTv3 = BERT
vectorizer_mod.FineTunedJinaBERTv3 = BERT
vectorizer_mod._hash_vector = _hash_vector

memory_store_mod = types.ModuleType("candyconc_copilot.memory_store")

class MemoryStore:
    def __init__(self, *a, **k) -> None:
        self.notes = []

    def add(self, note: str, embedding=None) -> None:
        self.notes.append(note)

    def search(self, query: str, k: int = 3):
        return self.notes[:k]

memory_store_mod.MemoryStore = MemoryStore

sys.modules["candyconc_copilot"] = copilot_pkg
sys.modules["candyconc_copilot.orchestrator"] = orch_mod
sys.modules["candyconc_copilot.dispatcher"] = dispatcher_mod
sys.modules["candyconc_copilot.session_manager"] = session_mod
sys.modules["candyconc_copilot.observability"] = obs_mod
sys.modules["candyconc_copilot.policy_engine"] = policy_mod
sys.modules["candyconc_copilot.tool_wrappers"] = tw_mod
sys.modules["candyconc_copilot.vectorizer"] = vectorizer_mod
sys.modules["candyconc_copilot.memory_store"] = memory_store_mod
sys.modules["candyconc.candyconc_copilot"] = copilot_pkg
sys.modules["candyconc.candyconc_copilot.orchestrator"] = orch_mod
sys.modules["candyconc.candyconc_copilot.dispatcher"] = dispatcher_mod
sys.modules["candyconc.candyconc_copilot.session_manager"] = session_mod
sys.modules["candyconc.candyconc_copilot.observability"] = obs_mod
sys.modules["candyconc.candyconc_copilot.policy_engine"] = policy_mod
sys.modules["candyconc.candyconc_copilot.tool_wrappers"] = tw_mod
sys.modules["candyconc.candyconc_copilot.vectorizer"] = vectorizer_mod
sys.modules["candyconc.candyconc_copilot.memory_store"] = memory_store_mod

# Test-local registry shim.  Importing the production registry pulls in backend
# semantic availability and the native fast-index extension during collection.
tooling_registry_mod = types.ModuleType("candyconc.tooling.registry")
REGISTRY = []


def llm_tool(tool, response_schema=None, *, read_only=True, concurrency_safe=None):
    params = tool.get("function", {}).get("parameters")
    if not isinstance(params, dict) or params.get("type") != "object":
        raise ValueError("Tool schema must define object parameters")

    def wrap(fn):
        entry = {
            **tool,
            "function": {"name": fn.__name__, **tool.get("function", {})},
            "callable": fn,
            "read_only": read_only,
            "concurrency_safe": read_only if concurrency_safe is None else concurrency_safe,
        }
        if response_schema is not None:
            entry["response_schema"] = response_schema
        REGISTRY.append(entry)
        return fn

    return wrap


def _enabled_unique_tools():
    seen = set()
    unique_reversed = []
    for tool in reversed(REGISTRY):
        name = str(tool.get("function", {}).get("name", "") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        unique_reversed.append(tool)
    return list(reversed(unique_reversed))


def get_tools():
    return [
        {
            "type": tool.get("type", "function"),
            "function": tool.get("function", {}),
        }
        for tool in _enabled_unique_tools()
    ]


def get_schema_map():
    return {
        tool["function"]["name"]: tool["function"].get("parameters", {})
        for tool in get_tools()
    }


def get_tool_runtime_info():
    return {
        str(tool["function"]["name"]): {
            "read_only": bool(tool.get("read_only", True)),
            "concurrency_safe": bool(tool.get("concurrency_safe", True)),
        }
        for tool in _enabled_unique_tools()
        if tool.get("function", {}).get("name")
    }


tooling_registry_mod.REGISTRY = REGISTRY
tooling_registry_mod.llm_tool = llm_tool
tooling_registry_mod.get_tools = get_tools
tooling_registry_mod.get_schema_map = get_schema_map
tooling_registry_mod.get_tool_runtime_info = get_tool_runtime_info
sys.modules["candyconc.tooling.registry"] = tooling_registry_mod

tool_selection_path = Path(__file__).resolve().parent.parent / "src" / "candyconc" / "tooling" / "tool_selection.py"
tool_selection_spec = importlib.util.spec_from_file_location(
    "candyconc.tooling.tool_selection",
    tool_selection_path,
)
tool_selection_mod = importlib.util.module_from_spec(tool_selection_spec)
assert tool_selection_spec and tool_selection_spec.loader
tool_selection_spec.loader.exec_module(tool_selection_mod)  # type: ignore[arg-type]
sys.modules["candyconc.tooling.tool_selection"] = tool_selection_mod

tooling_mod = types.ModuleType("candyconc.tooling")
tooling_mod.__path__ = [str(Path(__file__).resolve().parent.parent / "src" / "candyconc" / "tooling")]
tooling_mod.REGISTRY = REGISTRY
tooling_mod.llm_tool = llm_tool
tooling_mod.get_tools = get_tools
tooling_mod.get_schema_map = get_schema_map
tooling_mod.get_tool_runtime_info = get_tool_runtime_info
tooling_mod.product_tool_bindings_by_name = tool_selection_mod.product_tool_bindings_by_name
tooling_mod.bindings_allow_default_release_dispatch = tool_selection_mod.bindings_allow_default_release_dispatch
tooling_mod.product_binding_metadata = tool_selection_mod.product_binding_metadata
tooling_mod.is_tool_dispatchable_for_principal = tool_selection_mod.is_tool_dispatchable_for_principal
tooling_mod.filter_dispatchable_tools_for_principal = tool_selection_mod.filter_dispatchable_tools_for_principal
tooling_mod.response_contract_for_prompt = tool_selection_mod.response_contract_for_prompt
tooling_mod.select_tools_for_prompt = tool_selection_mod.select_tools_for_prompt
sys.modules["candyconc.tooling"] = tooling_mod


def _register_stub_tool(fn, tool_schema):
    """Register a stub tool function with its schema in the REGISTRY."""
    entry = {
        **tool_schema,
        "function": {
            "name": fn.__name__,
            **tool_schema.get("function", {}),
            "parameters": tool_schema.get("function", {}).get("parameters", {"type": "object", "properties": {}}),
        },
        "callable": fn,
    }
    # Ensure parameters has type: object for schema validation
    if entry["function"]["parameters"].get("type") != "object":
        entry["function"]["parameters"] = {"type": "object", "properties": entry["function"]["parameters"]}
    REGISTRY.append(entry)


# register stub tools with registry
_register_stub_tool(run_cqlf_query_tool, tw_mod.RUN_CQLF_TOOL)
_register_stub_tool(collocate_stats_tool, tw_mod.COLLOCATE_TOOL)
_register_stub_tool(frequency_list_tool, tw_mod.FREQUENCY_TOOL)
_register_stub_tool(dispersion_offsets_tool, tw_mod.DISPERSION_TOOL)
_register_stub_tool(keyness_tool, tw_mod.KEYNESS_TOOL)
_register_stub_tool(document_search_tool, tw_mod.DOCUMENT_SEARCH_TOOL)
_register_stub_tool(documentation_search_tool, tw_mod.DOCUMENTATION_SEARCH_TOOL)
_register_stub_tool(semantic_search_tool, tw_mod.SEMANTIC_SEARCH_TOOL)
_register_stub_tool(transformer_search_tool, tw_mod.TRANSFORMER_SEARCH_TOOL)

# Canonical snapshot of the stub tool surface.  A couple of tests import the
# REAL ``candyconc_copilot.tool_wrappers`` (tests/ai/test_documentation_tool.py,
# tests/ai/test_corpus_mismatch_guard.py) to exercise its real behaviour.  That
# import runs the module-level ``@llm_tool(...)`` decorators, which APPEND the
# real tool entries onto the shared ``REGISTRY`` list above (9 stub entries grow
# to ~28).  ``get_tool_runtime_info()`` / ``get_tools()`` then return the real
# surface for every later test in the same process.  ReActOrchestrator caches
# ``get_tool_runtime_info()`` at construction, so the contract/forced-tool path
# in tests/ai/test_orchestrator_grounding_runtime.py sees the wrong tool surface
# and the run finalises down the wrong branch (forced_exposures 0 != 2).  The
# heal hook below restores this snapshot in place before every test/collection.
_BASELINE_REGISTRY = [dict(entry) for entry in REGISTRY]

# Provide actual pii_filter implementation
pii_path = Path(__file__).resolve().parent.parent / "src" / "candyconc" / "services" / "backend" / "pii_filter.py"
pii_spec = importlib.util.spec_from_file_location("candyconc.services.backend.pii_filter", pii_path)
pii_mod = importlib.util.module_from_spec(pii_spec)
assert pii_spec and pii_spec.loader
pii_spec.loader.exec_module(pii_mod)  # type: ignore[arg-type]
sys.modules["candyconc.services.backend.pii_filter"] = pii_mod

# Pre-load the real copilot_event_bus module under its production name.  The module is
# self-contained (stdlib only), so this does NOT pull in the
# heavy backend server.  Reason: tests/ai/test_streaming_runtime_regressions.py
# sets a SimpleNamespace ``copilot_event_bus`` ATTRIBUTE on the backend package at
# import (collection) time when the attribute is missing; that namespace then
# shadows the real submodule for every later ``from candyconc.services.backend
# import copilot_event_bus`` (tests/backend/test_copilot_stream_results.py,
# test_chat_stream_termination.py).  With the real module cached here, the
# heal hook below can re-attach it whenever a stub namespace shadows it.
copilot_event_bus_path = (
    Path(__file__).resolve().parent.parent
    / "src" / "candyconc" / "services" / "backend" / "copilot_event_bus.py"
)
if "candyconc.services.backend.copilot_event_bus" not in sys.modules:
    copilot_event_bus_spec = importlib.util.spec_from_file_location(
        "candyconc.services.backend.copilot_event_bus", copilot_event_bus_path
    )
    copilot_event_bus_mod = importlib.util.module_from_spec(copilot_event_bus_spec)
    assert copilot_event_bus_spec and copilot_event_bus_spec.loader
    copilot_event_bus_spec.loader.exec_module(copilot_event_bus_mod)  # type: ignore[arg-type]
    sys.modules["candyconc.services.backend.copilot_event_bus"] = copilot_event_bus_mod


# ---------------------------------------------------------------------------
# Package-__path__ self-healing.
#
# pytest imports EVERY test module during collection before running any test.
# A few test modules install module-level stubs via
# ``sys.modules.setdefault("candyconc.services", types.ModuleType(...))`` and
# then unconditionally assign ``__path__ = []`` (e.g.
# tests/ai/test_streaming_runtime_regressions.py).  When the real package is
# already cached, ``setdefault`` returns the REAL package object and the
# assignment empties the real package's search path — every later submodule
# import ("candyconc.services.controller", "candyconc.services.hpc_monitor",
# "candyconc.tooling.registry", ...) then fails with ModuleNotFoundError,
# producing collection errors and run-time failures in unrelated directories.
#
# The heal below restores the search path of any candyconc package whose
# ``__path__`` has been emptied: real packages get ``dirname(__file__)``
# back, and the conftest tooling shim gets its configured source path back.
# It runs before each collection step and before each test, so damage from a
# module-level mutation is repaired before the next module imports or the
# next test runs.  Cached stub leaf modules are untouched (an emptied
# ``__path__`` only ever breaks imports — nothing relies on it staying
# empty for modules already in ``sys.modules``).
# ---------------------------------------------------------------------------

_TOOLING_SHIM_PATH = str(
    Path(__file__).resolve().parent.parent / "src" / "candyconc" / "tooling"
)


def _heal_candyconc_package_paths() -> None:
    for _name, _mod in list(sys.modules.items()):
        if _mod is None or not _name.startswith("candyconc"):
            continue
        _path = getattr(_mod, "__path__", None)
        if _path is None:
            continue
        try:
            _path_entries = list(_path)
        except TypeError:
            continue
        if len(_path_entries) > 0:
            continue
        _file = getattr(_mod, "__file__", None)
        if _file and os.path.basename(_file) == "__init__.py":
            _mod.__path__ = [os.path.dirname(_file)]
        elif _mod is tooling_mod:
            _mod.__path__ = [_TOOLING_SHIM_PATH]
    # Re-attach the real copilot_event_bus submodule when a test module shadowed it
    # with a plain namespace attribute on the backend package (see the
    # pre-load above for the why).
    _backend_pkg = sys.modules.get("candyconc.services.backend")
    _real_copilot_event_bus = sys.modules.get("candyconc.services.backend.copilot_event_bus")
    if (
        _backend_pkg is not None
        and _real_copilot_event_bus is not None
        and hasattr(_backend_pkg, "copilot_event_bus")
        and not isinstance(_backend_pkg.copilot_event_bus, types.ModuleType)
    ):
        _backend_pkg.copilot_event_bus = _real_copilot_event_bus
    # Re-pin the tooling shim surface.  Some module-level loaders fetch the
    # shim via sys.modules.setdefault(...) and then assign replacement
    # lambdas onto the returned object (tests/ai/test_orchestrator_async.py:
    # ``tooling_pkg.get_tools = lambda: []`` /
    # ``registry_mod.get_tool_runtime_info = lambda *a, **k: {}``).  A
    # sys.modules snapshot/restore cannot undo ATTRIBUTE mutation on the
    # shared shim object, so the canonical functions are re-asserted here.
    # Restore the canonical stub tool surface.  A test that imported the real
    # ``candyconc_copilot.tool_wrappers`` appended its real ``@llm_tool`` entries
    # onto the shared REGISTRY list; left in place they corrupt
    # get_tool_runtime_info()/get_tools() for every later test (see the
    # _BASELINE_REGISTRY comment above).  Restore in place so the shared list
    # object that get_tools() closes over keeps its identity.
    if len(REGISTRY) != len(_BASELINE_REGISTRY):
        REGISTRY[:] = [dict(entry) for entry in _BASELINE_REGISTRY]
    for _shim in (tooling_registry_mod, tooling_mod):
        if _shim.get_tools is not get_tools:
            _shim.get_tools = get_tools
        if _shim.get_schema_map is not get_schema_map:
            _shim.get_schema_map = get_schema_map
        if _shim.get_tool_runtime_info is not get_tool_runtime_info:
            _shim.get_tool_runtime_info = get_tool_runtime_info
        if _shim.llm_tool is not llm_tool:
            _shim.llm_tool = llm_tool
    # Re-align the canonical backend metrics module.  A module-level loader
    # may exec a FRESH metrics module under the production name
    # (tests/ai/test_token_usage.py) without restoring it; the server module
    # keeps its import-time binding, so the /metrics endpoint and tests that
    # bind ``from candyconc.services.backend import metrics`` afterwards end
    # up incrementing two different counter sets.  The server's binding is
    # canonical — restore the sys.modules entry and package attribute to it.
    _server_mod = sys.modules.get("candyconc.services.backend.server")
    _server_metrics = getattr(_server_mod, "metrics", None)
    if isinstance(_server_metrics, types.ModuleType):
        if sys.modules.get("candyconc.services.backend.metrics") is not _server_metrics:
            sys.modules["candyconc.services.backend.metrics"] = _server_metrics
        if _backend_pkg is not None and getattr(_backend_pkg, "metrics", None) is not _server_metrics:
            _backend_pkg.metrics = _server_metrics


def pytest_collectstart(collector):
    _heal_candyconc_package_paths()


def pytest_runtest_setup(item):
    _heal_candyconc_package_paths()


# ---------------------------------------------------------------------------
# Cross-test active-corpus pollution guard.
#
# Many tests install an active corpus by assigning ``query_runtime._CORPUS_INDEX``
# and/or the server active-corpus mirrors (``_INDEX``/``_INDEX_PATH``/
# ``_CORPUS_INDEX``/``_LANG_INDICES``) and never restore them. In a SINGLE-process
# full-tree run (``pytest tests``) that leaked active corpus bleeds into later
# directories (tests/search, tests/semantic, tests/docs, tests/infra), which pass
# in isolation but fail after a polluting earlier test ran.
#
# This autouse fixture snapshots those globals before each test and restores them
# afterwards. It is deliberately conservative: it only touches modules that are
# ALREADY imported (never forcing the heavy server import), uses guarded
# getattr/setattr, restores the ``_LANG_INDICES`` dict IN PLACE so any holder of
# the dict reference sees the restored mapping, and never asserts — a test that
# legitimately changes the active corpus simply gets its change rolled back.
# ---------------------------------------------------------------------------
_ACTIVE_CORPUS_SCALAR_MIRRORS = ("_INDEX", "_INDEX_PATH", "_CORPUS_INDEX")


@pytest.fixture(autouse=True)
def _restore_active_corpus():
    _SENTINEL = object()

    query_runtime = sys.modules.get("candyconc.core.query_runtime")
    server = sys.modules.get("candyconc.services.backend.server")
    server_was_imported = server is not None
    qr_was_imported = query_runtime is not None

    qr_corpus = (
        getattr(query_runtime, "_CORPUS_INDEX", _SENTINEL)
        if query_runtime is not None
        else _SENTINEL
    )

    server_scalars: dict[str, object] = {}
    lang_indices_snapshot = None
    if server is not None:
        for name in _ACTIVE_CORPUS_SCALAR_MIRRORS:
            server_scalars[name] = getattr(server, name, _SENTINEL)
        lang = getattr(server, "_LANG_INDICES", _SENTINEL)
        if isinstance(lang, dict):
            lang_indices_snapshot = dict(lang)

    try:
        yield
    finally:
        # If a test FIRST-imported these modules during its run, the setup-time
        # snapshot above missed them; re-resolve and reset their active-corpus
        # mirrors to module defaults so a first-importer cannot leak state forward.
        if not qr_was_imported:
            qr_now = sys.modules.get("candyconc.core.query_runtime")
            if qr_now is not None:
                set_fn = getattr(qr_now, "set_corpus", None)
                if callable(set_fn):
                    try:
                        set_fn(None)
                    except Exception:
                        setattr(qr_now, "_CORPUS_INDEX", None)
                else:
                    setattr(qr_now, "_CORPUS_INDEX", None)
        if not server_was_imported:
            server_now = sys.modules.get("candyconc.services.backend.server")
            if server_now is not None:
                reset_fn = getattr(server_now, "reset_default_corpus_runtime_state", None)
                if callable(reset_fn):
                    try:
                        reset_fn()
                    except Exception:
                        pass
                else:
                    for name in _ACTIVE_CORPUS_SCALAR_MIRRORS:
                        if hasattr(server_now, name):
                            setattr(server_now, name, None)
                    lang = getattr(server_now, "_LANG_INDICES", None)
                    if isinstance(lang, dict):
                        lang.clear()

        # query_runtime: prefer the public set_corpus so its own bookkeeping
        # stays consistent; fall back to a direct attribute restore.
        if query_runtime is not None and qr_corpus is not _SENTINEL:
            set_fn = getattr(query_runtime, "set_corpus", None)
            if callable(set_fn):
                try:
                    set_fn(qr_corpus)
                except Exception:
                    setattr(query_runtime, "_CORPUS_INDEX", qr_corpus)
            else:
                setattr(query_runtime, "_CORPUS_INDEX", qr_corpus)

        if server is not None:
            for name, value in server_scalars.items():
                if value is _SENTINEL:
                    continue
                setattr(server, name, value)
            if lang_indices_snapshot is not None:
                lang = getattr(server, "_LANG_INDICES", None)
                if isinstance(lang, dict):
                    lang.clear()
                    lang.update(lang_indices_snapshot)
                else:
                    setattr(server, "_LANG_INDICES", dict(lang_indices_snapshot))
