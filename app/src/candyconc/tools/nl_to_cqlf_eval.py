from __future__ import annotations

from pathlib import Path
import json
from typing import Callable, Dict, List

def evaluate_nl_to_cqlf(path: str | Path, call_fn: Callable[[str], str] | None = None) -> float:
    """Return accuracy of NL-to-CQLF generation against a gold standard dataset."""
    # Import lazily: candyconc_copilot re-exports this evaluator, so importing
    # the evaluator before the package must not create a package cycle.
    from candyconc.candyconc_copilot import generate, validate

    data = json.loads(Path(path).read_text())
    if not data:
        return 0.0
    fn = call_fn or generate
    total = 0
    correct = 0
    for item in data:
        prompt = item.get("prompt", "")
        expected = item.get("query", "")
        if not prompt or not expected:
            continue
        pred = fn(prompt)
        if not validate(pred)["errors"] and pred.strip() == expected.strip():
            correct += 1
        total += 1
    return correct / total if total else 0.0


def store_feedback(path: str | Path, prompt: str, query: str, prediction: str) -> None:
    """Append a feedback entry with ``prompt``, gold ``query`` and ``prediction``."""
    file = Path(path)
    try:
        data: List[Dict[str, str]] = json.loads(file.read_text())
    except Exception:
        data = []
    data.append({"prompt": prompt, "query": query, "prediction": prediction})
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2))


__all__ = ["evaluate_nl_to_cqlf", "store_feedback"]
