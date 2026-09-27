from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path
import json
import zipfile
import random
import logging

from anytree import AnyNode, PreOrderIter

from .resources import ResourceRegistry

LOGGER = logging.getLogger(__name__)


_ALGO_SPECS: Dict[str, Dict[str, Any]] = {
    "filter_contains": {
        "name": "filter_contains",
        "description": "Filter rows by substring match",
        "args_schema": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "enum": ["left", "kw", "right", "file", "any"],
                    "default": "any",
                },
                "value": {"type": "string"},
                "case_sensitive": {"type": "boolean", "default": False},
            },
            "required": ["value"],
        },
    },
    "limit": {
        "name": "limit",
        "description": "Limit rows",
        "args_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "default": 1000}},
            "required": ["n"],
        },
    },
    "sort": {
        "name": "sort",
        "description": "Sort rows",
        "args_schema": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "enum": ["left", "kw", "right", "file", "pos"],
                    "default": "pos",
                },
                "order": {"type": "string", "enum": ["asc", "desc"], "default": "asc"},
            },
            "required": ["field"],
        },
    },
    "dedup": {
        "name": "dedup",
        "description": "Remove duplicate rows",
        "args_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["row_id", "left_kw_right"],
                    "default": "row_id",
                }
            },
        },
    },
    "sample": {
        "name": "sample",
        "description": "Sample rows",
        "args_schema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "default": 100},
                "seed": {"type": "integer", "default": 0},
            },
            "required": ["n"],
        },
    },
}


def _row_id(row: dict[str, Any]) -> str:
    rid = row.get("row_id")
    if rid is not None:
        return str(rid)
    return f"{row.get('file','')}::{row.get('pos','')}::{row.get('kw','')}"


class AnalysisTreeNode(AnyNode):
    """Analysis tree node bound to an executable Concordance pipeline."""

    def __init__(
        self,
        node_type: str,
        parent: Optional["AnalysisTreeNode"],
        id: int | None = None,
        concordance: "Concordance" | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent=parent)
        if self.parent is None:
            self._last_id = 0
        self.id = id if id is not None else self._next_id()
        self.node_type = node_type
        self.concordance = (
            (lambda conc=concordance: conc) if concordance else parent.concordance
        )
        self.bookmarked = kwargs.get("bookmarked", False)
        self.label = kwargs.get("label", "")
        self.algorithms = kwargs.get("algorithms", {})
        for key, value in kwargs.items():
            setattr(self, key, value)

    def _next_id(self) -> int:
        if self.parent is not None:
            return self.root._next_id()
        if not hasattr(self, "_last_id"):
            self._last_id = 0
        else:
            self._last_id += 1
        return self._last_id

    def schema_for(self, name: str) -> dict:
        conc = self.concordance()
        if conc is None:
            raise RuntimeError("Concordance fehlt")
        return conc.schema_for(name)

    def view(self) -> Dict[str, Any]:
        conc = self.concordance()
        if conc is None:
            raise RuntimeError("Concordance fehlt")
        return conc.view(self.id)

    def summary(self, fmt: str = "text") -> str:
        view = self.view()
        rows = view.get("rows", []) if isinstance(view, dict) else []
        if fmt == "json":
            return json.dumps({"rows": len(rows)}, ensure_ascii=False)
        return f"Treffer: {len(rows)}"


class Concordance:
    """Fast Index concordance with real algorithm pipeline."""

    def __init__(self) -> None:
        self.info: Dict[str, Any] = {}
        self.resources = ResourceRegistry()
        self.available_algorithms: Dict[str, Any] = dict(_ALGO_SPECS)
        self.root = AnalysisTreeNode(
            node_type="subset",
            parent=None,
            id=0,
            concordance=self,
            label="root",
        )
        self._views: Dict[int, Dict[str, Any]] = {self.root.id: {"rows": []}}

    def list_algorithms(self) -> List[Dict[str, Any]]:
        return list(self.available_algorithms.values())

    def schema_for(self, name: str) -> dict:
        meta = self.available_algorithms.get(name)
        if not meta:
            raise RuntimeError(f"Algorithmus unbekannt: {name}")
        return meta.get("args_schema", {"type": "object", "properties": {}})

    def set_root_view(self, rows: list[dict[str, Any]]) -> None:
        self._views[self.root.id] = {"rows": list(rows)}
        self.root.line_count = len(rows)

    def _apply_algorithm(
        self, name: str, args: Dict[str, Any], rows: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if name == "filter_contains":
            field = str(args.get("field", "any"))
            value = str(args.get("value", ""))
            case_sensitive = bool(args.get("case_sensitive", False))
            if not value:
                raise RuntimeError("filter_contains: value fehlt")
            if not case_sensitive:
                value_cmp = value.lower()
            else:
                value_cmp = value

            def _match(row: dict[str, Any]) -> bool:
                if field == "any":
                    parts = [
                        row.get("left", ""),
                        row.get("kw", ""),
                        row.get("right", ""),
                        row.get("file", ""),
                    ]
                else:
                    parts = [row.get(field, "")]
                for part in parts:
                    text = str(part)
                    text_cmp = text if case_sensitive else text.lower()
                    if value_cmp in text_cmp:
                        return True
                return False

            return [r for r in rows if _match(r)]

        if name == "limit":
            n = int(args.get("n", 0))
            if n <= 0:
                raise RuntimeError("limit: n muss > 0 sein")
            return rows[:n]

        if name == "sort":
            field = str(args.get("field", "pos"))
            order = str(args.get("order", "asc"))
            reverse = order.lower() == "desc"
            return sorted(rows, key=lambda r: r.get(field, ""), reverse=reverse)

        if name == "dedup":
            mode = str(args.get("mode", "row_id"))
            seen: set[str] = set()
            out: list[dict[str, Any]] = []
            for r in rows:
                if mode == "left_kw_right":
                    key = f"{r.get('left','')}|{r.get('kw','')}|{r.get('right','')}"
                else:
                    key = _row_id(r)
                if key in seen:
                    continue
                seen.add(key)
                out.append(r)
            return out

        if name == "sample":
            n = int(args.get("n", 0))
            if n <= 0:
                raise RuntimeError("sample: n muss > 0 sein")
            seed = int(args.get("seed", 0))
            if n >= len(rows):
                return list(rows)
            rng = random.Random(seed)
            return rng.sample(rows, n)

        raise RuntimeError(f"Algorithmus nicht implementiert: {name}")

    def add_node(self, specs: List[tuple[str, Dict[str, Any]]]) -> AnalysisTreeNode:
        if not specs:
            raise RuntimeError("Keine Pipeline Schritte definiert")
        base_view = self._views.get(self.root.id, {"rows": []})
        rows = list(base_view.get("rows", []))
        if not rows:
            raise RuntimeError("Keine Basisdaten für Pipeline vorhanden")
        for name, args in specs:
            if name not in self.available_algorithms:
                raise RuntimeError(f"Algorithmus unbekannt: {name}")
            rows = self._apply_algorithm(name, args, rows)
        node = AnalysisTreeNode(
            node_type="subset",
            parent=self.root,
            concordance=self,
            algorithms={"subset": {"specs": specs}},
        )
        self._views[node.id] = {"rows": rows}
        node.line_count = len(rows)
        return node

    def view(self, node_id: int) -> Dict[str, Any]:
        if node_id in self._views:
            return self._views[node_id]
        node = None
        for n in PreOrderIter(self.root):
            if getattr(n, "id", None) == node_id:
                node = n
                break
        if node is None:
            raise RuntimeError(f"Unbekannter Node: {node_id}")
        self._compute_node(node)
        return self._views.get(node_id, {"rows": []})

    def _compute_node(self, node: AnalysisTreeNode) -> None:
        algos = getattr(node, "algorithms", {})
        specs = None
        if isinstance(algos, dict):
            subset = algos.get("subset")
            if isinstance(subset, dict):
                specs = subset.get("specs")
        if not specs:
            raise RuntimeError("Node ohne Pipeline Spezifikation")
        base_view = self._views.get(self.root.id, {"rows": []})
        rows = list(base_view.get("rows", []))
        if not rows:
            raise RuntimeError("Keine Basisdaten für Pipeline vorhanden")
        for name, args in specs:
            rows = self._apply_algorithm(name, args, rows)
        self._views[node.id] = {"rows": rows}
        node.line_count = len(rows)

    def compute_nodes(self) -> None:
        for node in PreOrderIter(self.root):
            if node.id not in self._views and node is not self.root:
                self._compute_node(node)

    def _node_to_dict(self, node: AnalysisTreeNode) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": node.id,
            "node_type": getattr(node, "node_type", "subset"),
            "label": getattr(node, "label", ""),
        }
        if hasattr(node, "algorithms"):
            data["algorithms"] = node.algorithms
        if node.children:
            data["children"] = [self._node_to_dict(c) for c in node.children]
        return data

    def export(self, path: str, *, as_zip: bool = False) -> None:
        payload = {
            "analysis_tree": self._node_to_dict(self.root),
            "info": self.info,
        }
        if as_zip or str(path).lower().endswith(".zip"):
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("analysis_tree.json", json.dumps(payload, ensure_ascii=False))
        else:
            out_dir = Path(path)
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "analysis_tree.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
