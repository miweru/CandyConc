from __future__ import annotations

from pathlib import Path
from typing import List
import json
import tempfile
import threading
import re


_SQLITE_MAGIC = b"SQLite format 3\x00"


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in re.findall(r"\w+", text)]


class MemoryStore:
    """Simple in-memory store for text notes."""

    def __init__(self, *, path: str | Path | None = None) -> None:
        tmp_dir = Path(tempfile.gettempdir())
        self.path = Path(path) if path is not None else tmp_dir / "session_memory.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.notes: List[str] = []
        self.tokens: List[List[str]] = []
        self.token_sets: List[set[str]] = []
        if self.path.exists():
            raw = self.path.read_bytes()
            if raw.startswith(_SQLITE_MAGIC):
                raise RuntimeError("Legacy Memory Store ist nicht mehr unterstützt.")
            try:
                text = raw.decode("utf-8")
            except Exception as exc:
                raise RuntimeError(f"Memory Store ist unlesbar: {self.path}") from exc
            for line_no, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception as exc:
                    raise RuntimeError(
                        f"Memory Store JSON ungültig in Zeile {line_no}: {self.path}"
                    ) from exc
                if not isinstance(row, dict):
                    raise RuntimeError(
                        f"Memory Store Eintrag ist kein Objekt in Zeile {line_no}: {self.path}"
                    )
                note = row.get("note")
                if not isinstance(note, str):
                    raise RuntimeError(
                        f"Memory Store Eintrag ohne note in Zeile {line_no}: {self.path}"
                    )
                toks = row.get("tokens")
                if not isinstance(toks, list):
                    toks = _tokenize(note)
                self.notes.append(note)
                toks_list = [str(t) for t in toks]
                self.tokens.append(toks_list)
                self.token_sets.append(set(toks_list))

    def close(self) -> None:
        return

    def _append(self, note: str, tokens: List[str]) -> None:
        row = {"note": note, "tokens": tokens}
        line = json.dumps(row, ensure_ascii=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def add(self, note: str) -> None:
        """Add ``note`` to the store."""
        toks = _tokenize(note)
        self.notes.append(note)
        self.tokens.append(toks)
        self.token_sets.append(set(toks))
        self._append(note, toks)

    def search(self, query: str, k: int = 3) -> List[str]:
        """Return the ``k`` notes most similar to ``query``."""
        if not self.notes:
            return []
        qtokens = set(_tokenize(query))
        if not qtokens:
            return []
        scored = []
        for note, tset in zip(self.notes, self.token_sets):
            if not tset:
                continue
            inter = len(qtokens & tset)
            score = inter / max(len(qtokens), 1)
            if score > 0:
                scored.append((score, note))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored[:k]]
