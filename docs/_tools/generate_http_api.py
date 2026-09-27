#!/usr/bin/env python3
"""Write the route tables of the HTTP API reference from the OpenAPI description.

The server describes its routes in OpenAPI (``/openapi.json`` of a running
server in single-user mode). This script builds the same description without
starting a server, joins it with the task groups and one-line purposes in
``docs/_data/http_api.json`` and with the release route matrix (roles), and
writes ``docs/reference/_generated/http_api.md``, which
``docs/reference/http-api.md`` includes. Run it with the Python environment of
CandyConc whenever a route changes::

    python docs/_tools/generate_http_api.py
    python docs/_tools/generate_http_api.py --check   # exit 1 if the file is out of date

The check also fails when a route has no entry in ``http_api.json`` or an
entry names a route that does not exist. The documentation build itself does
not import CandyConc.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent
DATA = DOCS / "_data" / "http_api.json"
OUT = DOCS / "reference" / "_generated" / "http_api.md"

#: Transport of the token, described once in the page text.
HIDDEN_PARAMETERS = {"authorization", "token"}
METHOD_ORDER = {"get": 0, "post": 1, "put": 2, "patch": 3, "delete": 4}


def _find_source() -> None:
    for candidate in (DOCS.parent / "app" / "src", DOCS.parent.parent / "app" / "src"):
        if (candidate / "candyconc" / "services" / "backend" / "server.py").is_file():
            sys.path.insert(0, str(candidate))
            return
    try:
        import candyconc.services.backend.server  # noqa: F401
    except ImportError:
        raise SystemExit("candyconc not found: run from a source checkout or install CandyConc") from None


def _local_token_routes() -> set[str]:
    """Routes that ask for a token even in single-user mode.

    Their handlers call ``_require_user_access`` or ``_require_admin_access``,
    which refuse a request without a token when role-based access control is
    off. The web interface fetches such a token from ``/api/v1/auth/dev-token``.
    """
    import inspect

    from candyconc.services.backend.server import app

    found: set[str] = set()
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        methods = getattr(route, "methods", None)
        if endpoint is None or not methods:
            continue
        try:
            source = inspect.getsource(endpoint)
        except (OSError, TypeError):
            continue
        if "_require_user_access(" in source or "_require_admin_access(" in source:
            for method in methods:
                found.add(f"{method} {route.path}")
    return found


def _openapi() -> dict:
    # A throwaway data directory and no language model: building the app
    # description must not touch the user's data or any model endpoint.
    os.environ["CANDYCONC_HOME"] = tempfile.mkdtemp(prefix="candyconc-openapi-")
    os.environ["COPILOT_ENDPOINT"] = ""
    os.environ["CANDYCONC_GEMMA_EMB_ENDPOINT"] = "http://127.0.0.1:9/v1/embeddings"
    _find_source()
    from candyconc.services.backend.server import app

    return app.openapi()


def _role(path: str) -> str:
    from candyconc.services.backend.route_matrix import policy_for_path

    policy = policy_for_path(path)
    if policy is None:
        return "unclassified"
    return {
        "public": "none",
        "user": "user",
        "manager": "manager",
        "admin": "admin",
        "owner_or_admin": "owner or admin",
    }[policy.access.value]


def _cell(text: str) -> str:
    text = " ".join(str(text).split())
    return text.replace("|", "\\|")


def _schema(spec: dict, schema: dict) -> dict:
    ref = schema.get("$ref")
    if ref:
        return spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    return schema


def _body_fields(spec: dict, operation: dict) -> list[str]:
    content = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
    if not content:
        return []
    schema = content.get("schema", {})
    resolved = _schema(spec, schema)
    fields = list(resolved.get("properties", {}))
    if fields:
        required = set(resolved.get("required", []))
        return [f"`{name}`\\*" if name in required else f"`{name}`" for name in fields]
    examples = content.get("examples") or schema.get("examples") or {}
    for example in examples.values():
        value = example.get("value") if isinstance(example, dict) else None
        if isinstance(value, dict):
            return [f"`{name}`" for name in value]
    return ["JSON object"]


def _parameters(spec: dict, operation: dict, body_override: str | None = None) -> str:
    names = []
    for parameter in operation.get("parameters", []):
        name = parameter["name"]
        if name in HIDDEN_PARAMETERS:
            continue
        mark = "\\*" if parameter.get("required") else ""
        names.append(f"`{name}`{mark}")
    body = [body_override] if body_override else _body_fields(spec, operation)
    parts = []
    if names:
        parts.append(", ".join(names) + ".")
    if body:
        parts.append("Body: " + ", ".join(body) + ".")
    return " ".join(parts)


def render() -> str:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    spec = _openapi()
    token_routes = _local_token_routes()
    entries = data["operations"]
    seen: set[str] = set()
    rows: dict[str, list[tuple[str, str, str, str, str]]] = {group["id"]: [] for group in data["groups"]}
    problems: list[str] = []
    for path, operations in spec["paths"].items():
        for method, operation in sorted(operations.items(), key=lambda item: METHOD_ORDER.get(item[0], 9)):
            key = f"{method.upper()} {path}"
            seen.add(key)
            entry = entries.get(key)
            if entry is None:
                problems.append(f"no entry in http_api.json for {key}")
                continue
            if entry["group"] not in rows:
                problems.append(f"unknown group {entry['group']!r} for {key}")
                continue
            rows[entry["group"]].append(
                (
                    f"`{method.upper()} {path}`",
                    _cell(entry["summary"]),
                    _parameters(spec, operation, entry.get("body")),
                    _role(path),
                    "yes" if key in token_routes else "",
                )
            )
    for key in sorted(set(entries) - seen):
        problems.append(f"http_api.json names {key}, the server has no such route")
    if problems:
        raise SystemExit("\n".join(problems))

    count = len(seen)
    lines = [
        "<!-- Generated by docs/_tools/generate_http_api.py from the OpenAPI description of the server and docs/_data/http_api.json. Do not edit. -->",
        "",
        f"The OpenAPI description of this version has {count} operations. For each route, the list "
        "names its purpose, its parameters (a parameter or body field marked with \\* is required), "
        "the least role in multi-user mode, and whether it needs a token in single-user mode.",
        "",
    ]
    for group in data["groups"]:
        lines += [f"### {group['title']}", "", _cell(group["intro"]), ""]
        for route, summary, parameters, role, token in rows[group["id"]]:
            facts = ["Open without sign-in." if role == "none" else f"Role: {role}."]
            if token:
                facts.append("Needs a token in single-user mode.")
            if parameters:
                facts.insert(0, parameters if parameters.startswith("Body:") else f"Parameters: {parameters}")
            lines += [route, f": {summary}", "", "  " + " ".join(facts), ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the generated file is out of date")
    args = ap.parse_args()
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != text:
            print(f"{OUT} is out of date. Run: python docs/_tools/generate_http_api.py")
            return 1
        print(f"{OUT} is current.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
