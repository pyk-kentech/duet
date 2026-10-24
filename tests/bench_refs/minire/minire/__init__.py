"""minire: 파이썬 re 의 부분집합을 직접 구현한 정규식 엔진 (참조 구현)."""

from __future__ import annotations

from ._engine import DOTALL, IGNORECASE, MULTILINE, Program
from ._parser import ASCIILETTERS, DIGITS, ESCAPES, MAXGROUPS, OCTDIGITS, Source, error, parse

I = IGNORECASE
M = MULTILINE
S = DOTALL

__all__ = ["compile", "match", "search", "fullmatch", "findall", "finditer", "sub", "subn", "split",
           "escape", "error", "Pattern", "Match", "IGNORECASE", "I", "MULTILINE", "M", "DOTALL", "S"]


def _clamp(string: str, pos: int, endpos: int | None) -> tuple[int, int]:
    n = len(string)
    pos = min(max(pos, 0), n)
    endpos = n if endpos is None else min(max(endpos, 0), n)
    return pos, endpos


class Pattern:
    def __init__(self, pattern: str, flags: int):
        if not isinstance(pattern, str):
            raise TypeError("pattern must be a str")
        seq, state = parse(pattern)
        self.pattern = pattern
        self.flags = flags
        self.groups = state.groups - 1
        self.groupindex = dict(state.groupdict)
        self._names = {v: k for k, v in self.groupindex.items()}
        self._prog = Program(seq, self.groups, flags)

    def __repr__(self) -> str:
        return "minire.compile(%r)" % (self.pattern,)

    # ------------------------------------------------------------ 매치 하나
    def _make(self, string, start, end, caps, lastindex, pos, endpos) -> "Match":
        spans = [(start, end)]
        for g in range(self.groups):
            a, b = caps[2 * g], caps[2 * g + 1]
            spans.append((a, b) if a is not None and b is not None else (-1, -1))
        return Match(self, string, pos, endpos, spans, lastindex)

    def match(self, string: str, pos: int = 0, endpos: int | None = None):
        pos, endpos = _clamp(string, pos, endpos)
        if pos > endpos:
            return None
        r = self._prog.match_at(string, pos, endpos)
        return None if r is None else self._make(string, pos, *r, pos, endpos)

    def fullmatch(self, string: str, pos: int = 0, endpos: int | None = None):
        pos, endpos = _clamp(string, pos, endpos)
        if pos > endpos:
            return None
        r = self._prog.match_at(string, pos, endpos, match_all=True)
        return None if r is None else self._make(string, pos, *r, pos, endpos)

    def search(self, string: str, pos: int = 0, endpos: int | None = None):
        pos, endpos = _clamp(string, pos, endpos)
        r = self._prog.search(string, pos, endpos)
        return None if r is None else self._make(string, *r, pos, endpos)

    # ------------------------------------------------------------ 훑기
    def _iter(self, string: str, pos: int, endpos: int):
        start = pos
        must = False
        while start <= endpos:
            r = self._prog.search(string, start, endpos, must)
            if r is None:
                return
            m = self._make(string, *r, pos, endpos)
            yield m
            must = r[0] == r[1]
            start = r[1]

    def finditer(self, string: str, pos: int = 0, endpos: int | None = None):
        pos, endpos = _clamp(string, pos, endpos)
        return self._iter(string, pos, endpos)

    def findall(self, string: str, pos: int = 0, endpos: int | None = None) -> list:
        pos, endpos = _clamp(string, pos, endpos)
        out = []
        for m in self._iter(string, pos, endpos):
            if self.groups == 0:
                out.append(m.group())
            elif self.groups == 1:
                g = m.group(1)
                out.append("" if g is None else g)
            else:
                out.append(tuple("" if g is None else g for g in m.groups()))
        return out

    def split(self, string: str, maxsplit: int = 0) -> list:
        if maxsplit < 0:
            return [string]
        out: list = []
        last = 0
        n = 0
        for m in self._iter(string, 0, len(string)):
            if maxsplit and n >= maxsplit:
                break
            out.append(string[last:m.start()])
            out.extend(m.groups())
            last = m.end()
            n += 1
        out.append(string[last:])
        return out

    def subn(self, repl, string: str, count: int = 0) -> tuple[str, int]:
        if callable(repl):
            filt = repl
        else:
            items = _parse_template(repl, self)
            filt = lambda m: _expand(items, m)  # noqa: E731
        if count < 0:
            return string, 0
        out: list[str] = []
        last = 0
        n = 0
        for m in self._iter(string, 0, len(string)):
            if count and n >= count:
                break
            out.append(string[last:m.start()])
            out.append(filt(m))
            last = m.end()
            n += 1
        out.append(string[last:])
        return "".join(out), n

    def sub(self, repl, string: str, count: int = 0) -> str:
        return self.subn(repl, string, count)[0]


class Match:
    def __init__(self, pattern: Pattern, string: str, pos: int, endpos: int,
                 spans: list, lastindex):
        self.re = pattern
        self.string = string
        self.pos = pos
        self.endpos = endpos
        self._spans = spans
        self.lastindex = lastindex
        self.lastgroup = pattern._names.get(lastindex) if lastindex is not None else None

    def __repr__(self) -> str:
        return "<minire.Match object; span=%r, match=%r>" % (self.span(), self.group())

    def __bool__(self) -> bool:
        return True

    def _index(self, g) -> int:
        if isinstance(g, str):
            idx = self.re.groupindex.get(g)
            if idx is None:
                raise IndexError("no such group")
            return idx
        if isinstance(g, int) and 0 <= g < len(self._spans):
            return int(g)
        raise IndexError("no such group")

    def _get(self, g, default=None):
        a, b = self._spans[self._index(g)]
        if a < 0:
            return default
        return self.string[a:b]

    def group(self, *groups):
        if not groups:
            return self._get(0)
        if len(groups) == 1:
            return self._get(groups[0])
        return tuple(self._get(g) for g in groups)

    def __getitem__(self, g):
        return self._get(g)

    def groups(self, default=None) -> tuple:
        return tuple(self._get(g, default) for g in range(1, len(self._spans)))

    def groupdict(self, default=None) -> dict:
        return {name: self._get(idx, default) for name, idx in self.re.groupindex.items()}

    def start(self, group=0) -> int:
        return self._spans[self._index(group)][0]

    def end(self, group=0) -> int:
        return self._spans[self._index(group)][1]

    def span(self, group=0) -> tuple[int, int]:
        return self._spans[self._index(group)]

    def expand(self, template: str) -> str:
        return _expand(_parse_template(template, self.re), self)


# ---------------------------------------------------------------- 치환 템플릿
def _parse_template(template: str, pattern: Pattern) -> list:
    s = Source(template)
    items: list = []
    literal: list[str] = []

    def addgroup(index: int, pos: int) -> None:
        if index > pattern.groups:
            raise s.error("invalid group reference %d" % index, pos)
        if literal:
            items.append("".join(literal))
            del literal[:]
        items.append(index)

    while True:
        this = s.get()
        if this is None:
            break
        if this[0] == "\\":
            c = this[1]
            if c == "g":
                if not s.match("<"):
                    raise s.error("missing <")
                name = s.getuntil(">", "group name")
                if name.isidentifier():
                    try:
                        index = pattern.groupindex[name]
                    except KeyError:
                        raise IndexError("unknown group name %r" % name) from None
                else:
                    if not (name.isdecimal() and name.isascii()):
                        raise s.error("bad character in group name %r" % name, len(name) + 1)
                    index = int(name)
                    if index >= MAXGROUPS:
                        raise s.error("invalid group reference %d" % index, len(name) + 1)
                addgroup(index, len(name) + 1)
            elif c == "0":
                if s.next is not None and s.next in OCTDIGITS:
                    this += s.get()
                    if s.next is not None and s.next in OCTDIGITS:
                        this += s.get()
                literal.append(chr(int(this[1:], 8) & 0xFF))
            elif c in DIGITS:
                isoctal = False
                if s.next is not None and s.next in DIGITS:
                    this += s.get()
                    if (c in OCTDIGITS and this[2] in OCTDIGITS
                            and s.next is not None and s.next in OCTDIGITS):
                        this += s.get()
                        isoctal = True
                        v = int(this[1:], 8)
                        if v > 0o377:
                            raise s.error("octal escape value %s outside of range 0-0o377" % this, len(this))
                        literal.append(chr(v))
                if not isoctal:
                    addgroup(int(this[1:]), len(this) - 1)
            elif this in ESCAPES:
                literal.append(ESCAPES[this])
            elif c in ASCIILETTERS:
                raise s.error("bad escape %s" % this, len(this))
            else:
                literal.append(this)
        else:
            literal.append(this)
    if literal:
        items.append("".join(literal))
    return items


def _expand(items: list, m: Match) -> str:
    out = []
    for it in items:
        if isinstance(it, str):
            out.append(it)
        else:
            g = m.group(it)
            if g is not None:
                out.append(g)
    return "".join(out)


# ---------------------------------------------------------------- 모듈 함수
def compile(pattern, flags: int = 0) -> Pattern:  # noqa: A001
    if isinstance(pattern, Pattern):
        if flags:
            raise ValueError("cannot process flags argument with a compiled pattern")
        return pattern
    return Pattern(pattern, flags)


def match(pattern, string, flags=0):
    return compile(pattern, flags).match(string)


def search(pattern, string, flags=0):
    return compile(pattern, flags).search(string)


def fullmatch(pattern, string, flags=0):
    return compile(pattern, flags).fullmatch(string)


def findall(pattern, string, flags=0):
    return compile(pattern, flags).findall(string)


def finditer(pattern, string, flags=0):
    return compile(pattern, flags).finditer(string)


def sub(pattern, repl, string, count=0, flags=0):
    return compile(pattern, flags).sub(repl, string, count)


def subn(pattern, repl, string, count=0, flags=0):
    return compile(pattern, flags).subn(repl, string, count)


def split(pattern, string, maxsplit=0, flags=0):
    return compile(pattern, flags).split(string, maxsplit)


_SPECIAL = frozenset("()[]{}?*+-|^$\\.&~# \t\n\r\v\f")


def escape(pattern: str) -> str:
    return "".join("\\" + c if c in _SPECIAL else c for c in pattern)
