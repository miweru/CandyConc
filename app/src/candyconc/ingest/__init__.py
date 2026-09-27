"""Corpus import: the Fast Index builders.

Each module is runnable with ``python -m candyconc.ingest.<module>`` and exposes
``main(argv)``. ``candy import`` and the import jobs of the backend call them
in-process through :mod:`candyconc.builders`.

* :mod:`build_fast_index_from_parquet`: Parquet and generic row input, spaCy
  annotation, index writers.
* :mod:`ingest_adapters`: CSV, JSONL, plain text, Hugging Face datasets and the
  pre-aligned (paired) formats.
* :mod:`build_fast_index_from_vrt`: VRT and XML-like vertical text.
* :mod:`build_fast_index`: binary writers shared by the builders.
* :mod:`build_word_faiss_from_index`: word vectors for the thesaurus
  (needs the ``semantic`` extra).
* :mod:`cwb_decode_to_vrt`: converts ``cwb-decode -C`` output to VRT.
"""
