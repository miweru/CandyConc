"""spaCy pipelines: status, messages and the explicit installation.

CandyConc never downloads a pipeline on its own. ``candy pipeline <name>``
installs one on request, in any environment: with pip when the interpreter has
it, otherwise with uv (uv-created environments have no pip). ``blank:<lang>``
needs no download and tokenizes without linguistic annotation.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from pathlib import Path

from candyconc.i18n import LocalizedText, lt

_BLANK = re.compile(r"blank:([A-Za-z][A-Za-z_-]*)")
_LANG_PREFIX = re.compile(r"([a-z]{2,3})_")
_LANG_CODE = re.compile(r"[a-z]{2,3}")

#: Language of a corpus imported without --language and without --spacy-model.
DEFAULT_LANGUAGE = "de"

#: Trained spaCy pipeline per language (spaCy 3.8 compatibility table). The
#: ``_md`` size ships static word vectors, which the thesaurus and ``sim()``
#: need, and keeps the German default ``de_core_news_md`` unchanged.
DEFAULT_PIPELINES: dict[str, str] = {
    "ca": "ca_core_news_md",
    "da": "da_core_news_md",
    "de": "de_core_news_md",
    "el": "el_core_news_md",
    "en": "en_core_web_md",
    "es": "es_core_news_md",
    "fi": "fi_core_news_md",
    "fr": "fr_core_news_md",
    "hr": "hr_core_news_md",
    "it": "it_core_news_md",
    "ja": "ja_core_news_md",
    "ko": "ko_core_news_md",
    "lt": "lt_core_news_md",
    "mk": "mk_core_news_md",
    "nb": "nb_core_news_md",
    "nl": "nl_core_news_md",
    "pl": "pl_core_news_md",
    "pt": "pt_core_news_md",
    "ro": "ro_core_news_md",
    "ru": "ru_core_news_md",
    "sl": "sl_core_news_md",
    "sv": "sv_core_news_md",
    "uk": "uk_core_news_md",
    "zh": "zh_core_web_md",
}


def normalize_language(code: str) -> str:
    """ISO 639 code in lower case: ``EN``, ``en-US`` and ``en_GB`` give ``en``.

    Raises ``ValueError`` for anything that is not a two or three letter code.
    """
    primary = re.split(r"[-_]", str(code or "").strip().lower(), maxsplit=1)[0]
    if not _LANG_CODE.fullmatch(primary):
        raise ValueError(f"'{code}' is not an ISO 639 language code (for example en, de, fr).")
    return primary


def default_pipeline(language: str) -> str:
    """The pipeline ``--language`` selects: a trained one, else ``blank:<language>``.

    ``blank:<language>`` only tokenizes. Raises ``ValueError`` when spaCy has
    no tokenizer for the language either.
    """
    lang = normalize_language(language)
    if lang in DEFAULT_PIPELINES:
        return DEFAULT_PIPELINES[lang]
    try:
        from spacy.util import get_lang_class

        get_lang_class(lang)
    except Exception as exc:
        raise ValueError(f"spaCy has no pipeline and no tokenizer for the language '{lang}'.") from exc
    return f"blank:{lang}"


def pipeline_language(name: str) -> str | None:
    """Language of a pipeline name without loading it, ``None`` when unknown.

    ``blank:en`` and ``en_core_web_sm`` give ``en``. A pipeline directory
    gives the ``lang`` of its ``meta.json``.
    """
    name = str(name or "").strip()
    blank = _BLANK.fullmatch(name)
    if blank:
        return blank.group(1).lower()
    if "/" in name or "\\" in name:
        meta = Path(name).expanduser() / "meta.json"
        try:
            import json

            lang = json.loads(meta.read_text("utf-8")).get("lang")
        except Exception:
            return None
        return str(lang).lower() if lang else None
    match = _LANG_PREFIX.match(name)
    return match.group(1) if match else None


def resolve_import_pipeline(language: str | None, spacy_model: str | None) -> str:
    """The pipeline of an import from ``--language`` and ``--spacy-model``.

    ``--spacy-model`` wins when it is given. With only ``--language`` the
    language's default pipeline is used, with neither the German default.
    Raises ``ValueError`` when both are given and name different languages.
    """
    model = str(spacy_model or "").strip()
    if not str(language or "").strip():
        return model or DEFAULT_PIPELINES[DEFAULT_LANGUAGE]
    lang = normalize_language(str(language))
    if not model:
        return default_pipeline(lang)
    model_lang = pipeline_language(model)
    if model_lang is not None and model_lang != lang:
        raise ValueError(
            f"--language {lang} does not match --spacy-model {model}, which is a "
            f"pipeline for '{model_lang}'. Give only one of them, or a pipeline for '{lang}'."
        )
    return model


def pipeline_label(requested: str | None, nlp) -> tuple[str, str]:
    """Name and version of a loaded pipeline for the index manifest.

    Uses the package naming of spaCy (``en_core_web_sm``) rather than a local
    path, so the manifest records no directory of the build machine.
    """
    requested = str(requested or "").strip()
    lang = str(getattr(nlp, "lang", "") or "")
    if is_blank(requested):
        return f"blank:{lang or pipeline_language(requested) or 'xx'}", ""
    meta = getattr(nlp, "meta", None)
    meta = meta if isinstance(meta, dict) else {}
    name = str(meta.get("name") or "")
    version = str(meta.get("version") or "")
    if name and name != "pipeline" and lang:
        return f"{lang}_{name}", version
    if requested and "/" not in requested and "\\" not in requested:
        return requested, version
    return "", version


def pipeline_meta(name: str) -> dict | None:
    """``meta.json`` of an installed pipeline package or directory, without loading it.

    None for ``blank:<lang>``, for a pipeline that is not installed and for
    an unreadable file.
    """
    name = str(name or "").strip()
    if not name or is_blank(name):
        return None
    import json

    candidates: list[Path] = []
    if "/" in name or "\\" in name:
        candidates.append(Path(name).expanduser() / "meta.json")
    else:
        try:
            spec = importlib.util.find_spec(name.replace("-", "_"))
        except (ImportError, ValueError):
            spec = None
        for location in list(getattr(spec, "submodule_search_locations", None) or []):
            root = Path(location)
            candidates.append(root / "meta.json")
            candidates.extend(sorted(root.glob("*/meta.json")))
    for meta_path in candidates:
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
        except Exception:
            continue
        if isinstance(meta, dict):
            return meta
    return None


def pipeline_vector_width(name: str) -> int | None:
    """Width of the static word vectors of an installed pipeline, without loading it.

    ``0`` means no vectors, ``None`` that the pipeline is not installed or
    declares nothing.
    """
    if is_blank(str(name or "").strip()):
        return 0
    meta = pipeline_meta(name)
    vectors = meta.get("vectors") if meta else None
    if not isinstance(vectors, dict):
        return None
    try:
        rows = int(vectors.get("vectors") or vectors.get("keys") or 0)
        width = int(vectors.get("width") or 0)
    except (TypeError, ValueError):
        return None
    return width if rows > 0 else 0


def pipeline_has_parser(name: str) -> bool:
    """True when the pipeline runs a dependency parser by default (``meta.json``)."""
    meta = pipeline_meta(name)
    components = meta.get("pipeline") if meta else None
    return isinstance(components, list) and "parser" in components


def is_blank(name: str) -> bool:
    return bool(_BLANK.fullmatch(name.strip()))


def pipeline_installed(name: str) -> bool:
    """True when ``name`` can be loaded here without a download.

    ``blank:<lang>`` only needs spaCy itself, a path needs to exist, a package
    name needs to be importable (``en_core_web_sm`` and so on).
    """
    name = name.strip()
    if not name:
        return False
    if is_blank(name):
        return importlib.util.find_spec("spacy") is not None
    if "/" in name or "\\" in name:
        return Path(name).expanduser().exists()
    try:
        return importlib.util.find_spec(name.replace("-", "_")) is not None
    except (ImportError, ValueError):
        return False


def blank_alternative(name: str) -> str:
    """``blank:<lang>`` for the language of ``name`` (``en_core_web_sm`` -> ``blank:en``)."""
    match = _LANG_PREFIX.match(name.strip())
    return f"blank:{match.group(1)}" if match else "blank:xx"


def missing_text(name: str) -> LocalizedText:
    """Bilingual form of :func:`missing_message` for server answers."""
    return lt(
        "Die spaCy-Pipeline '{name}' ist nicht installiert. "
        "Installation mit: candy pipeline {name} (lädt sie von GitHub, "
        "explosion/spacy-models). "
        "Für eine Tokenisierung ohne linguistische Annotation die Pipeline {blank} verwenden.",
        "The spaCy pipeline '{name}' is not installed. "
        "Install it with: candy pipeline {name} (downloads it from GitHub, "
        "explosion/spacy-models). "
        "To tokenize without linguistic annotation, use the pipeline {blank}.",
    ).format(name=name, blank=blank_alternative(name))


def missing_message(name: str) -> str:
    """English message for the CLI and build logs."""
    return missing_text(name).en


def download_url(name: str) -> str:
    """The wheel URL of the release of ``name`` that fits the installed spaCy.

    Uses spaCy's own compatibility table (one request to GitHub).
    """
    from urllib.parse import urljoin

    from spacy import about
    from spacy.cli.download import get_compatibility, get_model_filename, get_version

    version = get_version(name, get_compatibility())
    return urljoin(about.__download_url__ + "/", get_model_filename(name, version))


def install_command(url: str, *, target: Path | None = None) -> list[str]:
    """pip or uv command that installs the pipeline wheel at ``url``.

    ``--no-deps``: a pipeline only depends on spaCy, which is installed.
    """
    extra = ["--no-deps"]
    if target is not None:
        extra += ["--target", str(target)]
    if importlib.util.find_spec("pip") is not None:
        return [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *extra, url]
    uv = shutil.which("uv")
    if uv is not None:
        python = [] if target is not None else ["--python", sys.executable]
        return [uv, "pip", "install", *python, *extra, url]
    raise RuntimeError(
        "Neither pip nor uv is available to install the pipeline. "
        f"Download {url} and install it into this Python environment."
    )
