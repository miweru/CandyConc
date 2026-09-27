try:
    from spacy.cli import download
    from spacy.util import is_package
except ImportError:  # spaCy not installed — provide no-op stubs
    def download(model: str) -> None:  # type: ignore[misc]
        pass

    def is_package(name: str) -> bool:  # type: ignore[misc]
        return False


def ensure_spacy_model(model: str) -> bool:
    """Ensure required spaCy model is available."""
    if is_package(model):
        return True
    try:
        download(model)
    except SystemExit:
        pass
    return is_package(model)
