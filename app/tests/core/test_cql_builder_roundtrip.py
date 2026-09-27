from cqlhpc import parse_cql, to_cql


def test_to_cql_preserves_grouping_inside_sequences() -> None:
    ast = parse_cql('[word="A"] ([word="B"] [word="C"] | [word="D"]) [word="E"]')

    assert to_cql(ast) == '[word="A"] ([word="B"] [word="C"] | [word="D"]) [word="E"]'


def test_to_cql_preserves_meta_precedence() -> None:
    ast = parse_cql('where(source="mlsum" & (genre="news" | year>=2024), [word="A"])')

    assert to_cql(ast) == 'where(source="mlsum" & (genre="news" | year>=2024), [word="A"])'
