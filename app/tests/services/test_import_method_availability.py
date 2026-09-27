"""``/corpora/import-methods`` reports only what runs in this installation.

Before the builders moved into the package, the availability check looked for a
file name only: a wheel reported eight of nine methods as ``available`` while
every import failed, and ``hf`` stayed ``available`` without the ``datasets``
package.
"""

from __future__ import annotations

import pytest

from candyconc.services.backend import corpus_import_jobs as jobs


@pytest.mark.parametrize(
    "method",
    ["parquet", "vrt", "csv", "jsonl", "plaintext", "prealigned_csv", "prealigned_jsonl", "prealigned_parquet"],
)
def test_core_methods_are_available_with_core_dependencies(monkeypatch, method):
    real = jobs._module_available
    monkeypatch.setattr(jobs, "_module_available", lambda name: name != "datasets" and real(name))
    availability = jobs._builder_availability(method)
    assert availability["status"] == "available", availability


def test_hf_is_unavailable_without_datasets_and_names_the_extra(monkeypatch):
    real = jobs._module_available
    monkeypatch.setattr(jobs, "_module_available", lambda name: name != "datasets" and real(name))
    availability = jobs._builder_availability("hf")
    assert availability["status"] == "unavailable"
    assert availability["missing_packages"] == ["datasets"]
    assert "candyconc[hf]" in availability["reason"]


def test_hf_is_available_when_datasets_is_importable(monkeypatch):
    real = jobs._module_available
    monkeypatch.setattr(jobs, "_module_available", lambda name: name == "datasets" or real(name))
    assert jobs._builder_availability("hf")["status"] == "available"


def test_missing_builder_module_is_reported(monkeypatch):
    real = jobs._module_available
    monkeypatch.setattr(
        jobs,
        "_module_available",
        lambda name: name != "candyconc.ingest.build_fast_index_from_vrt" and real(name),
    )
    availability = jobs._builder_availability("vrt")
    assert availability["status"] == "unavailable"
    assert "builder module" in availability["reason"]


def test_missing_spacy_blocks_every_method(monkeypatch):
    real = jobs._module_available
    monkeypatch.setattr(jobs, "_module_available", lambda name: name != "spacy" and real(name))
    availability = jobs._builder_availability("csv")
    assert availability["status"] == "unavailable"
    assert availability["missing_packages"] == ["spacy"]
