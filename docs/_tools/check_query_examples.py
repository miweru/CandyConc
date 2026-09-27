#!/usr/bin/env python3
"""Check the query examples of the query language reference.

``docs/_data/query_examples.json`` holds every example query that the
reference shows, with the corpus it runs on and the recorded result (hits
and documents, or a rejection). The ``query-example`` directive renders the
examples from this file. This script runs every example against a running
CandyConc server and reports every difference. With ``--record`` it writes
the results it observed.

Usage::

    python docs/_tools/check_query_examples.py --server http://127.0.0.1:8010 \\
      --corpus sotu=sotu_en --corpus dta=dta_de --corpus tea=tea_demo
    python docs/_tools/check_query_examples.py --server ... --record

The corpus keys (sotu, dta, tea) are the keys under ``corpora`` in the JSON
file. The values are the corpus names on your server. The recorded results
of sotu and dta come from the imports in ``examples/README.md``
(``--language en`` with en_core_web_md, ``--language de`` with
de_core_news_md), the index that the tutorial "First results" builds. Another
pipeline gives other lemmas, parts of speech, and dependency relations. See
``docs/contribute/documentation.md`` for how to prepare the three corpora.

Only the standard library is used. Exit status 0 means that every example
gave its recorded result.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "_data" / "query_examples.json"


def _call(method: str, url: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(10):
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as err:
            payload = err.read().decode("utf-8")
            if err.code == 429:
                # The server limits requests per client and minute. Wait for
                # the next window instead of reporting a false difference.
                time.sleep(15)
                continue
            try:
                return err.code, json.loads(payload)
            except json.JSONDecodeError:
                return err.code, payload
    return 429, {"detail": "rate limit still exceeded after retries"}


def run_example(base: str, corpus: str, query: str) -> dict:
    """Return {"status": "ok", "hits": n, "docs": m} or {"status": "rejected", "code": c}."""
    params = urllib.parse.urlencode({"term": query, "corpus": corpus, "limit": 1})
    status, payload = _call("GET", f"{base}/query?{params}")
    if status == 400:
        return {"status": "rejected", "code": status}
    if status != 200:
        return {"status": "error", "detail": payload}
    params = urllib.parse.urlencode({"term": query, "corpus": corpus, "wait_ms": 60000})
    status, count = _call("GET", f"{base}/query/count?{params}")
    if status != 200 or count.get("status") != "ready" or count.get("partial"):
        return {"status": "error", "detail": count}
    status, docset = _call("POST", f"{base}/analysis/docset_from_search",
                           {"query": query, "corpus": corpus, "familien": False})
    docs = docset.get("hit_doc_count") if status == 200 else None
    return {"status": "ok", "hits": int(count["total"]), "docs": docs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--server", required=True, help="base URL, for example http://127.0.0.1:8010")
    parser.add_argument("--corpus", action="append", default=[],
                        help="KEY=NAME, maps a corpus key of the JSON file to a corpus name on the server")
    parser.add_argument("--record", action="store_true", help="write the observed results into the JSON file")
    args = parser.parse_args()

    base = args.server.rstrip("/") + "/api/v1"
    mapping = dict(item.split("=", 1) for item in args.corpus)
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    failures = 0
    for example in data["examples"]:
        key = example["corpus"]
        corpus = mapping.get(key, data["corpora"][key]["default_name"])
        observed = run_example(base, corpus, example["query"])
        if observed["status"] == "error":
            print(f"ERROR {example['id']}: {observed['detail']}")
            failures += 1
            continue
        expected = {"status": example.get("status"), "hits": example.get("hits"), "docs": example.get("docs")}
        got = {"status": observed["status"], "hits": observed.get("hits"), "docs": observed.get("docs")}
        if expected != got:
            print(f"DIFF  {example['id']}: recorded {expected}, observed {got}  ({example['query']})")
            failures += 1
        else:
            print(f"ok    {example['id']}: {got['status']} {got['hits'] if got['hits'] is not None else ''}")
        if args.record:
            example["status"] = observed["status"]
            example["hits"] = observed.get("hits")
            example["docs"] = observed.get("docs")
    if args.record:
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"results written to {DATA_FILE}")
        return 0
    print(f"{len(data['examples'])} examples, {failures} differences")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
