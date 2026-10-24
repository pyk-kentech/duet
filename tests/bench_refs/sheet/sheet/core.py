"""Sheet: 셀 저장, 재계산(의존 그래프·순환), 복사·이동·행열 삽입/삭제."""

from __future__ import annotations

from dataclasses import replace

from sheet.evaluate import Evaluator
from sheet.formula import (ErrLit, Func, Range, Ref, is_ref_arg, make_range, map_refs, parse_formula, render,
                           shift_ref, unparen, walk)
from sheet.refs import parse_area, parse_cell, parse_col
from sheet.values import CYCLE, EMPTY, MAX_COL, MAX_ROW, NUM_TEXT_RE, finite, out

_REF_ERR = ErrLit("#REF!")


class _Cell:
    __slots__ = ("raw", "value", "ast")

    def __init__(self, raw: str, value=None, ast=None) -> None:
        self.raw = raw        # formula() 가 돌려주는 글자
        self.value = value    # 상수 값 (수식이면 None)
        self.ast = ast        # 수식 구문 트리 (상수면 None)


def _make_cell(text: str) -> _Cell:
    if text.startswith("="):
        ast = parse_formula(text[1:])
        return _Cell("=" + render(ast), ast=ast)
    if text.startswith("'"):
        return _Cell(text, value=text[1:])
    if text.lower() in ("true", "false"):
        return _Cell(text, value=text.lower() == "true")
    if NUM_TEXT_RE.fullmatch(text):
        return _Cell(text, value=finite(float(text)))
    return _Cell(text, value=text)


def _formula_cell(ast) -> _Cell:
    return _Cell("=" + render(ast), ast=ast)


class Sheet:
    def __init__(self) -> None:
        self._cells: dict[tuple[int, int], _Cell] = {}
        self._values: dict[tuple[int, int], object] | None = None

    # ------------------------------------------------------------ 기본
    def set(self, ref: str, text: str) -> None:
        pos = parse_cell(ref)
        if not isinstance(text, str):
            raise TypeError("text 는 문자열이어야 한다")
        if text == "":
            self._cells.pop(pos, None)
        else:
            self._cells[pos] = _make_cell(text)
        self._values = None

    def get(self, ref: str):
        pos = parse_cell(ref)
        cell = self._cells.get(pos)
        if cell is None:
            return None
        if cell.ast is None:
            return out(cell.value)
        if self._values is None:
            self._recalc()
        return out(self._values[pos])

    def formula(self, ref: str) -> str:
        cell = self._cells.get(parse_cell(ref))
        return "" if cell is None else cell.raw

    # ------------------------------------------------------------ 계산기가 쓰는 것
    def _value_at(self, c: int, r: int):
        cell = self._cells.get((c, r))
        if cell is None:
            return EMPTY
        if cell.ast is None:
            return cell.value
        return self._values[(c, r)]

    def _iter_rect(self, c1: int, r1: int, c2: int, r2: int):
        area = (c2 - c1 + 1) * (r2 - r1 + 1)
        cells = self._cells
        if area <= 2 * len(cells) + 64:
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    if (c, r) in cells:
                        yield c, r, self._value_at(c, r)
        else:
            pts = sorted((r, c) for (c, r) in cells if c1 <= c <= c2 and r1 <= r <= r2)
            for r, c in pts:
                yield c, r, self._value_at(c, r)

    # ------------------------------------------------------------ 재계산
    def _rects(self, ast):
        """수식이 의존하는 영역들 (적힌 모든 참조 + SUMIF 의 크기 맞춘 영역)."""
        rects = []
        for n in walk(ast):
            t = type(n)
            if t is Ref:
                rects.append((n.col, n.row, n.col, n.row))
            elif t is Range:
                rects.append((n.a.col, n.a.row, n.b.col, n.b.row))
            elif t is Func and n.name == "SUMIF" and len(n.args) == 3 \
                    and is_ref_arg(n.args[0]) and is_ref_arg(n.args[2]):
                a, s = unparen(n.args[0]), unparen(n.args[2])
                a1 = a if type(a) is Ref else a.a
                a2 = a if type(a) is Ref else a.b
                s1 = s if type(s) is Ref else s.a
                w, h = a2.col - a1.col, a2.row - a1.row
                rects.append((s1.col, s1.row, min(s1.col + w, MAX_COL), min(s1.row + h, MAX_ROW)))
        return rects

    def _recalc(self) -> None:
        formulas = [p for p, c in self._cells.items() if c.ast is not None]
        fset = set(formulas)
        deps: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for p in formulas:
            ds: set[tuple[int, int]] = set()
            for c1, r1, c2, r2 in self._rects(self._cells[p].ast):
                area = (c2 - c1 + 1) * (r2 - r1 + 1)
                if area <= len(fset):
                    for r in range(r1, r2 + 1):
                        for c in range(c1, c2 + 1):
                            if (c, r) in fset:
                                ds.add((c, r))
                else:
                    for q in formulas:
                        if c1 <= q[0] <= c2 and r1 <= q[1] <= r2:
                            ds.add(q)
            deps[p] = sorted(ds)
        self._values = {}
        ev = Evaluator(self)
        for comp in _sccs(formulas, deps):
            if len(comp) > 1 or comp[0] in deps[comp[0]]:
                for p in comp:
                    self._values[p] = CYCLE
            else:
                p = comp[0]
                self._values[p] = ev.result(self._cells[p].ast)

    # ------------------------------------------------------------ 복사·이동
    def copy(self, src: str, dst: str) -> None:
        c1, r1, c2, r2 = parse_area(src)
        dc0, dr0 = parse_cell(dst)
        dc, dr = dc0 - c1, dr0 - r1
        if c2 + dc > MAX_COL or r2 + dr > MAX_ROW:
            raise ValueError("복사할 자리가 시트를 벗어난다")
        snap = {p: cell for p, cell in self._cells.items() if c1 <= p[0] <= c2 and r1 <= p[1] <= r2}

        def f_ref(r: Ref):
            s = shift_ref(r, dc, dr, True)
            return _REF_ERR if s is None else s

        def f_range(g: Range):
            a, b = shift_ref(g.a, dc, dr, True), shift_ref(g.b, dc, dr, True)
            if a is None or b is None:
                return _REF_ERR
            return make_range(a, b)

        self._clear_rect(c1 + dc, r1 + dr, c2 + dc, r2 + dr)
        for (c, r), cell in snap.items():
            if cell.ast is not None:
                cell = _formula_cell(map_refs(cell.ast, f_ref, f_range))
            self._cells[(c + dc, r + dr)] = cell
        self._values = None

    def move(self, src: str, dst: str) -> None:
        c1, r1, c2, r2 = parse_area(src)
        dc0, dr0 = parse_cell(dst)
        dc, dr = dc0 - c1, dr0 - r1
        if c2 + dc > MAX_COL or r2 + dr > MAX_ROW:
            raise ValueError("옮길 자리가 시트를 벗어난다")
        d1, e1, d2, e2 = c1 + dc, r1 + dr, c2 + dc, r2 + dr

        def in_s(c, r):
            return c1 <= c <= c2 and r1 <= r <= r2

        def f_ref(r: Ref):
            if in_s(r.col, r.row):
                return replace(r, col=r.col + dc, row=r.row + dr)
            if d1 <= r.col <= d2 and e1 <= r.row <= e2:
                return _REF_ERR
            return r

        def f_range(g: Range):
            if in_s(g.a.col, g.a.row) and in_s(g.b.col, g.b.row):
                return Range(replace(g.a, col=g.a.col + dc, row=g.a.row + dr),
                             replace(g.b, col=g.b.col + dc, row=g.b.row + dr))
            return g

        self._rewrite(f_ref, f_range)
        snap = {p: cell for p, cell in self._cells.items() if in_s(*p)}
        self._clear_rect(c1, r1, c2, r2)
        self._clear_rect(d1, e1, d2, e2)
        for (c, r), cell in snap.items():
            self._cells[(c + dc, r + dr)] = cell
        self._values = None

    def _clear_rect(self, c1, r1, c2, r2) -> None:
        for p in [p for p in self._cells if c1 <= p[0] <= c2 and r1 <= p[1] <= r2]:
            del self._cells[p]

    def _rewrite(self, f_ref, f_range) -> None:
        for p, cell in list(self._cells.items()):
            if cell.ast is not None:
                self._cells[p] = _formula_cell(map_refs(cell.ast, f_ref, f_range))

    # ------------------------------------------------------------ 행·열 삽입/삭제
    def insert_rows(self, row: int, count: int = 1) -> None:
        self._insert(1, self._check_index(row, MAX_ROW), self._check_count(count))

    def insert_cols(self, col: str, count: int = 1) -> None:
        self._insert(0, parse_col(col), self._check_count(count))

    def delete_rows(self, row: int, count: int = 1) -> None:
        row, count = self._check_index(row, MAX_ROW), self._check_count(count)
        if row + count - 1 > MAX_ROW:
            raise ValueError("시트 밖의 행은 지울 수 없다")
        self._delete(1, row, count)

    def delete_cols(self, col: str, count: int = 1) -> None:
        col, count = parse_col(col), self._check_count(count)
        if col + count - 1 > MAX_COL:
            raise ValueError("시트 밖의 열은 지울 수 없다")
        self._delete(0, col, count)

    @staticmethod
    def _check_index(i, limit: int) -> int:
        if isinstance(i, bool) or not isinstance(i, int) or not 1 <= i <= limit:
            raise ValueError(f"잘못된 위치: {i!r}")
        return i

    @staticmethod
    def _check_count(n) -> int:
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError(f"잘못된 개수: {n!r}")
        return n

    def _insert(self, axis: int, at: int, n: int) -> None:
        limit = MAX_ROW if axis else MAX_COL
        if any(p[axis] >= at and p[axis] + n > limit for p in self._cells):
            raise ValueError("삽입하면 비어 있지 않은 셀이 시트 밖으로 밀려난다")

        def get(r: Ref) -> int:
            return r.row if axis else r.col

        def put(r: Ref, v: int) -> Ref:
            return replace(r, row=v) if axis else replace(r, col=v)

        def f_ref(r: Ref):
            v = get(r)
            if v >= at:
                v += n
                if v > limit:
                    return _REF_ERR
            return put(r, v)

        def f_range(g: Range):
            a, b = get(g.a), get(g.b)
            if at <= a:
                a, b = a + n, b + n
            elif at <= b:
                b += n
            if a > limit:
                return _REF_ERR
            return Range(put(g.a, a), put(g.b, min(b, limit)))

        self._rewrite(f_ref, f_range)
        self._cells = {self._shift_pos(p, axis, at, n): cell for p, cell in self._cells.items()}
        self._values = None

    def _delete(self, axis: int, at: int, n: int) -> None:
        end = at + n - 1

        def get(r: Ref) -> int:
            return r.row if axis else r.col

        def put(r: Ref, v: int) -> Ref:
            return replace(r, row=v) if axis else replace(r, col=v)

        def m(v: int) -> int:
            return v if v < at else v - n

        def f_ref(r: Ref):
            v = get(r)
            if at <= v <= end:
                return _REF_ERR
            return put(r, m(v))

        def f_range(g: Range):
            a, b = get(g.a), get(g.b)
            if a >= at and b <= end:
                return _REF_ERR
            na = end + 1 if at <= a <= end else a
            nb = at - 1 if at <= b <= end else b
            return Range(put(g.a, m(na)), put(g.b, m(nb)))

        self._rewrite(f_ref, f_range)
        cells = {}
        for p, cell in self._cells.items():
            v = p[axis]
            if at <= v <= end:
                continue
            cells[self._shift_pos(p, axis, end + 1, -n)] = cell
        self._cells = cells
        self._values = None

    @staticmethod
    def _shift_pos(p, axis: int, at: int, n: int):
        if p[axis] < at:
            return p
        return (p[0], p[1] + n) if axis else (p[0] + n, p[1])


def _sccs(nodes, deps):
    """반복형 Tarjan. 의존하는 쪽이 나중에 나오도록 강한 연결 요소를 돌려준다."""
    index: dict = {}
    low: dict = {}
    on: set = set()
    stack: list = []
    result: list = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        work = [(root, iter(deps[root]))]
        while work:
            v, it = work[-1]
            pushed = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(deps[w])))
                    pushed = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if pushed:
                continue
            work.pop()
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                result.append(comp)
    return result
