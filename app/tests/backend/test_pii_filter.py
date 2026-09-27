from candyconc.services.backend import pii_filter


def test_mask_pii_disabled_passthrough(monkeypatch) -> None:
    monkeypatch.setattr(pii_filter, "get_config", lambda *_args, **_kwargs: "0")
    assert pii_filter.mask_pii("Alice Example") == "Alice Example"


def test_mask_pii_enabled_requires_index(monkeypatch) -> None:
    monkeypatch.setattr(pii_filter, "get_config", lambda *_args, **_kwargs: "1")
    try:
        pii_filter.mask_pii("Alice Example")
    except RuntimeError as exc:
        assert "PII Filter erfordert Index" in str(exc)
    else:
        raise AssertionError("PII filter should require index data when enabled")


def test_mask_free_text_pii_disabled_passthrough(monkeypatch) -> None:
    monkeypatch.setattr(pii_filter, "get_config", lambda *_args, **_kwargs: "0")
    text = "Kontakt: max@example.org, +49 30 123456."
    assert pii_filter.mask_free_text_pii(text) == text


def test_mask_free_text_pii_masks_obvious_identifiers(monkeypatch) -> None:
    monkeypatch.setattr(pii_filter, "get_config", lambda *_args, **_kwargs: "1")
    text = "Kontakt max@example.org, Telefon +49 30 123456, IBAN DE89370400440532013000."
    masked = pii_filter.mask_free_text_pii(text)
    assert "max@example.org" not in masked
    assert "+49 30 123456" not in masked
    assert "DE89370400440532013000" not in masked
    assert "<EMAIL>" in masked
    assert "<PHONE>" in masked
    assert "<IBAN>" in masked


def test_copilot_llm_bound_messages_apply_free_text_mask(monkeypatch) -> None:
    from candyconc.services.backend.routes import copilot

    monkeypatch.setattr(pii_filter, "get_config", lambda *_args, **_kwargs: "1")
    history, question = copilot._mask_llm_bound_messages(
        [{"role": "user", "content": "Mail max@example.org"}],
        "Ruf +49 30 123456 an",
    )
    assert history[0]["content"] == "Mail <EMAIL>"
    assert question == "Ruf <PHONE> an"


def test_copilot_ui_context_masks_free_text_and_omits_literal_kwic_preview(monkeypatch) -> None:
    from candyconc.services.backend.routes import copilot

    monkeypatch.setattr(pii_filter, "get_config", lambda *_args, **_kwargs: "1")
    context = copilot._mask_llm_bound_ui_context(
        {
            # A search expression stays as written (query strings are exempt,
            # see test_copilot_ui_context_keeps_query_strings_and_filter_values).
            "current_query": "max@example.org",
            "task_goal": "Mail max@example.org",
            "kwic": {
                "resultSet": {"rows": 1},
                "preview": [{
                    "rowId": "row-0",
                    "left": "Mail max@example.org",
                    "match": "Alice Beispiel",
                    "right": "Telefon +49 30 123456",
                }],
            },
        }
    )

    assert context["current_query"] == "max@example.org"
    assert context["task_goal"] == "Mail <EMAIL>"
    assert context["kwic"]["preview"] == []
    assert context["kwic"]["preview_omitted_for_privacy"] == 1


# The phone rule masked every run of digit groups: years, date ranges,
# numbers with thousands dots and the numbers of a within() clause became
# <PHONE> before the question reached recipe choice, tool choice and model.
KEPT_AS_WRITTEN = [
    "Compare 2019 2020 2021 frequencies",
    "Between 2020-01-15 and 2021-03-01",
    "How often in docs 12.345.678?",
    '[word="x"] within 10 20 30',
    "Wie oft steht Freiheit in den 403284 Token?",
    "Verlauf 1945-2006 nach Dekaden",
    "Vergleiche 1949 1950 1951 und 15.01.2020",
    "Zwischen 10.000 und 250.000 Treffern",
]

MASKED_PHONES = [
    "+49 30 12345678",
    "030/1234567",
    "(030) 123 4567",
    "+1 202-555-0143",
    "202-555-0143",
    "(202) 555-0143",
    "0151 12345678",
    "+49 (0)30 1234567",
    "+4930123456",
]


def test_mask_free_text_pii_keeps_years_dates_numbers_and_queries(monkeypatch) -> None:
    monkeypatch.setattr(pii_filter, "get_config", lambda *_args, **_kwargs: "1")
    for text in KEPT_AS_WRITTEN:
        assert pii_filter.mask_free_text_pii(text) == text


def test_mask_free_text_pii_still_masks_phone_numbers(monkeypatch) -> None:
    monkeypatch.setattr(pii_filter, "get_config", lambda *_args, **_kwargs: "1")
    for number in MASKED_PHONES:
        masked = pii_filter.mask_free_text_pii(f"Ruf {number} an.")
        assert masked == "Ruf <PHONE> an.", (number, masked)


def test_copilot_ui_context_keeps_query_strings_and_filter_values(monkeypatch) -> None:
    """Query strings and filter values search the corpus, they are not free text.

    The corpus text they select reaches the model in the tool results anyway,
    and a masked query is a different query than the one the interface ran.
    """
    from candyconc.services.backend.routes import copilot

    monkeypatch.setattr(pii_filter, "get_config", lambda *_args, **_kwargs: "1")
    context = copilot._mask_llm_bound_ui_context(
        {
            "corpus": {"corpusId": "sotu_en", "subcorpus": {"filters": [
                {"field": "date", "op": "between", "value": ["2020-01-15", "2021-03-01"]},
                {"field": "contact", "op": "eq", "value": "max@example.org"},
            ]}},
            "query": {"mode": "cqlf", "cqlf": '[word="max@example.org"] within 10 20 30'},
            "task_goal": "Mail an max@example.org",
        }
    )
    assert context["query"]["cqlf"] == '[word="max@example.org"] within 10 20 30'
    filters = context["corpus"]["subcorpus"]["filters"]
    assert filters[0]["value"] == ["2020-01-15", "2021-03-01"]
    assert filters[1]["value"] == "max@example.org"
    assert context["task_goal"] == "Mail an <EMAIL>"
