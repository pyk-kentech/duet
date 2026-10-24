from findex import Index


def make():
    i = Index()
    i.add("a", tags=["python", "web"])
    i.add("b", tags=["Python"])
    i.add("c", tags=["rust", "web"])
    i.add("d", tags=["go"])
    return i


def test_counts_and_order():
    assert make().facets() == [("python", 2), ("web", 2), ("go", 1), ("rust", 1)]


def test_limit():
    assert make().facets(limit=2) == [("python", 2), ("web", 2)]


def test_facets_for_query():
    i = make()
    assert i.facets("tag:web") == [("web", 2), ("python", 1), ("rust", 1)]
