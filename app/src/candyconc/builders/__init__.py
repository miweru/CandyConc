"""Fast-Index builder launchers.

The builder implementations live in :mod:`candyconc.ingest` and ship with the
package. This subpackage holds the launchers and the in-process dispatch:

* :mod:`_runner` runs a builder IN-PROCESS via ``importlib`` (each
  implementation exposes ``main(argv)``) and keeps a subprocess path for an
  explicit ``CANDYCONC_BUILDER_DIR`` override.
* :mod:`_impl_build_fast_index_from_parquet` and :mod:`_impl_ingest_adapters`
  are the in-process seams for the Parquet builder and the multi-format
  adapters (plaintext, csv, jsonl, hf, prealigned-*).
* :mod:`_impl_build_word_faiss_from_index` exposes the word-FAISS post-step
  (thesaurus) as an importable function for the import-job service.
* :mod:`build_fast_index_from_parquet`, :mod:`build_fast_index_from_vrt`,
  :mod:`ingest_adapters` are stable ``python -m`` launchers.
"""

from __future__ import annotations

__all__ = [
    "build_fast_index_from_parquet",
    "build_fast_index_from_vrt",
    "ingest_adapters",
]
