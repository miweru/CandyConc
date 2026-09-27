#!/usr/bin/env python3
"""Prepare the two CandyConc sample corpora from their primary sources.

English: C-SPAN State of the Union Address Corpus 1945-2006 as distributed by
NLTK Data (package ``state_union``, 65 addresses). Addresses of the US
President are works of the US federal government (17 U.S.C. 105), NLTK lists
the package as "public domain".

German: a stratified sample of 30 complete texts from the DTA core corpus
(Deutsches Textarchiv, normalized plain text release 2020-10-23, 1800-1899).
DTA full texts are licensed CC BY-SA 4.0, attribution "Deutsches Textarchiv".

The script is deterministic: pinned URLs, pinned SHA-256 checksums, a fixed
selection rule and sorted output. Only the Python standard library is used.

Usage:
    python prepare_sample_corpora.py --workdir /path/to/workdir

Outputs in <workdir>/prepared/:
    sotu_en_1945_2006.jsonl
    dta_de_1800_1899_sample.jsonl
    ATTRIBUTION.txt
    prepare_manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

DOWNLOADS = {
    "state_union.zip": {
        "url": "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/state_union.zip",
        "sha256": "366c1dc82b2abf896f42b2ec50ba802a0141a29f75d29ca48a7a243ce5bfbe8d",
        # MD5 published in https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/index.xml
        "md5": "044f2d20c592b17a26ac0102111833c9",
    },
    "dtak_2020-10-23_normalized_1800-1899.zip": {
        "url": "https://www.deutschestextarchiv.de/media/download/dtak/2020-10-23/normalized/1800-1899.zip",
        "sha256": "84b334bdbff73099366fe09ce298cc5659fec1fcabf22b4aa45446db00192615",
    },
    "dta_metadaten_oai_dc_2026-02-12.zip": {
        "url": "https://www.deutschestextarchiv.de/media/download/dta_metadaten_oai_dc_2026-02-12.zip",
        "sha256": "97cee635634aa92064daa67ecb71c313cf2726044b0b1853d03de67a10893775",
    },
}

# Party affiliation is public record. Key: surname part of the NLTK file name.
PRESIDENTS = {
    "Truman": ("Harry S. Truman", "Democratic"),
    "Eisenhower": ("Dwight D. Eisenhower", "Republican"),
    "Kennedy": ("John F. Kennedy", "Democratic"),
    "Johnson": ("Lyndon B. Johnson", "Democratic"),
    "Nixon": ("Richard Nixon", "Republican"),
    "Ford": ("Gerald R. Ford", "Republican"),
    "Carter": ("Jimmy Carter", "Democratic"),
    "Reagan": ("Ronald Reagan", "Republican"),
    "Bush": ("George H. W. Bush", "Republican"),
    "Clinton": ("Bill Clinton", "Democratic"),
    "GWBush": ("George W. Bush", "Republican"),
}

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December",
        ],
        start=1,
    )
}
DATE_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),\s+(\d{4})\b")

# Five NLTK files (Nixon 1970-1974) are Big5-encoded. The only non-ASCII
# characters in them are typographic punctuation, so Big5 is accepted only if
# every decoded non-ASCII character is in this set.
BIG5_ALLOWED = {"’", "—", "“", "”", "…", "　"}

DTA_GENRES = ("Belletristik", "Gebrauchsliteratur", "Wissenschaft")
DTA_MIN_WORDS = 5_000
DTA_MAX_WORDS = 40_000
DTA_TARGET_WORDS = 15_000
DC = {"dc": "http://purl.org/dc/elements/1.1/"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(downloads: Path, name: str, offline: bool) -> Path:
    spec = DOWNLOADS[name]
    target = downloads / name
    if not target.exists():
        if offline:
            raise SystemExit(f"missing {target} and --offline is set")
        print(f"download {spec['url']}", file=sys.stderr)
        tmp = target.with_suffix(target.suffix + ".part")
        req = urllib.request.Request(spec["url"], headers={"User-Agent": "candyconc-sample-prep/1"})
        with urllib.request.urlopen(req) as resp, tmp.open("wb") as out:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        tmp.rename(target)
    digest = sha256_file(target)
    if digest != spec["sha256"]:
        raise SystemExit(f"checksum mismatch for {target}: {digest} != {spec['sha256']}")
    return target


def decode_sotu(raw: bytes) -> tuple[str, str]:
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        text = raw.decode("big5")
        if all(ord(ch) < 128 or ch in BIG5_ALLOWED for ch in text):
            return text.replace("　", " "), "big5"
    except UnicodeDecodeError:
        pass
    return raw.decode("cp1252"), "cp1252"


def prepare_sotu(zip_path: Path) -> list[dict]:
    rows = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".txt"):
                continue
            stem = Path(name).stem  # e.g. 1965-Johnson-2
            parts = stem.split("-")
            year, surname = parts[0], parts[1]
            president, party = PRESIDENTS[surname]
            text, encoding = decode_sotu(zf.read(name))
            text = text.replace("\r\n", "\n").strip()
            lines = [ln.strip() for ln in text.split("\n")]
            title = lines[0]
            head = " ".join(lines[:4])
            m = DATE_RE.search(head)
            date = ""
            if m and m.group(3) == year:
                date = f"{m.group(3)}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
            rows.append(
                {
                    "id": f"sotu-{stem}",
                    "text": text,
                    "president": president,
                    "party": party,
                    "year": year,
                    "decade": f"{year[:3]}0s",
                    "date": date,
                    "title": title,
                    "source_file": name,
                    "source_encoding": encoding,
                }
            )
    return rows


def load_dta_metadata(zip_path: Path) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.endswith(".oai_dc.xml"):
                continue
            root = ET.fromstring(zf.read(name))
            ident = (root.findtext("dc:identifier", namespaces=DC) or "").rstrip("/")
            dirname = ident.rsplit("/", 1)[-1]
            meta[dirname] = {
                "url": ident,
                "title": root.findtext("dc:title", namespaces=DC) or "",
                "creators": [e.text or "" for e in root.findall("dc:creator", DC)],
                "subjects": [e.text or "" for e in root.findall("dc:subject", DC)],
                "date": root.findtext("dc:date", namespaces=DC) or "",
                "publisher": root.findtext("dc:publisher", namespaces=DC) or "",
                "edition": root.findtext("dc:source", namespaces=DC) or "",
            }
    return meta


def prepare_dta(zip_path: Path, meta_zip: Path) -> tuple[list[dict], list[dict]]:
    meta = load_dta_metadata(meta_zip)
    candidates: dict[tuple[str, str], list[tuple[int, str, str, dict]]] = {}
    with zipfile.ZipFile(zip_path) as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".txt"):
                continue
            dirname = Path(name).stem
            m = meta.get(dirname)
            if m is None or m["publisher"] != "Deutsches Textarchiv (Kernkorpus)":
                continue
            genre, _, subgenre = (m["subjects"][0] if m["subjects"] else "").partition(":")
            genre, subgenre = genre.strip(), subgenre.strip()
            ymatch = re.match(r"(\d{4})", m["date"])
            if genre not in DTA_GENRES or ymatch is None:
                continue
            year = ymatch.group(1)
            if not ("1800" <= year <= "1899"):
                continue
            text = zf.read(name).decode("utf-8").replace("\r\n", "\n").strip()
            words = len(text.split())
            if not (DTA_MIN_WORDS <= words <= DTA_MAX_WORDS):
                continue
            cell = (f"{year[:3]}0s", genre)
            candidates.setdefault(cell, []).append((words, dirname, text, dict(m, genre=genre, subgenre=subgenre, year=year)))
    rows, selection = [], []
    for cell in sorted(candidates):
        pool = sorted(candidates[cell], key=lambda c: (abs(c[0] - DTA_TARGET_WORDS), c[1]))
        words, dirname, text, m = pool[0]
        title = re.sub(r"\s*\(vollständige digitalisierte Ausgabe\)\s*$", "", m["title"]).strip()
        title = re.sub(r"\s{2,}", " ", title)
        rows.append(
            {
                "id": dirname,
                "text": text,
                "author": "; ".join(c for c in m["creators"] if c) or "unbekannt",
                "title": title,
                "year": m["year"],
                "decade": cell[0],
                "genre": m["genre"],
                "subgenre": m["subgenre"],
                "url": m["url"],
                "edition": m["edition"],
            }
        )
        selection.append({"cell": list(cell), "chosen": dirname, "words": words, "candidates": len(pool)})
    rows.sort(key=lambda r: (r["year"], r["id"]))
    return rows, selection


ATTRIBUTION = """CandyConc sample corpora
========================

sotu_en_1945_2006.jsonl
  Content: 65 US presidential addresses to Congress, 1945-2006, as compiled
  in the "C-Span State of the Union Address Corpus" (compiled by Kathleen
  Ahrens from C-SPAN sources) and distributed by NLTK Data, package
  "state_union".
  Source: https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/state_union.zip
  Rights: works of the US federal government (17 U.S.C. 105), listed as
  "public domain" in the NLTK Data index.
  Changes: character encoding normalised to UTF-8 (Big5 punctuation in the
  Nixon files and cp1252 characters decoded), metadata fields added
  (president, party, year, decade, date, title). Text otherwise unchanged.

dta_de_1800_1899_sample.jsonl
  Content: 30 complete texts from the DTA core corpus (normalised plain text
  release 2020-10-23, period 1800-1899), one per decade and main genre.
  Source: Deutsches Textarchiv. Grundlage fuer ein Referenzkorpus der
  neuhochdeutschen Sprache. Herausgegeben von der Berlin-Brandenburgischen
  Akademie der Wissenschaften, Berlin. https://www.deutschestextarchiv.de/
  Metadata: DTA Dublin Core metadata release 2026-02-12.
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/).
  Attribution: "Deutsches Textarchiv". Each document carries its DTA URL.
  Changes: selection of 30 texts, metadata fields added (author, title,
  year, decade, genre, subgenre, url, edition). Text unchanged.
  This prepared file is distributed under CC BY-SA 4.0.
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--offline", action="store_true", help="fail instead of downloading")
    args = ap.parse_args(argv)

    downloads = args.workdir / "downloads"
    prepared = args.workdir / "prepared"
    downloads.mkdir(parents=True, exist_ok=True)
    prepared.mkdir(parents=True, exist_ok=True)

    paths = {name: fetch(downloads, name, args.offline) for name in DOWNLOADS}

    sotu = prepare_sotu(paths["state_union.zip"])
    dta, selection = prepare_dta(
        paths["dtak_2020-10-23_normalized_1800-1899.zip"],
        paths["dta_metadaten_oai_dc_2026-02-12.zip"],
    )

    outputs = {}
    for fname, rows in (("sotu_en_1945_2006.jsonl", sotu), ("dta_de_1800_1899_sample.jsonl", dta)):
        out = prepared / fname
        with out.open("w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
        outputs[fname] = {
            "documents": len(rows),
            "whitespace_words": sum(len(r["text"].split()) for r in rows),
            "sha256": sha256_file(out),
            "bytes": out.stat().st_size,
        }
    (prepared / "ATTRIBUTION.txt").write_text(ATTRIBUTION, encoding="utf-8")

    manifest = {
        "prepared_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script": Path(__file__).name,
        "inputs": {name: {"url": spec["url"], "sha256": spec["sha256"]} for name, spec in DOWNLOADS.items()},
        "dta_selection_rule": {
            "corpus": "DTA core corpus (publisher 'Deutsches Textarchiv (Kernkorpus)'), normalized plain text 2020-10-23",
            "years": "1800-1899 (dc:date)",
            "genres": list(DTA_GENRES),
            "whitespace_words": [DTA_MIN_WORDS, DTA_MAX_WORDS],
            "per_cell": f"one text per decade x genre, closest to {DTA_TARGET_WORDS} words, ties by DTA dirname",
        },
        "dta_selection": selection,
        "outputs": outputs,
    }
    (prepared / "prepare_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
