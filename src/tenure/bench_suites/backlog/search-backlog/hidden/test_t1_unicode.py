"""FX-101: 하나의 정규형 (NFKD → Mn 제거 → casefold → NFC) 이 모든 경로에 쓰인다."""

import os
import subprocess
import sys

from findex import Index


def ids(idx, q):
    return sorted(idx.search(q, per_page=100).ids())


def cli(tmp_path, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "findex", "--index", str(tmp_path / "i.json"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(tmp_path))


def test_accented_and_plain_find_each_other():
    i = Index()
    a = i.add("Café culture")
    b = i.add("cafe racer")
    assert ids(i, "cafe") == [a, b]
    assert ids(i, "café") == [a, b]
    assert ids(i, "CAFÉ") == [a, b]


def test_various_foldings():
    i = Index()
    a = i.add("Ångström units", body="a naïve approach")
    b = i.add("Die Straße", body="ﬁle system")
    c = i.add("ＰＹＴＨＯＮ guide")          # fullwidth PYTHON
    assert ids(i, "angstrom") == [a]
    assert ids(i, "naive") == [a]
    assert ids(i, "STRASSE") == [b]
    assert ids(i, "file") == [b]
    assert ids(i, "python") == [c]


def test_nfd_text_is_one_word():
    i = Index()
    a = i.add("Art", body="a naïve painter")
    assert ids(i, "naive") == [a]
    assert ids(i, "naïve") == [a]
    assert ids(i, '"naive painter"') == [a]
    assert ids(i, "nai") == []          # the combining mark does not split the word


def test_prefix_queries_fold():
    i = Index()
    a = i.add("Crème brûlée")
    b = i.add("Straße")
    assert ids(i, "crem*") == [a]
    assert ids(i, "CRÈM*") == [a]
    assert ids(i, "straß*") == [b]
    assert ids(i, "title:brul*") == [a]


def test_phrase_and_field_queries_fold():
    i = Index()
    a = i.add("Crème Brûlée recipe", body="Classic French dessert")
    i.add("creme only")
    assert ids(i, '"creme brulee"') == [a]
    assert ids(i, 'title:"CRÈME BRÛLÉE"') == [a]
    assert ids(i, "title:brulee") == [a]


def test_stopwords_compared_in_normal_form():
    i = Index(stopwords=["für"])
    a = i.add("fur coat")
    b = i.add("für Elise")
    assert ids(i, "coat") == [a]
    assert i.search("fur").total == 0           # 'fur' is a stopword too: stopword-only query
    assert ids(i, "elise") == [b]


def test_tag_filter_folds():
    i = Index()
    a = i.add("one", tags=["Café"])
    b = i.add("two", tags=["CAFE"])
    c = i.add("three", tags=["Crème Brûlée"])
    assert ids(i, "tag:cafe") == [a, b]
    assert ids(i, "tag:CAFÉ") == [a, b]
    assert ids(i, 'tag:"creme brulee"') == [c]
    d = i.add("t", tags=["Café", "cafe", "CAFÉ", "thé"])        # one document: duplicates removed
    assert i.get(d).tags == ("Café", "thé")


def test_facets_merge_and_keep_first_label():
    i = Index()
    i.add("a", tags=["Café"])
    i.add("b", tags=["cafe"])
    i.add("c", tags=["CAFE", "Thé"])
    assert i.facets() == [("Café", 3), ("Thé", 1)]
    i.delete(1)
    assert i.facets() == [("cafe", 2), ("Thé", 1)]
    assert i.facets("tag:the") == [("CAFE", 1), ("Thé", 1)]


def test_facets_tie_order_uses_normal_form():
    i = Index()
    i.add("a", tags=["Fig"])
    i.add("b", tags=["Éclair"])
    i.add("c", tags=["date"])
    assert i.facets() == [("date", 1), ("Éclair", 1), ("Fig", 1)]


def test_documents_stay_verbatim():
    i = Index()
    d = i.add("Crème Brûlée", body="Ångström naïve", tags=["Café"])
    assert ids(i, "creme") == [d]
    doc = i.get(d)
    assert (doc.title, doc.body, doc.tags) == ("Crème Brûlée", "Ångström naïve", ("Café",))
    assert i.documents()[0].title == "Crème Brûlée"


def test_highlight_keeps_original_spelling():
    i = Index()
    d = i.add("Crème brûlée recipe")
    assert i.highlight(d, "creme") == "[Crème] brûlée recipe"
    assert i.highlight(d, "BRULEE") == "Crème [brûlée] recipe"
    assert i.highlight(d, "crem*") == "[Crème] brûlée recipe"


def test_snippet_offsets_with_length_changing_folds():
    i = Index()
    d = i.add("x", body="Die Straße und das Café.")
    assert i.snippet(d, "strasse cafe") == "Die [Straße] und das [Café]."
    e = i.add("y", body="ﬁne ﬁle, then Ｏｋ done")
    assert i.snippet(e, "file ok") == "ﬁne [ﬁle], then [Ｏｋ] done"
    f = i.add("z", body="a naïve art")
    assert i.snippet(f, "naive") == "a [naïve] art"        # the whole NFD word


def test_hangul_unchanged_and_fullwidth_latin():
    i = Index()
    a = i.add("한국어 검색 엔진", tags=["한국"])
    b = i.add("ＫＯＲＥＡ travel")              # fullwidth KOREA
    assert ids(i, "한국어") == [a]
    assert ids(i, "한국*") == [a]
    assert ids(i, "tag:한국") == [a]
    assert ids(i, "korea") == [b]
    assert i.facets() == [("한국", 1)]
    assert i.highlight(a, "검색") == "한국어 [검색] 엔진"
    assert i.suggest("한국") == [("한국어", 1)]


def test_suggest_prefix_folds():
    i = Index()
    i.add("Café one")
    i.add("cafe two")
    i.add("cafeteria")
    assert i.suggest("CAFÉ") == [("cafe", 2), ("cafeteria", 1)]


def test_cli_accents(tmp_path):
    assert cli(tmp_path, "add", "Crème Brûlée", "--tag", "Café").returncode == 0
    cli(tmp_path, "add", "Other", "--tag", "cafe")
    r = cli(tmp_path, "search", "creme", "--snippets")
    assert r.stdout.splitlines()[0] == "검색 결과 1건"
    assert cli(tmp_path, "get", "1").stdout.splitlines()[1] == "title: Crème Brûlée"
    assert cli(tmp_path, "facets").stdout.splitlines() == ["Café\t2"]
