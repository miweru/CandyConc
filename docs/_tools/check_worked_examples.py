#!/usr/bin/env python3
"""Check the worked examples of the methods reference.

The methods pages show tables from ``docs/_data/worked_examples.json``. Each
table is a recorded response on the synthetic tea corpus or the public
State of the Union sample. This script

1. recomputes every value in these tables from the corpus file with its own
   code (standard library only, nothing is imported from CandyConc) and
   reports every difference, and
2. with ``--server``, requests the same analyses from a running CandyConc
   server and reports every difference to the recorded tables, and
3. with ``--server`` and ``--record``, replaces the recorded tables with the
   server responses (after both checks passed).

Usage::

    python docs/_tools/check_worked_examples.py
    python docs/_tools/check_worked_examples.py --server http://127.0.0.1:8010 --corpus tea_demo
    python docs/_tools/check_worked_examples.py --server http://127.0.0.1:8010 --corpus tea_demo --record

The corpus must have been imported with::

    candy import --input docs/methods/data/tea_demo.jsonl --output ~/.candyconc/corpora/tea_demo \\
      --text-column text --id-column id --meta-columns date register --spacy-model blank:en

The word sketch table needs dependency relations and is recorded from a
second import with ``--spacy-model en_core_web_sm --enable-deps``. For that
table the script counts preserved dependency annotations in
``methods/data/tea_dependencies.json``. The SOTU check uses all candidate
count pairs in ``methods/data/sotu_counts.json``, including the BH correction.
Both input files record their provenance. No analysis results are imported.

Exit status 0 means that every check passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent
CORPUS_FILE = DOCS / "methods" / "data" / "tea_demo.jsonl"
DATA_FILE = DOCS / "_data" / "worked_examples.json"

Z95 = 1.959963984540054
LRC_ALPHA = 0.001

# --------------------------------------------------------------------------
# Corpus model, written from the definitions on the methods pages
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[^\W_]+|[^\w\s]", re.UNICODE)
_SENTENCE_END = {".", "!", "?"}


def load_corpus() -> list[dict]:
    docs = []
    with CORPUS_FILE.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                docs.append(json.loads(line))
    for doc in docs:
        tokens = _TOKEN_RE.findall(doc["text"])
        sentences, current = [], []
        for tok in tokens:
            current.append(tok)
            if tok in _SENTENCE_END:
                sentences.append(current)
                current = []
        if current:
            sentences.append(current)
        doc["sentences"] = sentences
        doc["tokens"] = tokens
    return docs


def is_word_token(tok: str) -> bool:
    """Word token: not empty, not an index marker, contains a letter or digit."""
    t = tok.strip()
    return bool(t) and not (t.startswith("|") and t.endswith("|")) and any(c.isalnum() for c in t)


def positions(docs):
    """Flat token list with sentence and document numbers."""
    toks, sent, doc = [], [], []
    sid = 0
    for di, d in enumerate(docs):
        for s in d["sentences"]:
            for t in s:
                toks.append(t)
                sent.append(sid)
                doc.append(di)
            sid += 1
    return toks, sent, doc


# --------------------------------------------------------------------------
# Statistics helpers (standard library only)
# --------------------------------------------------------------------------


def g2(table):
    """Log-likelihood G2 over a 2x2 table [[a, b], [c, d]]."""
    (a, b), (c, d) = table
    n = a + b + c + d
    rows = (a + b, c + d)
    cols = (a + c, b + d)
    total = 0.0
    for i, row in enumerate(table):
        for j, o in enumerate(row):
            e = rows[i] * cols[j] / n
            if o > 0:
                total += o * math.log(o / e)
    return 2 * total


def chi2_pearson(table):
    (a, b), (c, d) = table
    n = a + b + c + d
    rows = (a + b, c + d)
    cols = (a + c, b + d)
    total = 0.0
    for i, row in enumerate(table):
        for j, o in enumerate(row):
            e = rows[i] * cols[j] / n
            total += (o - e) ** 2 / e
    return total


def chi2_sf_1df(x: float) -> float:
    return math.erfc(math.sqrt(max(x, 0.0) / 2.0))


def _betacf(a: float, b: float, x: float) -> float:
    # Continued fraction for the incomplete beta function (Lentz).
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(q: float, a: float, b: float) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if betainc(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def lrc(a: int, b: int, n1: float, n2: float, m: int) -> float:
    """Conservative Log Ratio: the bound nearer to zero of the exact
    Clopper-Pearson interval for a / (a + b), Bonferroni-corrected over m
    tests, converted to the Log Ratio scale. Zero if the interval contains 0."""
    alpha = LRC_ALPHA / max(1, m)
    n = a + b
    p_lo = beta_ppf(alpha / 2, a, n - a + 1) if a > 0 else 0.0
    p_hi = beta_ppf(1 - alpha / 2, a + 1, n - a) if b > 0 else 1.0
    offset = math.log2(n2 / n1)
    lo = math.log2(p_lo / (1 - p_lo)) + offset if 0 < p_lo < 1 else -math.inf
    hi = math.log2(p_hi / (1 - p_hi)) + offset if 0 < p_hi < 1 else math.inf
    if lo > 0:
        return lo
    if hi < 0:
        return hi
    return 0.0


def benjamini_hochberg(pvals: list[float]) -> list[float]:
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, pvals[i] * m / rank)
        q[i] = prev
    return q


def wilson(hits: int, n: int, z: float = Z95) -> tuple[float, float]:
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


# --------------------------------------------------------------------------
# Independent recomputation of each recorded table
# --------------------------------------------------------------------------


def recompute(docs) -> dict:
    out: dict = {}
    toks, sent, doc = positions(docs)
    N = len(toks)
    words_folded = Counter(t.lower() for t in toks if is_word_token(t))

    # Frequency and hit counts
    out["frequency-tea"] = {
        "corpus_tokens": N,
        "word_tokens": sum(words_folded.values()),
        "row_tea": words_folded["tea"],
        "total_candidates": len(words_folded),
        "exact_tea": sum(1 for t in toks if t == "tea"),
        "exact_Tea": sum(1 for t in toks if t == "Tea"),
        "exact_TEA": sum(1 for t in toks if t == "TEA"),
        "plain_tea": words_folded["tea"], "plain_Tea": words_folded["tea"],
        "plain_Tea_case_sensitive": toks.count("Tea"),
        "cql_Tea": toks.count("Tea"), "cql_tea_c": words_folded["tea"],
    }

    out["frequency-tea"]["counts"] = dict(words_folded)

    # Keyness blog against news
    def side(register):
        return [t for d in docs if d["register"] == register for t in d["tokens"]]

    tgt, ref = side("blog"), side("news")
    ft = Counter(t.lower() for t in tgt if is_word_token(t))
    fr = Counter(t.lower() for t in ref if is_word_token(t))
    nt, nr = sum(ft.values()), sum(fr.values())
    cands = [w for w in sorted(set(ft) | set(fr)) if ft[w] + fr[w] >= 5]
    m = len(cands)
    rows = []
    for w in cands:
        a, c = ft[w], fr[w]
        table = [[a, nt - a], [c, nr - c]]
        ll = g2(table)
        lr = math.log2(((a + 0.5) / nt) / ((c + 0.5) / nr))
        se = math.sqrt(1 / (a + 0.5) - 1 / (nt + 0.5) + 1 / (c + 0.5) - 1 / (nr + 0.5)) / math.log(2)
        sign = 1.0 if a / nt >= c / nr else -1.0
        rows.append({
            "word": w, "target_freq": a, "reference_freq": c,
            "target_per_million": a / nt * 1e6, "reference_per_million": c / nr * 1e6,
            "ll": ll, "ll_signed": sign * ll, "chi2": chi2_pearson(table),
            "log_ratio": lr, "log_ratio_ci_low": lr - Z95 * se, "log_ratio_ci_high": lr + Z95 * se,
            "lrc": lrc(a, c, nt, nr, m), "p_value": chi2_sf_1df(ll),
            "bic": ll - math.log(nt + nr),
        })
    for row, q in zip(rows, benjamini_hochberg([r["p_value"] for r in rows])):
        row["q_value"] = q
    rows.sort(key=lambda r: -r["ll_signed"])
    out["keyness-blog-news"] = {"target_total": nt, "reference_total": nr,
                                "target_tokens_raw": len(tgt), "reference_tokens_raw": len(ref),
                                "total_candidates": m, "rows": rows}

    # Collocations of tea, window 3, within sentences
    node = "tea"
    window = 3
    anchors = [i for i, t in enumerate(toks) if t.lower() == node]
    union = set()
    for p in anchors:
        for q in range(p - window, p + window + 1):
            if q != p and 0 <= q < N and sent[q] == sent[p]:
                union.add(q)
    r1 = len(union)
    fu = len(anchors)
    observed = Counter(toks[q] for q in union if toks[q].lower() != node)
    freq_exact = Counter(toks)
    floor = max(2, min(fu // 10, 5)) if fu < 50 else 5
    coll_rows = []
    candidates_all = {v: o for v, o in observed.items() if o >= floor and is_word_token(v)}
    for v, o11 in candidates_all.items():
        c1 = freq_exact[v]
        e11 = r1 * c1 / N
        o12, o21 = r1 - o11, c1 - o11
        mi = math.log2(o11 / e11)
        dice_w = 2 * o11 / (r1 + c1)
        coll_rows.append({
            "word": v, "observed": o11, "f2": c1, "expected": e11,
            "mi": mi, "mi3": math.log2(o11 ** 3 / e11), "lmi": o11 * mi,
            "npmi": mi / -math.log2(o11 / N),
            "t": (o11 - e11) / math.sqrt(o11), "z": (o11 - e11) / math.sqrt(e11),
            "chi2_cell": (o11 - e11) ** 2 / e11,
            "ll": g2([[o11, o12], [o21, N - r1 - c1 + o11]]),
            "dice": dice_w, "logdice_window": 14 + math.log2(dice_w),
            "logdice": 14 + math.log2(2 * o11 / (fu + c1)),
            "delta_p_nc": o11 / r1 - o21 / (N - r1),
            "delta_p_cn": o11 / c1 - o12 / (N - c1),
            "log_ratio": math.log2(((o11 + 0.5) / r1) / ((c1 - o11 + 0.5) / (N - r1))),
            "lrc": lrc(o11, c1 - o11, r1, N - r1, len(candidates_all)),
        })
    coll_rows.sort(key=lambda r: (-round(r["logdice"], 4), r["word"]))
    out["collocation-tea"] = {"node_frequency": fu, "window": window, "within_sentence": True, "target_total": N,
                              "effective_min_cooccurrence": floor, "rows": coll_rows}

    # Lines behind a collocate: node hits with the collocate in the window, in
    # the exact spelling that the collocation row counts
    def lines_for(collocate: str) -> int:
        count = 0
        for p in anchors:
            for q in range(p - window, p + window + 1):
                if q != p and 0 <= q < N and sent[q] == sent[p] and toks[q] == collocate:
                    count += 1
                    break
        return count

    out["collocation-lines"] = {"rows": [
        {"word": w, "observed": observed[w], "lines": lines_for(w)} for w in ("green", "a", "A")
    ]}

    # Dispersion of tea and coffee
    def dispersion(term: str) -> dict:
        o = [sum(1 for t in d["tokens"] if t.lower() == term) for d in docs]
        s = [len(d["tokens"]) for d in docs]
        F, Ntot, n = sum(o), sum(s), len(o)
        exp = [x / Ntot for x in s]
        dp = 0.5 * sum(abs(oi / F - ei) for oi, ei in zip(o, exp))
        v = [oi / si for oi, si in zip(o, s)]
        mean = sum(v) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in v) / n)
        vc = sd / mean
        shares = [oi / F for oi in o]
        proportional = [math.floor(F * p) for p in exp]
        remainder = sorted(range(n), key=lambda i: F * exp[i] - proportional[i], reverse=True)
        for i in remainder[:F - sum(proportional)]:
            proportional[i] += 1
        dp_min = 0.5 * sum(abs(c / F - p) for c, p in zip(proportional, exp))
        # Linearity of expectation permits exact binomial marginals here.
        dp_expected = 0.5 * sum(
            math.comb(F, k) * p ** k * (1 - p) ** (F - k) * abs(k / F - p)
            for p in exp for k in range(F + 1)
        )
        dp_max = 1 - min(exp)
        classification = ("zu_wenig_treffer" if dp_max - dp_min < 0.05 else
                          "even" if dp <= 0.75 * dp_expected else
                          "fairly_even" if dp <= dp_expected else
                          "fairly_clustered" if dp <= (dp_expected + dp_max) / 2 else "clustered")
        return {
            "term": term, "partitions": o, "doc_sizes": s,
            "dp": dp, "dpnorm": dp / (1 - min(exp)), "vc": vc,
            "juilland_d": min(1.0, max(0.0, 1 - vc / math.sqrt(n - 1))),
            "carroll_d2": -sum(p * math.log(p) for p in shares if p > 0) / math.log(n),
            "range": sum(1 for x in o if x > 0), "range_prop": sum(1 for x in o if x > 0) / n,
            "dp_min": dp_min, "dp_max": dp_max,
            "dp_expected": dp_expected, "classification": classification,
        }

    out["dispersion"] = {"rows": [dispersion("tea"), dispersion("coffee")]}
    out["dispersion-tea-parts"] = {"rows": [
        {"document": d["id"], "register": d["register"],
         "hits": sum(t.lower() == "tea" for t in d["tokens"]), "tokens": len(d["tokens"])}
        for d in docs
    ]}

    # Trend of tea per year, divided by the word tokens of the period
    trend_rows = []
    for year in sorted({d["date"][:4] for d in docs}):
        ds = [d for d in docs if d["date"].startswith(year)]
        hits = sum(1 for d in ds for t in d["tokens"] if t.lower() == "tea")
        n = sum(1 for d in ds for t in d["tokens"] if is_word_token(t))
        lo, hi = wilson(hits, n)
        trend_rows.append({"period": year, "documents": len(ds), "hits": hits, "tokens": n,
                           "per_million": hits / n * 1e6, "ci_low": lo * 1e6, "ci_high": hi * 1e6})
    out["trend-tea"] = {"rows": trend_rows}

    # Bigrams within documents, word tokens only, exact spelling
    bigrams = Counter()
    for d in docs:
        t = d["tokens"]
        for i in range(len(t) - 1):
            if is_word_token(t[i]) and is_word_token(t[i + 1]):
                bigrams[f"{t[i]} {t[i + 1]}"] += 1
    out["bigrams-tea"] = {"total_candidates": len(bigrams), "counts": dict(bigrams)}

    # Lexical diversity, window 20
    stream = [t for d in docs for t in d["tokens"] if is_word_token(t)]
    n_tok, n_types, w = len(stream), len(set(stream)), 20
    k = n_tok // w
    sttr = sum(len(set(stream[i * w:(i + 1) * w])) / w for i in range(k)) / k
    mattr = sum(len(set(stream[i:i + w])) / w for i in range(n_tok - w + 1)) / (n_tok - w + 1)
    out["lexdiv-tea"] = {"n_tokens": n_tok, "n_types": n_types, "ttr": n_types / n_tok,
                         "guiraud": n_types / math.sqrt(n_tok), "sttr": sttr, "sttr_windows": k,
                         "mattr": mattr}
    deps = load_input("tea_dependencies.json")
    if deps["tokens"] != toks:
        raise ValueError("Preserved dependency tokens differ from tea_demo.jsonl")
    pairs = Counter()
    for dep, (head, rel) in enumerate(zip(deps["head_positions"], deps["relations"])):
        if rel in {"ROOT", "punct", "case", "pnc"} or head < 0 or head == dep:
            continue
        if toks[head] == "tea" and is_word_token(toks[dep]):
            pairs[rel, toks[dep]] += 1
        if toks[dep] == "tea" and is_word_token(toks[head]):
            pairs[rel + "_rev", toks[head]] += 1
    # The public sketch omits self pairs when that relation has other words.
    non_self_relations = {rel for rel, word in pairs if word.lower() != "tea"}
    ws_rows = []
    f1 = freq_exact["tea"]
    for (rel, word), o in pairs.items():
        if word.lower() == "tea" and rel in non_self_relations:
            continue
        f2 = freq_exact[word]
        e = f1 * f2 / N
        ws_rows.append({
            "relation": rel, "word": word, "f": o, "f2": f2,
            "logdice": 14 + math.log2(2 * o / (f1 + f2)),
            "ll": g2([[o, f1 - o], [f2 - o, N - f1 - f2 + o]]),
            "chi2_cell": (o - e) ** 2 / e, "t": (o - e) / math.sqrt(o),
        })
    out["wordsketch-tea"] = {"node_frequency": f1, "corpus_tokens": N, "rows": ws_rows}
    return out


def load_input(name: str) -> dict:
    data = json.loads((CORPUS_FILE.parent / name).read_text(encoding="utf-8"))
    provenance = data["provenance"]
    source = DOCS.parent / provenance["source_file"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != provenance["source_sha256"]:
        raise ValueError(f"{name}: source corpus hash differs from the preserved input")
    return data


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.checked = 0

    def value(self, label: str, recorded, expected, tol: float) -> None:
        self.checked += 1
        if isinstance(expected, float) and isinstance(recorded, (int, float)):
            scale = abs(expected) if label.endswith((" p_value", " q_value")) else max(1.0, abs(expected))
            equal = math.isfinite(recorded) and abs(recorded - expected) <= tol * scale
        else:
            equal = recorded == expected
        if not equal:
            self.failures.append(f"{label}: recorded {recorded!r}, expected {expected!r}")

    def fields(self, label, recorded, expected, tolerances=None):
        self.value(f"{label} fields", sorted(recorded), sorted(expected), 0)
        for key, value in expected.items():
            self.value(f"{label} {key}", recorded.get(key), value, (tolerances or {}).get(key, 1e-3))

    def rows(self, label, recorded, expected, keys, tolerances=None):
        identities = lambda rows: [tuple(row.get(k) for k in keys) for row in rows]
        actual_ids, expected_ids = identities(recorded), identities(expected)
        self.value(f"{label} rows", Counter(actual_ids), Counter(expected_ids), 0)
        actual = dict(zip(actual_ids, recorded))
        for identity, row in zip(expected_ids, expected):
            self.fields(f"{label} {' '.join(map(str, identity))}", actual.get(identity, {}), row, tolerances)

    def top_counts(self, label, recorded, counts, key, count_key, limit, *, fold=False):
        names = [str(row.get(key, "")) for row in recorded]
        identities = [word.lower() if fold else word for word in names]
        self.value(f"{label} row count", len(recorded), min(limit, len(counts)), 0)
        self.value(f"{label} unique rows", len(set(identities)), len(recorded), 0)
        # Ties at the display limit may select different equally frequent items.
        self.value(f"{label} top frequencies", [row.get(count_key) for row in recorded],
                   sorted(counts.values(), reverse=True)[:limit], 0)
        for name, identity, row in zip(names, identities, recorded):
            self.fields(f"{label} {name}", row, {key: name, count_key: counts.get(identity)})


def check_against(recorded: dict, computed: dict, report: Report, *, source: str) -> None:
    tables = recorded["tables"]
    for name, expected in computed.items():
        actual = tables.get(name, {})
        facts = {k: v for k, v in expected.items() if k not in {"rows", "counts"}}
        if facts:
            tolerances = {key: 1e-6 for key in facts} if name == "lexdiv-tea" else {}
            report.fields(f"{source} {name} facts", actual.get("facts", {}), facts, tolerances)
        if name == "frequency-tea":
            report.top_counts(f"{source} {name}", actual.get("rows", []), expected["counts"],
                              "word", "f", 12, fold=True)
        elif name == "bigrams-tea":
            report.top_counts(f"{source} {name}", actual.get("rows", []), expected["counts"],
                              "ngram", "freq", 10)
        elif "rows" in expected:
            keys = {"dispersion": ("term",), "dispersion-tea-parts": ("document",),
                    "trend-tea": ("period",), "wordsketch-tea": ("relation", "word")}.get(name, ("word",))
            tolerances = ({"expected": 0.006, "t": 0.006, "chi2_cell": 0.006, "ll": 0.006}
                          if name == "collocation-tea" else {})
            if name == "collocation-tea":
                report.value(f"{source} {name} order",
                             [r.get("word") for r in actual.get("rows", [])],
                             [r["word"] for r in expected["rows"]], 0)
            if name == "trend-tea":
                tolerances = {key: 1e-6 for row in expected["rows"] for key in row}
            report.rows(f"{source} {name}", actual.get("rows", []), expected["rows"], keys, tolerances)


# --------------------------------------------------------------------------
# Server access and recording
# --------------------------------------------------------------------------


class Server:
    def __init__(self, base: str, corpus: str, deps_corpus: str | None, sotu_corpus: str | None = None) -> None:
        self.base = base.rstrip("/") + "/api/v1"
        self.corpus = corpus
        self.deps_corpus = deps_corpus
        self.sotu_corpus = sotu_corpus
        self.token = None

    def _request(self, method: str, path: str, params=None, body=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get(self, path, **params):
        return self._request("GET", path, params=params)

    def post(self, path, body):
        return self._request("POST", path, body=body)

    def login_local(self) -> None:
        # Single-user mode hands out a local token. In multi-user mode, pass
        # a token with --token instead.
        if self.token is None:
            self.token = self._request("GET", "/auth/dev-token").get("token")


def record(server: Server) -> dict:
    c = server.corpus
    tables: dict = {}
    fl = server.get("/analysis/frequency_list", corpus=c, limit=12)
    counts = {}
    for key, term, extra in (("plain_tea", "tea", {}), ("plain_Tea", "Tea", {}),
                             ("plain_Tea_case_sensitive", "Tea", {"case_insensitive": "false"}),
                             ("cql_Tea", 'cql:[word="Tea"]', {}), ("cql_tea_c", 'cql:[word="tea"%c]', {})):
        counts[key] = server.get("/query/count", corpus=c, term=term, wait_ms=10000, **extra)["total"]
    info = next(x for x in server.get("/corpora")["corpora"] if x["name"] == c)
    row_tea = next(r for r in fl["rows"] if r["word"].lower() == "tea")
    tables["frequency-tea"] = {"facts": {
        "corpus_tokens": info["token_count"], "word_tokens": None, "row_tea": row_tea["f"],
        "total_candidates": fl["total_candidates"], **counts,
        "exact_tea": server.get("/query/count", corpus=c, term='cql:[word="tea"]', wait_ms=10000)["total"],
        "exact_Tea": counts["cql_Tea"],
        "exact_TEA": server.get("/query/count", corpus=c, term='cql:[word="TEA"]', wait_ms=10000)["total"],
    }, "rows": [{"word": r["word"], "f": r["f"]} for r in fl["rows"]]}
    blog = server.post("/analysis/docset_from_meta", {"corpus": c, "filters": {"register": "blog"}})
    news = server.post("/analysis/docset_from_meta", {"corpus": c, "filters": {"register": "news"}})
    k = server.post("/analysis/keyness", {"corpus": c, "target_docset_id": blog["docset_id"],
                                          "reference_docset_id": news["docset_id"]})
    km = k["method"]
    tables["keyness-blog-news"] = {"facts": {
        "target_total": km.get("target_total"), "reference_total": km.get("reference_total"),
        "target_tokens_raw": km.get("target_tokens_roh"), "reference_tokens_raw": km.get("reference_tokens_roh"),
        "total_candidates": k["total_candidates"]},
        "rows": [{key: r[key] for key in ("word", "target_freq", "reference_freq", "target_per_million",
                                          "reference_per_million", "ll", "ll_signed", "chi2", "log_ratio",
                                          "log_ratio_ci_low", "log_ratio_ci_high", "lrc", "p_value", "q_value",
                                          "bic")} for r in k["rows"]]}
    co = server.get("/analysis/collocates", corpus=c, term="tea", window=3)
    cm = co["method"]
    tables["collocation-tea"] = {"facts": {
        "node_frequency": cm.get("node_frequency"), "effective_min_cooccurrence": cm.get("effective_min_cooccurrence"),
        "window": cm.get("window"), "within_sentence": cm.get("within_sentence"), "target_total": cm.get("target_total")},
        "rows": [{key: r[key] for key in ("word", "observed", "f2", "expected", "mi", "mi3", "lmi", "npmi", "t", "z",
                                          "chi2_cell", "ll", "dice", "logdice_window", "logdice", "delta_p_nc",
                                          "delta_p_cn", "log_ratio", "lrc")} for r in co["rows"]]}
    obs = {r["word"]: r["observed"] for r in co["rows"]}
    tables["collocation-lines"] = {"rows": [
        {"word": w, "observed": obs[w],
         "lines": server.get("/analysis/collocates/kwic", corpus=c, term="tea", collocate=w, window=3)["total"]}
        for w in ("green", "a", "A")]}
    disp_rows = []
    for term in ("tea", "coffee"):
        d = server.get("/analysis/dispersion", corpus=c, term=term)
        disp_rows.append({"term": term, **{key: d[key] for key in (
            "partitions", "doc_sizes", "dp", "dpnorm", "vc", "juilland_d", "carroll_d2", "range", "range_prop",
            "dp_min", "dp_max", "classification")}, "dp_expected": d["dp_erwartet"]})
    tables["dispersion"] = {"rows": disp_rows}
    ids = [d["id"] for d in load_corpus()]
    registers = [d["register"] for d in load_corpus()]
    tables["dispersion-tea-parts"] = {"rows": [
        {"document": doc_id, "register": reg, "hits": hits, "tokens": size}
        for doc_id, reg, hits, size in zip(ids, registers, disp_rows[0]["partitions"], disp_rows[0]["doc_sizes"])]}
    server.login_local()
    tr = server.post("/analysis/trend", {"corpus": c, "query": "tea", "date_field": "date", "granularity": "year"})
    tables["trend-tea"] = {"rows": [{key: p[key] for key in (
        "period", "documents", "hits", "tokens", "per_million", "ci_low", "ci_high")} for p in tr["periods"]]}
    ng = server.post("/analysis/ngrams", {"corpus": c, "min_n": 2, "max_n": 2, "limit": 10})
    tables["bigrams-tea"] = {"facts": {"total_candidates": ng["total_candidates"]},
                             "rows": [{"ngram": r["ngram"], "freq": r["freq"]} for r in ng["rows"]]}
    ld = server.get("/analysis/lexical-diversity", corpus=c, sttr_window=20, mattr="true", mattr_window=20)
    tables["lexdiv-tea"] = {"facts": {"n_tokens": ld["n_tokens"], "n_types": ld["n_types"], "ttr": ld["ttr"],
                                      "guiraud": ld["guiraud"], "sttr": ld["sttr"],
                                      "sttr_windows": ld["sttr_n_windows"], "mattr": ld["mattr"]}}
    if server.deps_corpus:
        ws = server.post("/analysis/wordsketch", {"corpus": server.deps_corpus, "term": "tea", "min_freq": 1})
        info_ws = next(x for x in server.get("/corpora")["corpora"] if x["name"] == server.deps_corpus)
        rows = []
        for rel, items in ws.items():
            if not isinstance(items, list):
                continue
            for r in items:
                rows.append({"relation": rel, "word": r["word"], "f": r["f"], "f2": r["f2"],
                             "logdice": r["logdice"], "ll": r["ll"], "chi2_cell": r["chi2_cell"], "t": r["t"]})
        tea_exact = server.get("/query/count", corpus=server.deps_corpus, term='cql:[word="tea"]', wait_ms=10000)
        tables["wordsketch-tea"] = {"facts": {"node_frequency": tea_exact["total"],
                                              "corpus_tokens": info_ws["token_count"]}, "rows": rows}
    if server.sotu_corpus:
        c2 = server.sotu_corpus
        rep = server.post("/analysis/docset_from_meta", {"corpus": c2, "filters": {"party": "Republican"}})
        dem = server.post("/analysis/docset_from_meta", {"corpus": c2, "filters": {"party": "Democratic"}})
        k2 = server.post("/analysis/keyness", {"corpus": c2, "target_docset_id": rep["docset_id"],
                                               "reference_docset_id": dem["docset_id"]})
        row = next(r for r in k2["rows"] if r["word"].lower() == "freedom")
        tables["keyness-sotu-freedom"] = {"facts": {
            "target_total": k2["method"].get("target_total"), "reference_total": k2["method"].get("reference_total"),
            "target_tokens_raw": k2["method"].get("target_tokens_roh"),
            "reference_tokens_raw": k2["method"].get("reference_tokens_roh"),
            "total_candidates": k2["total_candidates"], "target_docs": rep["doc_count"], "reference_docs": dem["doc_count"]},
            "rows": [{key: row[key] for key in ("word", "target_freq", "reference_freq", "target_per_million",
                                                "reference_per_million", "ll", "log_ratio", "log_ratio_ci_low",
                                                "log_ratio_ci_high", "lrc", "p_value", "q_value", "bic")}]}
    return tables


def check_formulas_sotu(recorded: dict, report: Report, *, source: str) -> None:
    """Recompute freedom and BH from all preserved SOTU candidate counts."""
    inputs = load_input("sotu_counts.json")
    nt, nr = inputs["word_token_counts"]
    candidates = inputs["counts"]
    m = len(candidates)
    p_values = [chi2_sf_1df(g2([[a, nt - a], [c, nr - c]])) for _, a, c in candidates]
    q_values = benjamini_hochberg(p_values)
    i = next(i for i, (word, _, _) in enumerate(candidates) if word == "freedom")
    word, a, c = candidates[i]
    ll = g2([[a, nt - a], [c, nr - c]])
    lr = math.log2(((a + 0.5) / nt) / ((c + 0.5) / nr))
    se = math.sqrt(1 / (a + 0.5) - 1 / (nt + 0.5) + 1 / (c + 0.5) - 1 / (nr + 0.5)) / math.log(2)
    expected = {"word": word, "target_freq": a, "reference_freq": c,
                "target_per_million": a / nt * 1e6, "reference_per_million": c / nr * 1e6, "ll": ll,
                "log_ratio": lr, "log_ratio_ci_low": lr - Z95 * se, "log_ratio_ci_high": lr + Z95 * se,
                "lrc": lrc(a, c, nt, nr, m), "p_value": p_values[i], "q_value": q_values[i],
                "bic": ll - math.log(nt + nr)}
    facts = {"target_total": nt, "reference_total": nr, "total_candidates": m,
             "target_tokens_raw": inputs["raw_token_counts"][0],
             "reference_tokens_raw": inputs["raw_token_counts"][1],
             "target_docs": inputs["document_counts"][0], "reference_docs": inputs["document_counts"][1]}
    actual = recorded["tables"].get("keyness-sotu-freedom", {})
    report.fields(f"{source} keyness-sotu facts", actual.get("facts", {}), facts)
    report.rows(f"{source} keyness-sotu", actual.get("rows", []), [expected], ("word",))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--server", help="base URL of a running CandyConc server, for example http://127.0.0.1:8010")
    parser.add_argument("--corpus", default="tea_demo", help="name of the tea corpus on that server")
    parser.add_argument("--deps-corpus", help="name of the tea corpus imported with dependency relations")
    parser.add_argument("--sotu-corpus", help="name of the State of the Union sample corpus, for the keyness example")
    parser.add_argument("--record", action="store_true", help="replace the recorded tables with the server responses")
    args = parser.parse_args()

    docs = load_corpus()
    computed = recompute(docs)
    recorded = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    report = Report()
    if not args.record:
        check_against(recorded, computed, report, source="recorded")
        check_formulas_sotu(recorded, report, source="recorded")

    if args.server:
        server = Server(args.server, args.corpus, args.deps_corpus, args.sotu_corpus)
        live = record(server)
        if "wordsketch-tea" not in live:
            live["wordsketch-tea"] = recorded["tables"]["wordsketch-tea"]
        live["frequency-tea"]["facts"]["word_tokens"] = computed["frequency-tea"]["word_tokens"]
        check_against({"tables": live}, computed, report, source="server")
        if args.sotu_corpus:
            check_formulas_sotu({"tables": live}, report, source="server")
        if args.record and not report.failures:
            for key, table in live.items():
                recorded["tables"].setdefault(key, {}).update(table)
            DATA_FILE.write_text(json.dumps(recorded, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"recorded tables written to {DATA_FILE}")
    elif args.record:
        parser.error("--record needs --server")

    for failure in report.failures:
        print("FAIL", failure)
    print(f"{report.checked} values checked, {len(report.failures)} differences")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
