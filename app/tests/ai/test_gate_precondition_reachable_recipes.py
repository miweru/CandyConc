"""Tool prerequisites remain reachable without making a recipe eligible by themselves.

A keyness gate requiring two live docsets must expose create_docset.
Keep prerequisite tools separate from core tools, since create_docset
alone must not make a recipe eligible when keyness is unavailable."""

from __future__ import annotations

import pathlib
import re
from unittest import mock

from candyconc.candyconc_copilot.grounding_contracts import (
    _recipe_tools_available,
)
from candyconc.candyconc_copilot.recipe_runtime import expand_tools_for_recipe
from candyconc.candyconc_copilot.recipes import RECIPES

# tests/conftest.py ersetzt ``candyconc.tooling.registry.REGISTRY`` durch eine
# Stubliste, die create_docset NICHT kennt. Ein Test, der den Werkzeugraum
# darauf misst, sieht den Deadlock nie verschwinden und den Fix nie greifen:
# er misst den Stub. ``REAL_REGISTRY`` laedt die echten Specs ueber den
# etablierten Loader (tests/tooling/_real_tooling.py), damit hier der
# Produktivpfad geprueft wird und nicht die Testkulisse.
from tests.tooling._real_tooling import REAL_REGISTRY

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"

ECHTE_WERKZEUGNAMEN = {
    str((t.get("function") or {}).get("name") or "")
    for t in REAL_REGISTRY
    if isinstance(t, dict)
}


def _rezept(familie: str):
    treffer = [r for r in RECIPES if familie in getattr(r, "familien", ())]
    assert len(treffer) == 1, f"{familie}: {len(treffer)} Rezepte"
    return treffer[0]


def _werkzeugraum(rezept_id: str, vorhanden: tuple[str, ...]) -> set[str]:
    """Der Werkzeugraum, den der Turn nach dem Routing tatsaechlich sieht.

    ``expand_tools_for_recipe`` importiert die Registry LAZY im Rumpf, also
    genuegt es, das Modulattribut fuer die Dauer des Aufrufs auf die echten
    Specs zu setzen.
    """

    raum = [
        {"type": "function", "function": {"name": name}} for name in vorhanden
    ]
    # TEUER GELERNT: ``import candyconc.tooling.registry as reg`` liefert den
    # sys.modules-Eintrag, ``from candyconc.tooling.registry import REGISTRY``
    # im Produktionscode loest dagegen ueber das PAKETATTRIBUT auf. In einem
    # Einzellauf sind beide dasselbe Objekt und der Test war gruen. In der
    # vollen Suite hatte ein frueheres Modul beide auseinanderlaufen lassen,
    # der Patch sass auf dem falschen Objekt, und die Wache meldete einen
    # Werkzeugraum von ['keyness'] — also genau den Deadlock, den sie
    # beweisen sollte, obwohl der Fix stand. Deshalb wird hier dieselbe
    # Auflösung nachgebaut, die die Produktion verwendet.
    modul = __import__(
        "candyconc.tooling.registry", fromlist=["REGISTRY"]
    )
    with mock.patch.object(modul, "REGISTRY", REAL_REGISTRY):
        erweitert = expand_tools_for_recipe(raum, rezept_id)
    return {
        str((t.get("function") or {}).get("name") or "") for t in erweitert
    }


def test_keyness_rezept_kann_seine_eigene_vorbedingung_erfuellen():
    """Verhalten, nicht Feldmitgliedschaft: kommt create_docset AN?"""

    r = _rezept("contrast_keyness")
    raum = _werkzeugraum(r.id, ("keyness",))
    assert "create_docset" in raum, (
        "Der Riegel keyness_before_two_live_docsets verlangt zwei Docsets. "
        "Ohne create_docset im Werkzeugraum kann das Modell sie nicht bauen, "
        "und der Turn steht. Gemessen: 16 Anomalien, alle mit "
        f"exposed=keyness. Raum war: {sorted(raum)}"
    )


def test_keyness_bleibt_das_fuehrende_kernwerkzeug():
    """An kern_tools[0] haengt das Capability-Gate (grounding_contracts:3249)."""

    assert _rezept("contrast_keyness").kern_tools[0] == "keyness"


def test_wegbereiter_allein_macht_das_rezept_nicht_waehlbar():
    """Die Regression aus dem ersten Reparaturanlauf, ausbuchstabiert.

    Ein Korpus, das Docsets bauen kann, aber kein ``keyness`` anbietet,
    darf das Kontrast-Rezept NICHT bekommen. Sonst waehlt der Router ein
    Rezept, dessen Messwerkzeug fehlt.
    """

    r = _rezept("contrast_keyness")
    ohne_keyness = (
        "run_cqlf_query",
        "collocate_stats",
        "metadata_values",
        "create_docset",
        "list_docsets",
        "frequency_list",
    )
    assert not _recipe_tools_available(r, ohne_keyness), (
        "create_docset allein hat das Rezept waehlbar gemacht. Wegbereiter "
        "gehoeren in wegbereiter_tools, nicht in kern_tools."
    )
    assert _recipe_tools_available(r, ohne_keyness + ("keyness",))


def test_kein_rezept_wird_allein_durch_seine_wegbereiter_waehlbar():
    """Dieselbe Falle, fuer alle Rezepte auf einmal.

    Auszaehlend statt exemplarisch: jedes Rezept mit Wegbereitern wird
    gegen einen Werkzeugraum geprueft, der NUR seine Wegbereiter enthaelt.
    """

    geprueft = 0
    for r in RECIPES:
        wegbereiter = tuple(getattr(r, "wegbereiter_tools", ()) or ())
        if not wegbereiter:
            continue
        geprueft += 1
        assert not _recipe_tools_available(r, wegbereiter), (
            f"{r.id}: allein durch Wegbereiter {wegbereiter} waehlbar. "
            "Damit entscheidet ein Hilfswerkzeug ueber die Rezeptwahl."
        )
    assert geprueft >= 1, "Kein Rezept mit Wegbereitern: Test laeuft leer."


def test_wegbereiter_sind_echte_registry_werkzeuge():
    """Ein Wegbereiter, den die Registry nicht kennt, erweitert nichts.

    ``expand_tools_for_recipe`` sucht die Spec in der Registry und schweigt,
    wenn sie fehlt. Ein Tippfehler waere damit unsichtbar und der Deadlock
    zurueck.
    """

    bekannt = ECHTE_WERKZEUGNAMEN
    for r in RECIPES:
        for name in getattr(r, "wegbereiter_tools", ()) or ():
            assert name in bekannt, (
                f"{r.id}: Wegbereiter {name!r} steht in keiner Registry-Spec. "
                "expand_tools_for_recipe wuerde ihn stillschweigend "
                "ueberspringen."
            )


def test_der_riegel_raet_zu_einem_werkzeug_das_im_raum_steht():
    """Der Rat der Fehlermeldung muss befolgbar sein.

    Keine Tautologie: der Test liest die Meldung aus dem Orchestrator, holt
    daraus die geratene Handlung und prueft, dass das Werkzeug, das sie
    ausfuehrt, im Werkzeugraum des Rezepts ankommt.
    """

    quelle = (
        SRC / "candyconc" / "candyconc_copilot" / "orchestrator.py"
    ).read_text(encoding="utf-8")
    treffer = re.search(
        r'"reason":\s*"keyness_before_two_live_docsets",\s*'
        r'"message":\s*\(\s*((?:"[^"]*"\s*)+)\)',
        quelle,
    )
    assert treffer, (
        "Riegel-Meldung nicht gefunden. Wurde sie umbenannt, prueft dieser "
        "Test nichts mehr."
    )
    meldung = " ".join(re.findall(r'"([^"]*)"', treffer.group(1)))
    assert "Erzeuge" in meldung and "scopes" in meldung.lower(), meldung

    raum = _werkzeugraum(_rezept("contrast_keyness").id, ("keyness",))
    assert "create_docset" in raum, (
        f"Die Meldung raet {meldung!r}, aber das Werkzeug, das Scopes "
        f"erzeugt, fehlt im Raum: {sorted(raum)}"
    )


def test_die_erweiterung_sitzt_auf_dem_produktivpfad():
    """Eine Funktion, die niemand ruft, behebt keinen Deadlock.

    Die Tests oben rufen ``expand_tools_for_recipe`` direkt. Sie wuerden
    auch dann gruen bleiben, wenn der Orchestrator den Aufruf verloere,
    und der Deadlock waere still zurueck. Diese Wache prueft deshalb die
    NAHT: der Aufruf steht in ``run_async``, direkt nach dem Routing, und
    sein Ergebnis wird ``self.tools`` zugewiesen. Genau das ist der
    Werkzeugraum, den der Turn dem Modell anbietet.
    """

    import ast

    quelle = (
        SRC / "candyconc" / "candyconc_copilot" / "orchestrator.py"
    ).read_text(encoding="utf-8")
    baum = ast.parse(quelle)

    # GEGENPRUEFUNG Runde 1, Schritt 4: die erste Fassung dieser Wache
    # suchte die Zuweisung IRGENDWO in der Datei. Ein adversarialer Pruefer
    # hat den Aufruf in run_async durch ``pass`` ersetzt und dieselbe
    # Zuweisung in eine nie gerufene Modulfunktion gehaengt: der Deadlock
    # war zurueck, die Wache blieb gruen. Sie war damit genau die Klasse
    # Test, die sie ersetzen sollte. Jetzt zaehlt die FUNKTION, in der die
    # Zuweisung steht.
    ziel_funktion = "run_async"
    treffer = []
    for knoten in ast.walk(baum):
        if not isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if knoten.name != ziel_funktion:
            continue
        for innen in ast.walk(knoten):
            if (
                isinstance(innen, ast.Assign)
                and isinstance(innen.value, ast.Call)
                and getattr(innen.value.func, "id", "")
                == "expand_tools_for_recipe"
            ):
                treffer.append(
                    (innen.lineno, {ast.unparse(z) for z in innen.targets})
                )
    assert treffer, (
        f"In {ziel_funktion}() steht keine Zuweisung aus "
        "expand_tools_for_recipe. Der Werkzeugraum des Turns bekommt die "
        "Kernwerkzeuge dann nicht, und der Docset-Deadlock ist zurueck. "
        "Eine Zuweisung anderswo in der Datei genuegt NICHT: sie kann in "
        "einer Funktion stehen, die niemand ruft."
    )
    ziele = set().union(*(z for _zeile, z in treffer))
    assert "self.tools" in ziele, (
        f"Das Ergebnis landet nicht in self.tools, sondern in {ziele}. "
        "Nur self.tools ist der Werkzeugraum des Turns."
    )
