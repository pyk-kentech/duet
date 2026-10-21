import pytest

from findex import DocumentNotFound, Index


@pytest.fixture
def idx():
    i = Index()
    i.add("Apple pie recipe", body="Bake the apples with sugar and butter.", tags=["food", "baking"], date="2024-01-10")
    i.add("Banana bread", body="Ripe bananas make the best bread. Apple optional.", tags=["food"], date="2024-02-20")
    i.add("Python tips", body="Use list comprehensions and generators.", tags=["python", "programming"],
          date="2023-12-01")
    i.add("Gardening notes", body="Apple trees need sun.", tags=["garden"])
    return i


def test_add_returns_increasing_ids(idx):
    assert idx.add("New") == 5
    assert idx.get(5).title == "New"
    assert idx.ids() == [1, 2, 3, 4, 5]


def test_add_validates():
    i = Index()
    with pytest.raises(ValueError):
        i.add("   ")
    with pytest.raises(ValueError):
        i.add("x", date="2024/01/01")
    assert len(i) == 0


def test_tags_cleaned():
    i = Index()
    d = i.add("t", tags=[" Food ", "", "food", "Baking"])
    assert i.get(d).tags == ("Food", "Baking")


def test_simple_search(idx):
    res = idx.search("apple")
    assert res.total == 3
    assert set(res.ids()) == {1, 2, 4}
    assert res.hits[0].doc_id == 1 and res.hits[0].title == "Apple pie recipe"
    assert res.hits[0].score > res.hits[1].score > 0


def test_title_boost(idx):
    # 'apple' is in the title of 1 and only in bodies of 2 and 4
    assert idx.search("apple").ids()[0] == 1


def test_implicit_and_or_not(idx):
    assert idx.search("apple bread").ids() == [2]
    assert set(idx.search("python OR garden").ids()) == {3, 4}
    assert set(idx.search("apple NOT bread").ids()) == {1, 4}


def test_phrase(idx):
    assert idx.search('"apple trees"').ids() == [4]
    assert idx.search('"trees apple"').ids() == []


def test_prefix(idx):
    assert set(idx.search("bana*").ids()) == {2}
    assert set(idx.search("gen*").ids()) == {3}


def test_field_query(idx):
    assert idx.search("title:apple").ids() == [1]
    assert set(idx.search("body:apple").ids()) == {1, 2, 4}


def test_tag_filter(idx):
    assert set(idx.search("tag:food").ids()) == {1, 2}
    assert idx.search("tag:FOOD apple").ids() == [1, 2]


def test_date_range(idx):
    assert set(idx.search("date:2024-01-01..2024-12-31").ids()) == {1, 2}
    assert idx.search("date:..2023-12-31").ids() == [3]


def test_delete(idx):
    idx.delete(2)
    assert 2 not in idx and len(idx) == 3
    assert idx.search("bread").total == 0
    with pytest.raises(DocumentNotFound):
        idx.get(2)


def test_update_title(idx):
    idx.update(3, title="Python tricks")
    assert idx.get(3).title == "Python tricks"
    assert idx.get(3).body == "Use list comprehensions and generators."
    assert idx.search("tricks").ids() == [3]


def test_pagination(idx):
    page1 = idx.search("apple", per_page=2)
    page2 = idx.search("apple", per_page=2, page=2)
    assert page1.total == page2.total == 3 and page1.pages == 2
    assert len(page1.hits) == 2 and len(page2.hits) == 1
    assert set(page1.ids() + page2.ids()) == {1, 2, 4}


def test_sort_by_date(idx):
    assert idx.search("apple", sort="date").ids() == [2, 1, 4]


def test_count_and_stats(idx):
    assert idx.count("apple") == 3
    st = idx.stats()
    assert st["documents"] == 4 and st["next_id"] == 5 and st["terms"] > 10


def test_correct_and_reindex(idx):
    assert idx.correct("bananna bred") == "banana bread"
    assert idx.correct("apple") is None
    assert idx.reindex() == 4
    assert idx.search("apple").total == 3


def test_merge_and_check(idx):
    other = Index()
    other.add("Kiwi", body="green fruit")
    other.add("Mango", body="sweet fruit")
    other.delete(1)
    assert idx.merge(other) == [5]
    assert idx.get(5).title == "Mango" and other.ids() == [2]
    assert idx.check() == []
