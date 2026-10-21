"""구문 트리 → 역추적 매처(연속 전달 방식).

매처: m(ctx, i, st, k) -> 결과 또는 None
  st = (caps, lastindex), caps 는 그룹마다 (시작, 끝) 두 칸의 튜플(그룹 1 이 0·1 칸).
  k(j, st) 는 나머지를 이어서 맞춰 보는 함수. 상태가 불변이라 역추적하면 저절로 되돌아간다.
반복의 빈 반복 규칙은 sre 와 같다: 최소 횟수를 넘는 반복이 아무것도 소비하지 않으면 그 뒤로 더 반복하지 않는다.
"""

from __future__ import annotations

import sys

from ._parser import INF

if sys.getrecursionlimit() < 20000:
    sys.setrecursionlimit(20000)

IGNORECASE = 2
MULTILINE = 8
DOTALL = 16


def _lower(ch: str) -> str:
    return ch.lower()[0]


def _isword(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


_CATS = {
    "d": str.isdecimal,
    "D": lambda c: not c.isdecimal(),
    "s": str.isspace,
    "S": lambda c: not c.isspace(),
    "w": _isword,
    "W": lambda c: not _isword(c),
}


class Ctx:
    __slots__ = ("s", "end")

    def __init__(self, s: str, end: int):
        self.s = s
        self.end = end


def _accept(j, st):
    return (j, st)


class Compiler:
    def __init__(self, flags: int):
        self.icase = bool(flags & IGNORECASE)
        self.multiline = bool(flags & MULTILINE)
        self.dotall = bool(flags & DOTALL)

    # ------------------------------------------------------------ 한 글자
    def unit_pred(self, node):
        """한 글자짜리 노드면 술어(ch -> bool), 아니면 None."""
        op = node[0]
        if op == "lit":
            c = node[1]
            if self.icase:
                lc = _lower(c)
                return lambda ch: _lower(ch) == lc
            return lambda ch: ch == c
        if op == "any":
            if self.dotall:
                return lambda ch: True
            return lambda ch: ch != "\n"
        if op == "set":
            return self.set_pred(node[1], node[2])
        if op == "group" and node[1] is None and len(node[2]) == 1:
            return self.unit_pred(node[2][0])
        return None

    def set_pred(self, negate: bool, items: list):
        icase = self.icase
        chars: set[str] = set()
        ranges: list[tuple[int, int]] = []
        cats = []
        for it in items:
            if it[0] == "lit":
                chars.add(_lower(it[1]) if icase else it[1])
            elif it[0] == "range":
                lo, hi = ord(it[1]), ord(it[2])
                if icase and hi - lo <= 0x10000:
                    chars.update(_lower(chr(x)) for x in range(lo, hi + 1))
                else:
                    ranges.append((lo, hi))
            else:
                cats.append(_CATS[it[1]])

        def pred(ch: str) -> bool:
            if icase:
                ch = _lower(ch)
            ok = ch in chars
            if not ok and ranges:
                o = ord(ch)
                for lo, hi in ranges:
                    if lo <= o <= hi:
                        ok = True
                        break
                if not ok and icase:
                    o = ord(ch.upper()[0])
                    for lo, hi in ranges:
                        if lo <= o <= hi:
                            ok = True
                            break
            if not ok:
                for f in cats:
                    if f(ch):
                        ok = True
                        break
            return ok != negate

        return pred

    # ------------------------------------------------------------ 순서열
    def seq(self, nodes: list):
        # 이어진 리터럴은 하나로 합친다(재귀 깊이를 줄인다)
        merged: list = []
        for n in nodes:
            if n[0] == "lit" and merged and merged[-1][0] == "litrun":
                merged[-1] = ("litrun", merged[-1][1] + n[1])
            elif n[0] == "lit":
                merged.append(("litrun", n[1]))
            else:
                merged.append(n)
        ms = [self.node(n) for n in merged]
        if not ms:
            return lambda ctx, i, st, k: k(i, st)
        m = ms[-1]
        for a in reversed(ms[:-1]):
            m = _chain(a, m)
        return m

    def node(self, node):
        op = node[0]
        if op == "litrun":
            return self.litrun(node[1])
        if op in ("any", "set"):
            pred = self.unit_pred(node)

            def m_unit(ctx, i, st, k, pred=pred):
                if i < ctx.end and pred(ctx.s[i]):
                    return k(i + 1, st)
                return None
            return m_unit
        if op == "at":
            return self.at(node[1])
        if op == "group":
            return self.group(node[1], node[2])
        if op == "alt":
            alts = [self.seq(a) for a in node[1]]

            def m_alt(ctx, i, st, k):
                for a in alts:
                    r = a(ctx, i, st, k)
                    if r is not None:
                        return r
                return None
            return m_alt
        if op == "repeat":
            return self.repeat(node[1], node[2], node[3], node[4])
        if op == "ref":
            return self.ref(node[1])
        if op == "look":
            return self.look(node[1], node[2], node[3], node[4])
        raise AssertionError(op)

    def litrun(self, text: str):
        n = len(text)
        if self.icase:
            low = [_lower(c) for c in text]

            def m_lit_i(ctx, i, st, k):
                j = i + n
                if j > ctx.end:
                    return None
                s = ctx.s
                for x in range(n):
                    if _lower(s[i + x]) != low[x]:
                        return None
                return k(j, st)
            return m_lit_i

        def m_lit(ctx, i, st, k):
            j = i + n
            if j > ctx.end or not ctx.s.startswith(text, i):
                return None
            return k(j, st)
        return m_lit

    def at(self, kind: str):
        ml = self.multiline
        if kind == "bol":
            if ml:
                def m(ctx, i, st, k):
                    if i == 0 or ctx.s[i - 1] == "\n":
                        return k(i, st)
                    return None
            else:
                def m(ctx, i, st, k):
                    return k(i, st) if i == 0 else None
        elif kind == "eol":
            if ml:
                def m(ctx, i, st, k):
                    if i == ctx.end or ctx.s[i] == "\n":
                        return k(i, st)
                    return None
            else:
                def m(ctx, i, st, k):
                    end = ctx.end
                    if i == end or (i == end - 1 and ctx.s[i] == "\n"):
                        return k(i, st)
                    return None
        elif kind == "bos":
            def m(ctx, i, st, k):
                return k(i, st) if i == 0 else None
        elif kind == "eos":
            def m(ctx, i, st, k):
                return k(i, st) if i == ctx.end else None
        elif kind in ("b", "B"):
            want = kind == "b"

            def m(ctx, i, st, k):
                end = ctx.end
                if end == 0:
                    return None
                s = ctx.s
                that = i > 0 and _isword(s[i - 1])
                this = i < end and _isword(s[i])
                if (this != that) == want:
                    return k(i, st)
                return None
        else:
            raise AssertionError(kind)
        return m

    def group(self, index, body_nodes):
        body = self.seq(body_nodes)
        if index is None:
            return body
        a = 2 * (index - 1)

        def m_group(ctx, i, st, k):
            caps, last = st
            c = list(caps)
            c[a] = i

            def close(j, st2):
                c2 = list(st2[0])
                c2[a + 1] = j
                return k(j, (tuple(c2), index))
            return body(ctx, i, (tuple(c), last), close)
        return m_group

    def repeat(self, mn: int, mx, greedy: bool, body_nodes: list):
        pred = self.unit_pred(body_nodes[0]) if len(body_nodes) == 1 else None
        if pred is not None:
            return _unit_repeat(pred, mn, mx, greedy)
        body = self.seq(body_nodes)

        def m_repeat(ctx, i, st, k):
            def until(j, st, count, last):
                if count < mn:
                    return body(ctx, j, st, lambda e, st2: until(e, st2, count + 1, last))
                if greedy:
                    if (mx is INF or count < mx) and j != last:
                        r = body(ctx, j, st, lambda e, st2: until(e, st2, count + 1, j))
                        if r is not None:
                            return r
                    return k(j, st)
                r = k(j, st)
                if r is not None:
                    return r
                if (mx is not INF and count >= mx) or j == last:
                    return None
                return body(ctx, j, st, lambda e, st2: until(e, st2, count + 1, j))
            return until(i, st, 0, None)
        return m_repeat

    def ref(self, index: int):
        a = 2 * (index - 1)
        icase = self.icase

        def m_ref(ctx, i, st, k):
            caps = st[0]
            p, e = caps[a], caps[a + 1]
            if p is None or e is None or e < p:
                return None
            n = e - p
            if i + n > ctx.end:
                return None
            s = ctx.s
            if icase:
                for x in range(n):
                    if _lower(s[i + x]) != _lower(s[p + x]):
                        return None
            elif s[i:i + n] != s[p:e]:
                return None
            return k(i + n, st)
        return m_ref

    def look(self, behind: bool, negate: bool, body_nodes: list, width: int):
        body = self.seq(body_nodes)

        def m_look(ctx, i, st, k):
            start = i - width if behind else i
            if start < 0:
                return k(i, st) if negate else None
            r = body(ctx, start, st, _accept)
            if negate:
                return None if r is not None else k(i, st)
            if r is None:
                return None
            return k(i, r[1])          # 전방·후방 탐색 안의 캡처는 남는다(되돌아 들어가지는 않는다)
        return m_look


def _chain(a, b):
    def m(ctx, i, st, k):
        return a(ctx, i, st, lambda j, st2: b(ctx, j, st2, k))
    return m


def _unit_repeat(pred, mn: int, mx, greedy: bool):
    def m(ctx, i, st, k):
        s = ctx.s
        end = ctx.end
        limit = end if mx is INF else min(end, i + mx)
        if greedy:
            j = i
            while j < limit and pred(s[j]):
                j += 1
            lo = i + mn
            while j >= lo:
                r = k(j, st)
                if r is not None:
                    return r
                j -= 1
            return None
        lo = i + mn
        if lo > end:
            return None
        j = i
        while j < lo:
            if not pred(s[j]):
                return None
            j += 1
        while True:
            r = k(j, st)
            if r is not None:
                return r
            if j < limit and pred(s[j]):
                j += 1
            else:
                return None
    return m


class Program:
    """컴파일된 패턴. match_at / search 로 쓴다."""

    def __init__(self, seq: list, ngroups: int, flags: int):
        self.ngroups = ngroups
        self.root = Compiler(flags).seq(seq)
        self.empty = ((None,) * (2 * ngroups), None)

    def match_at(self, s: str, i: int, end: int, *, match_all: bool = False, must_advance: bool = False):
        """i 에서 시작하는 매치. 성공하면 (끝, caps, lastindex)."""
        ctx = Ctx(s, end)

        def final(j, st):
            if match_all and j != end:
                return None
            if must_advance and j == i:
                return None
            return (j, st)
        r = self.root(ctx, i, self.empty, final)
        if r is None:
            return None
        return r[0], r[1][0], r[1][1]

    def search(self, s: str, pos: int, end: int, must_advance: bool = False):
        """pos..end 에서 가장 왼쪽 매치. (시작, 끝, caps, lastindex) 또는 None."""
        i = pos
        while i <= end:
            r = self.match_at(s, i, end, must_advance=must_advance and i == pos)
            if r is not None:
                return (i,) + r
            i += 1
        return None
