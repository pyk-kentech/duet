import pytest

from intervals import insert, merge, subtract, total_length


@pytest.mark.parametrize("items,want", [
    ([], []),
    ([(1, 3)], [(1, 3)]),
    ([(5, 8), (1, 3)], [(1, 3), (5, 8)]),
    ([(1, 4), (2, 6)], [(1, 6)]),
    ([(1, 10), (2, 3), (4, 5)], [(1, 10)]),
    ([(1, 3), (3, 5)], [(1, 5)]),                       # 맞닿으면 합침
    ([(1, 3), (4, 5)], [(1, 3), (4, 5)]),               # 정수 사이가 비면 따로
    ([(2, 2), (5, 7)], [(5, 7)]),                       # 길이 0 버림
    ([(3, 3)], []),
    ([(1, 2), (1, 2), (1, 2)], [(1, 2)]),
    ([(-5, -1), (-2, 3)], [(-5, 3)]),
    ([[7, 9], [1, 2]], [(1, 2), (7, 9)]),               # 리스트 쌍도 받음
    ([(1, 5), (5, 5), (5, 6)], [(1, 6)]),
])
def test_merge(items, want):
    got = merge(items)
    assert got == want
    assert all(type(x) is tuple for x in got)


def test_merge_does_not_mutate():
    items = [(5, 8), (1, 3), (2, 6)]
    copy = list(items)
    merge(items)
    assert items == copy


@pytest.mark.parametrize("bad", [[(3, 1)], [(1, 2), (5, 4)]])
def test_invalid(bad):
    with pytest.raises(ValueError):
        merge(bad)
    with pytest.raises(ValueError):
        total_length(bad)


@pytest.mark.parametrize("items,new,want", [
    ([], (1, 2), [(1, 2)]),
    ([(1, 3), (6, 9)], (2, 5), [(1, 5), (6, 9)]),
    ([(1, 2), (3, 5), (6, 7), (8, 10), (12, 16)], (4, 8), [(1, 2), (3, 10), (12, 16)]),
    ([(1, 3)], (3, 4), [(1, 4)]),
    ([(1, 3)], (5, 5), [(1, 3)]),
    ([(5, 6)], (1, 2), [(1, 2), (5, 6)]),
])
def test_insert(items, new, want):
    assert insert(items, new) == want


def test_insert_invalid():
    with pytest.raises(ValueError):
        insert([(1, 2)], (5, 3))


@pytest.mark.parametrize("items,cut,want", [
    ([(0, 10)], (3, 5), [(0, 3), (5, 10)]),
    ([(0, 10)], (0, 10), []),
    ([(0, 10)], (-5, 20), []),
    ([(0, 10)], (10, 12), [(0, 10)]),                   # 반열린: 10 은 원래 없음
    ([(0, 10)], (0, 3), [(3, 10)]),
    ([(0, 10)], (7, 10), [(0, 7)]),
    ([(0, 3), (5, 9), (12, 15)], (2, 13), [(0, 2), (13, 15)]),
    ([(5, 9), (0, 3)], (3, 5), [(0, 3), (5, 9)]),       # 병합 전 입력
    ([], (1, 2), []),
    ([(0, 10)], (4, 4), [(0, 10)]),
])
def test_subtract(items, cut, want):
    assert subtract(items, cut) == want


@pytest.mark.parametrize("items,want", [([], 0), ([(1, 3)], 2), ([(1, 3), (2, 5)], 4),
                                        ([(1, 3), (3, 5), (10, 11)], 5), ([(2, 2)], 0)])
def test_total_length(items, want):
    assert total_length(items) == want
