import pytest

from csvq import QueryError, query

DATA = """name,age,city,zip,score
Alice,34,Seoul,007,1.50
bob,28,Busan,12345,
Carol,,Seoul,04524,3
Dave,45,,54321,2.0
Eve,28,Incheon,99999,-1
"""


def names(q, data=DATA):
    return [r["name"] for r in query(data, q)]


def test_select_star_original_text():
    rows = query(DATA, "SELECT *")
    assert len(rows) == 5
    assert rows[0] == {"name": "Alice", "age": "34", "city": "Seoul", "zip": "007", "score": "1.50"}
    assert list(rows[0]) == ["name", "age", "city", "zip", "score"]
    assert rows[2]["age"] == "" and rows[3]["city"] == ""


def test_select_order_of_keys():
    rows = query(DATA, "select age, name where name = 'Eve'")
    assert rows == [{"age": "28", "name": "Eve"}] and list(rows[0]) == ["age", "name"]


def test_numeric_comparison_skips_null():
    assert names("select name where age > 30") == ["Alice", "Dave"]


def test_not_equal_is_unknown_for_null():
    assert names("select name where age != 28") == ["Alice", "Dave"]
    assert names("select name where age <> 28") == ["Alice", "Dave"]


def test_not_unknown_is_unknown():
    assert names("select name where not age = 28") == ["Alice", "Dave"]


def test_or_with_unknown():
    assert names("select name where age = 28 or city = 'Seoul'") == ["Alice", "bob", "Carol", "Eve"]


def test_and_with_unknown():
    assert names("select name where age > 30 and city = 'Seoul'") == ["Alice"]


def test_not_over_compound_three_valued():
    assert names("select name where not (age > 30 and city = 'Seoul')") == ["bob", "Eve"]


def test_precedence_not_and_or():
    # NOT > AND > OR : (city = 'Busan') OR ((age > 40) AND (NOT name = 'x'))
    assert names("select name where city = 'Busan' or age > 40 and not name = 'x'") == ["bob", "Dave"]


def test_order_desc_nulls_last_and_stable():
    assert names("select name order by age desc") == ["Dave", "Alice", "bob", "Eve", "Carol"]


def test_order_asc_nulls_last():
    assert names("select name order by age asc") == ["bob", "Eve", "Alice", "Dave", "Carol"]
    assert names("select name order by age") == ["bob", "Eve", "Alice", "Dave", "Carol"]


def test_order_numeric_values_kept_as_text():
    rows = query(DATA, "select name, score order by score desc")
    assert [(r["name"], r["score"]) for r in rows] == [
        ("Carol", "3"), ("Dave", "2.0"), ("Alice", "1.50"), ("Eve", "-1"), ("bob", "")]


def test_numeric_equality_by_value():
    assert names("select name where score = 2") == ["Dave"]
    assert names("select name where score >= 1.5") == ["Alice", "Carol", "Dave"]
    assert names("select name where score < 0") == ["Eve"]


def test_leading_zero_makes_text_column():
    with pytest.raises(QueryError):
        query(DATA, "select name where zip = 7")
    assert names("select name where zip = '007'") == ["Alice"]
    assert names("select name where zip < '1'") == ["Alice", "Carol"]


def test_type_mismatch_number_column_vs_string():
    with pytest.raises(QueryError):
        query(DATA, "select name where age = '28'")


def test_text_is_case_sensitive_code_point():
    assert names("select name order by name") == ["Alice", "Carol", "Dave", "Eve", "bob"]
    assert names("select name where name > 'B'") == ["bob", "Carol", "Dave", "Eve"]
    assert names("select name where name = 'alice'") == []


def test_order_by_column_not_selected():
    assert names("select name order by score") == ["Eve", "Alice", "Dave", "Carol", "bob"]


def test_multi_key_order():
    assert names("select name order by city, age desc") == ["bob", "Eve", "Alice", "Carol", "Dave"]


def test_limit():
    assert names("select name order by age limit 2") == ["bob", "Eve"]
    assert query(DATA, "select name limit 0") == []
    for bad in ("select name limit -1", "select name limit 1.5", "select name limit x"):
        with pytest.raises(QueryError):
            query(DATA, bad)


def test_keywords_case_insensitive_columns_not():
    assert names("SeLeCt name WhErE age > 40 OrDeR bY age DeSc LiMiT 5") == ["Dave"]
    with pytest.raises(QueryError):
        query(DATA, "select Name")


def test_quoted_identifiers_and_keyword_column():
    data = '"unit price",order,item\n1.5,1,a\n2,2,b\n'
    assert query(data, 'select item, "unit price" where "order" = 2') == [{"item": "b", "unit price": "2"}]
    assert query('"say ""hi""",x\nyes,1\n', 'select "say ""hi"""') == [{'say "hi"': "yes"}]
    with pytest.raises(QueryError):
        query(data, "select order")


def test_string_literal_escape():
    data = "name\nO'Brien\nOBrien\n"
    assert query(data, "select name where name = 'O''Brien'") == [{"name": "O'Brien"}]


def test_csv_quoting():
    data = 'name,note\nA,"x, y"\nB,"line1\nline2"\n'
    assert [r["note"] for r in query(data, "select note")] == ["x, y", "line1\nline2"]


def test_short_row_is_null_long_row_error():
    assert query("a,b\n1\n", "select *") == [{"a": "1", "b": ""}]
    assert query("a,b\n1\n2,5\n", "select a where b > 1") == [{"a": "2"}]
    with pytest.raises(QueryError):
        query("a,b\n1,2,3\n", "select *")


def test_all_empty_column_compares_with_anything():
    data = "a,b\n1,\n2,\n"
    assert query(data, "select a where b = 1") == []
    assert query(data, "select a where b = 'x'") == []
    assert query(data, "select a where not b = 'x'") == []


@pytest.mark.parametrize("data", ["", "a,a\n1,2\n"])
def test_bad_header(data):
    with pytest.raises(QueryError):
        query(data, "select *")


@pytest.mark.parametrize("q", [
    "select", "select name where", "select name order age", "select name limit 2 where age > 1",
    "select name where age >", "select name where 5 = age", "select name foo", "select nope",
    "select name where nope = 1", "select name order by nope", "select name where (age > 1",
    "select name where age > 1 and", "select name,", "name select", "select name where age = \"28\"",
])
def test_syntax_and_name_errors(q):
    with pytest.raises(QueryError):
        query(DATA, q)


def test_query_error_is_value_error():
    assert issubclass(QueryError, ValueError)
