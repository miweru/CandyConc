"""Convert the compact output of ``cwb-decode -C`` into VRT with real attributes.

A corpus that exists only as an encoded IMS Open Corpus Workbench corpus has
no VRT source. ``cwb-decode -C`` prints token lines and structural tags, but
writes every structural attribute as a tag of its own (``<name value>``). The
VRT import of CandyConc expects ONE segment element that carries its
attributes as XML attributes (``<speech speaker="..." date="...">``).

This script translates between the two. It keeps track of all open
structural attributes and copies them onto a segment when the segment starts.
An attribute of an enclosing element (for example a session date around many
speeches) therefore ends up on every segment inside it.

Example:

    cwb-decode -r REGISTRY -C CORPUS \\
        -P word -P lemma -P pos \\
        -S speech -S speech_speaker -S session_date -S s \\
      | python3 -m candyconc.ingest.cwb_decode_to_vrt --segment speech > out.vrt

Nothing is dropped silently: tokens outside every segment are counted and
reported on stderr at the end (see also ``--strict-attrs`` of the VRT import).
"""

from __future__ import annotations

import argparse
import re
import sys
from xml.sax.saxutils import quoteattr

#: ``<name wert>`` oder ``<name>`` (oeffnend), ``</name>`` (schliessend).
OEFFNEND = re.compile(r"^<([A-Za-z_][\w.:-]*)(?:\s+(.*?))?\s*>$")
SCHLIESSEND = re.compile(r"^</([A-Za-z_][\w.:-]*)\s*>$")


#: ``who="Labe" name="Paul Loebe" party="SPD"`` als Tag-Wert.
UNTERATTRIBUT = re.compile(r'([A-Za-z_][\w.:-]*)\s*=\s*"([^"]*)"')


def _unterattribute(wert: str) -> dict[str, str]:
    """Attributliste im Tag-Wert aufloesen, sonst leeres Ergebnis.

    Nur wenn der GESAMTE Wert aus solchen Paaren besteht -- ein Wert wie
    ``Rede zum Haushalt`` bleibt unangetastet.
    """
    text = (wert or "").strip()
    if not text or "=" not in text:
        return {}
    treffer = list(UNTERATTRIBUT.finditer(text))
    if not treffer:
        return {}
    rest = UNTERATTRIBUT.sub("", text).strip()
    if rest:
        return {}
    return {m.group(1): m.group(2) for m in treffer}


def _tag_zeile(zeile: str) -> tuple[str, str, bool] | None:
    """(name, wert, schliessend) fuer eine Struktur-Tag-Zeile, sonst None."""
    text = zeile.strip()
    if not text.startswith("<") or not text.endswith(">"):
        return None
    zu = SCHLIESSEND.match(text)
    if zu:
        return zu.group(1), "", True
    auf = OEFFNEND.match(text)
    if auf:
        return auf.group(1), (auf.group(2) or "").strip(), False
    return None


def konvertiere(
    zeilen,
    ausgabe,
    *,
    segment: str,
    satz_tag: str = "s",
    ignoriere: frozenset[str] = frozenset(),
) -> dict[str, int]:
    """CWB-Kompaktzeilen nach VRT wandeln. Rueckgabe: Kennzahlen."""
    offen: dict[str, str] = {}
    im_segment = False
    # The segment tag is written only at the first token. CWB emits all
    # structural tags that open at the same corpus position one after
    # another, and their order depends on the order of the -S flags. Writing
    # the tag immediately would lose every attribute that opens AFTER it,
    # which in a parliamentary corpus can be the party affiliation, the very
    # variable under study. An attribute that arrives only AFTER the first
    # token is still reported, because then it is really too late and no
    # longer applies to this segment.
    warte_auf_token = False
    verspaetet: dict[str, int] = {}
    zahlen = {"segmente": 0, "tokens": 0, "tokens_ausserhalb": 0, "saetze": 0}
    puffer: list[str] = []

    def _segment_schreiben() -> None:
        nonlocal warte_auf_token
        if not warte_auf_token:
            return
        warte_auf_token = False
        wert = offen.get(segment, "")
        attrs = {
            k: v
            for k, v in offen.items()
            if k != segment and v and k not in ignoriere
        }
        unter = _unterattribute(wert)
        if unter:
            for k, v in unter.items():
                if k not in ignoriere and v:
                    attrs.setdefault("%s_%s" % (segment, k), v)
        elif wert:
            attrs.setdefault(segment + "_value", wert)
        gerendert = " ".join(
            "%s=%s" % (k, quoteattr(v)) for k, v in sorted(attrs.items())
        )
        ausgabe.write(
            "<%s%s>\n" % (segment, (" " + gerendert) if gerendert else "")
        )
        for zeile in puffer:
            ausgabe.write(zeile)
        puffer.clear()

    for zeile in zeilen:
        roh = zeile.rstrip("\n")
        tag = _tag_zeile(roh)

        if tag is None:
            if not roh.strip():
                continue
            if im_segment:
                _segment_schreiben()
                ausgabe.write(roh + "\n")
                zahlen["tokens"] += 1
            else:
                # Token ausserhalb jedes Segments: NICHT still verwerfen.
                zahlen["tokens_ausserhalb"] += 1
            continue

        name, wert, schliessend = tag

        if name == satz_tag:
            if im_segment:
                marke = ("</%s>" if schliessend else "<%s>") % satz_tag + "\n"
                if warte_auf_token:
                    puffer.append(marke)
                else:
                    ausgabe.write(marke)
                if not schliessend:
                    zahlen["saetze"] += 1
            continue

        if name == segment:
            if schliessend:
                if im_segment:
                    _segment_schreiben()
                    ausgabe.write("</%s>\n" % segment)
                    im_segment = False
                offen.pop(name, None)
                continue
            if im_segment:
                _segment_schreiben()
                ausgabe.write("</%s>\n" % segment)
            offen[name] = wert
            im_segment = True
            warte_auf_token = True
            puffer.clear()
            zahlen["segmente"] += 1
            continue

        # Jedes andere Struktur-Attribut: nur Buch fuehren. Kommt es erst
        # NACH dem ersten Token des Segments, gilt es fuer dieses Segment
        # nicht mehr -- das wird gezaehlt statt verschwiegen.
        if schliessend:
            offen.pop(name, None)
        else:
            offen[name] = wert
            if im_segment and not warte_auf_token:
                verspaetet[name] = verspaetet.get(name, 0) + 1

    if im_segment:
        _segment_schreiben()
        ausgabe.write("</%s>\n" % segment)
    zahlen["attribute_zu_spaet"] = sum(verspaetet.values())
    zahlen["attribute_zu_spaet_namen"] = verspaetet
    return zahlen


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Convert the output of cwb-decode -C into VRT with real XML attributes."
    )
    p.add_argument(
        "--segment",
        required=True,
        help="structural attribute that delimits one document, for example speech",
    )
    p.add_argument("--sentence-tag", default="s", help="structural attribute of sentences (default: s)")
    p.add_argument(
        "--ignore-attrs",
        default="",
        help="comma-separated structural attributes that are not copied onto the segments",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="exit with status 1 when tokens lie outside every segment (they are dropped and counted)",
    )
    args = p.parse_args(argv)

    zahlen = konvertiere(
        sys.stdin,
        sys.stdout,
        segment=args.segment,
        satz_tag=args.sentence_tag,
        ignoriere=frozenset(
            t.strip() for t in args.ignore_attrs.split(",") if t.strip()
        ),
    )
    bericht = (
        "cwb_decode_to_vrt: %(segmente)d Segmente, %(saetze)d Saetze, "
        "%(tokens)d Tokens" % zahlen
    )
    if zahlen["tokens_ausserhalb"]:
        bericht += (
            ", %d Tokens ausserhalb jedes '%s'-Segments VERWORFEN"
            % (zahlen["tokens_ausserhalb"], args.segment)
        )
    print(bericht, file=sys.stderr)
    if args.strict and zahlen["tokens_ausserhalb"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
