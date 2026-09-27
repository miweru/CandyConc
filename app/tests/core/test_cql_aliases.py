from candyconc.core.cql_engine import normalize_cql_aliases


def test_normalize_ner_alias_in_first_and_subsequent_token_conditions():
    query = '[ner="PERSON"] [word="Berlin" & ner~"ORG.*"]'

    assert normalize_cql_aliases(query) == '[ent="PERSON"] [word="Berlin" & ent~"ORG.*"]'


def test_normalize_ner_alias_for_set_conditions_case_insensitively():
    query = '[word="Berlin" & NER in {"PERSON", "ORG"}]'

    assert normalize_cql_aliases(query) == '[word="Berlin" & ent in {"PERSON", "ORG"}]'
