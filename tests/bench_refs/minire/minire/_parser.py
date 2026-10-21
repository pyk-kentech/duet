"""패턴 문자열 → 구문 트리. 파이썬 re(sre_parse)의 규칙을 부분집합에 대해 따른다.

노드(튜플):
  ("lit", ch) ("any",) ("set", negate, items) ("at", kind)
  ("group", index_or_None, seq) ("alt", [seq, ...]) ("repeat", min, max_or_None, greedy, seq)
  ("ref", index) ("look", behind, negate, seq, width)
seq 는 노드의 list. set 의 items: ("lit", ch) | ("range", lo, hi) | ("cat", name)
cat 이름: "d" "D" "s" "S" "w" "W"
at 종류: "bol" "eol" "bos" "eos" "b" "B"
"""

from __future__ import annotations

from dataclasses import dataclass, field

INF = None  # 반복 상한 없음

DIGITS = frozenset("0123456789")
OCTDIGITS = frozenset("01234567")
HEXDIGITS = frozenset("0123456789abcdefABCDEF")
ASCIILETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
SPECIAL_CHARS = ".\\[{()*+?^$|"
REPEAT_CHARS = "*+?{"
MAXGROUPS = 2 ** 30

ESCAPES = {"\\a": "\a", "\\b": "\b", "\\f": "\f", "\\n": "\n", "\\r": "\r",
           "\\t": "\t", "\\v": "\v", "\\\\": "\\"}
CATEGORIES = {"\\d": ("set", False, [("cat", "d")]), "\\D": ("set", False, [("cat", "D")]),
              "\\s": ("set", False, [("cat", "s")]), "\\S": ("set", False, [("cat", "S")]),
              "\\w": ("set", False, [("cat", "w")]), "\\W": ("set", False, [("cat", "W")]),
              "\\A": ("at", "bos"), "\\Z": ("at", "eos"), "\\b": ("at", "b"), "\\B": ("at", "B")}


class error(Exception):
    """잘못된 패턴·템플릿."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pattern is not None and pos is not None:
            msg = "%s at position %d" % (msg, pos)
        super().__init__(msg)


class Source:
    def __init__(self, string: str):
        self.string = string
        self.index = 0
        self.next: str | None = None
        self._advance()

    def _advance(self) -> None:
        index = self.index
        try:
            char = self.string[index]
        except IndexError:
            self.next = None
            return
        if char == "\\":
            try:
                char += self.string[index + 1]
            except IndexError:
                raise error("bad escape (end of pattern)", self.string, len(self.string) - 1) from None
        self.index = index + len(char)
        self.next = char

    def match(self, char: str) -> bool:
        if char == self.next:
            self._advance()
            return True
        return False

    def get(self) -> str | None:
        this = self.next
        self._advance()
        return this

    def getuntil(self, terminator: str, name: str) -> str:
        result = ""
        while True:
            c = self.next
            self._advance()
            if c is None:
                if not result:
                    raise self.error("missing " + name)
                raise self.error("missing %s, unterminated name" % terminator, len(result))
            if c == terminator:
                if not result:
                    raise self.error("missing " + name, 1)
                break
            result += c
        return result

    def tell(self) -> int:
        return self.index - len(self.next or "")

    def seek(self, index: int) -> None:
        self.index = index
        self._advance()

    def error(self, msg: str, offset: int = 0) -> error:
        return error(msg, self.string, self.tell() - offset)


@dataclass
class State:
    groupdict: dict[str, int] = field(default_factory=dict)
    groupwidths: list = field(default_factory=lambda: [None])
    lookbehindgroups: int | None = None

    @property
    def groups(self) -> int:
        return len(self.groupwidths)

    def opengroup(self, name: str | None, source: Source) -> int:
        gid = self.groups
        self.groupwidths.append(None)
        if self.groups > MAXGROUPS:
            raise source.error("too many groups")
        if name is not None:
            ogid = self.groupdict.get(name)
            if ogid is not None:
                raise source.error("redefinition of group name %r as group %d; was group %d"
                                   % (name, gid, ogid))
            self.groupdict[name] = gid
        return gid

    def closegroup(self, gid: int, seq: list) -> None:
        self.groupwidths[gid] = getwidth(seq, self)

    def checkgroup(self, gid: int) -> bool:
        return gid < self.groups and self.groupwidths[gid] is not None

    def checklookbehindgroup(self, gid: int, source: Source) -> None:
        if self.lookbehindgroups is not None:
            if not self.checkgroup(gid):
                raise source.error("cannot refer to an open group")
            if gid >= self.lookbehindgroups:
                raise source.error("cannot refer to group defined in the same lookbehind subpattern")


BIG = 1 << 62


def getwidth(seq: list, state: State) -> tuple[int, int]:
    """(최소, 최대) 너비. 최대가 무한이면 BIG."""
    lo = hi = 0
    for node in seq:
        op = node[0]
        if op == "alt":
            i, j = BIG, 0
            for alt in node[1]:
                l, h = getwidth(alt, state)
                i = min(i, l)
                j = max(j, h)
            lo += i
            hi += j
        elif op == "group":
            i, j = getwidth(node[2], state)
            lo += i
            hi += j
        elif op == "repeat":
            i, j = getwidth(node[4], state)
            lo += i * node[1]
            if node[2] is INF and j:
                hi = BIG
            else:
                hi += j * (node[2] if node[2] is not INF else 0)
        elif op in ("lit", "any", "set"):
            lo += 1
            hi += 1
        elif op == "ref":
            w = state.groupwidths[node[1]]
            lo += w[0]
            hi += w[1]
    return min(lo, BIG), min(hi, BIG)


def parse(pattern: str) -> tuple[list, State]:
    source = Source(pattern)
    state = State()
    seq = _parse_sub(source, state, 0)
    if source.next is not None:
        assert source.next == ")"
        raise source.error("unbalanced parenthesis")
    _check_lookbehind(seq, state)
    return seq, state


def _check_lookbehind(seq: list, state: State) -> None:
    for node in seq:
        op = node[0]
        if op == "alt":
            for alt in node[1]:
                _check_lookbehind(alt, state)
        elif op == "group":
            _check_lookbehind(node[2], state)
        elif op == "repeat":
            _check_lookbehind(node[4], state)
        elif op == "look":
            _check_lookbehind(node[3], state)


def _parse_sub(source: Source, state: State, nested: int) -> list:
    items = []
    while True:
        items.append(_parse(source, state, nested + 1))
        if not source.match("|"):
            break
    if len(items) == 1:
        return items[0]
    return [("alt", items)]


def _class_escape(source: Source, escape: str):
    code = ESCAPES.get(escape)
    if code is not None:
        return ("lit", code)
    code = CATEGORIES.get(escape)
    if code is not None and code[0] == "set":
        return code[2][0]          # ("cat", name)
    c = escape[1:2]
    if c == "x":
        escape += _take(source, HEXDIGITS, 2)
        if len(escape) != 4:
            raise source.error("incomplete escape %s" % escape, len(escape))
        return ("lit", chr(int(escape[2:], 16)))
    if c in "uU":
        n = 4 if c == "u" else 8
        escape += _take(source, HEXDIGITS, n)
        if len(escape) != n + 2:
            raise source.error("incomplete escape %s" % escape, len(escape))
        return ("lit", chr(int(escape[2:], 16)))
    if c in OCTDIGITS:
        escape += _take(source, OCTDIGITS, 2)
        v = int(escape[1:], 8)
        if v > 0o377:
            raise source.error("octal escape value %s outside of range 0-0o377" % escape, len(escape))
        return ("lit", chr(v))
    if c in DIGITS:
        raise source.error("bad escape %s" % escape, len(escape))
    if len(escape) == 2:
        if c in ASCIILETTERS:
            raise source.error("bad escape %s" % escape, len(escape))
        return ("lit", escape[1])
    raise source.error("bad escape %s" % escape, len(escape))


def _take(source: Source, allowed: frozenset, n: int) -> str:
    out = ""
    while len(out) < n and source.next is not None and source.next in allowed:
        out += source.get()
    return out


def _escape(source: Source, escape: str, state: State):
    code = CATEGORIES.get(escape)
    if code is not None:
        return code
    code = ESCAPES.get(escape)
    if code is not None:
        return ("lit", code)
    c = escape[1:2]
    if c == "x":
        escape += _take(source, HEXDIGITS, 2)
        if len(escape) != 4:
            raise source.error("incomplete escape %s" % escape, len(escape))
        return ("lit", chr(int(escape[2:], 16)))
    if c in "uU":
        n = 4 if c == "u" else 8
        escape += _take(source, HEXDIGITS, n)
        if len(escape) != n + 2:
            raise source.error("incomplete escape %s" % escape, len(escape))
        return ("lit", chr(int(escape[2:], 16)))
    if c == "0":
        escape += _take(source, OCTDIGITS, 2)
        return ("lit", chr(int(escape[1:], 8)))
    if c in DIGITS:
        # 8진수 escape 이거나 번호 역참조
        if source.next is not None and source.next in DIGITS:
            escape += source.get()
            if (escape[1] in OCTDIGITS and escape[2] in OCTDIGITS
                    and source.next is not None and source.next in OCTDIGITS):
                escape += source.get()
                v = int(escape[1:], 8)
                if v > 0o377:
                    raise source.error("octal escape value %s outside of range 0-0o377" % escape,
                                       len(escape))
                return ("lit", chr(v))
        group = int(escape[1:])
        if group < state.groups:
            if not state.checkgroup(group):
                raise source.error("cannot refer to an open group", len(escape))
            state.checklookbehindgroup(group, source)
            return ("ref", group)
        raise source.error("invalid group reference %d" % group, len(escape) - 1)
    if len(escape) == 2:
        if c in ASCIILETTERS:
            raise source.error("bad escape %s" % escape, len(escape))
        return ("lit", escape[1])
    raise source.error("bad escape %s" % escape, len(escape))


def _parse(source: Source, state: State, nested: int) -> list:
    subpattern: list = []
    append = subpattern.append
    while True:
        this = source.next
        if this is None:
            break
        if this in "|)":
            break
        source.get()

        if this[0] == "\\":
            append(_escape(source, this, state))

        elif this not in SPECIAL_CHARS:
            append(("lit", this))

        elif this == "[":
            here = source.tell() - 1
            items: list = []
            negate = source.match("^")
            while True:
                this = source.get()
                if this is None:
                    raise error("unterminated character set", source.string, here)
                if this == "]" and items:
                    break
                if this[0] == "\\":
                    code1 = _class_escape(source, this)
                else:
                    code1 = ("lit", this)
                if source.match("-"):
                    that = source.get()
                    if that is None:
                        raise error("unterminated character set", source.string, here)
                    if that == "]":
                        items.append(code1)
                        items.append(("lit", "-"))
                        break
                    if that[0] == "\\":
                        code2 = _class_escape(source, that)
                    else:
                        code2 = ("lit", that)
                    if code1[0] != "lit" or code2[0] != "lit":
                        raise source.error("bad character range %s-%s" % (this, that),
                                           len(this) + 1 + len(that))
                    lo, hi = code1[1], code2[1]
                    if hi < lo:
                        raise source.error("bad character range %s-%s" % (this, that),
                                           len(this) + 1 + len(that))
                    items.append(("range", lo, hi))
                else:
                    items.append(code1)
            append(("set", negate, items))

        elif this in REPEAT_CHARS:
            here = source.tell()
            if this == "?":
                lo_, hi_ = 0, 1
            elif this == "*":
                lo_, hi_ = 0, INF
            elif this == "+":
                lo_, hi_ = 1, INF
            else:  # "{"
                if source.next == "}":
                    append(("lit", this))
                    continue
                lo_, hi_ = 0, INF
                lo = hi = ""
                while source.next is not None and source.next in DIGITS:
                    lo += source.get()
                if source.match(","):
                    while source.next is not None and source.next in DIGITS:
                        hi += source.get()
                else:
                    hi = lo
                if not source.match("}"):
                    append(("lit", this))
                    source.seek(here)
                    continue
                if lo:
                    lo_ = int(lo)
                if hi:
                    hi_ = int(hi)
                    if hi_ < lo_:
                        raise source.error("min repeat greater than max repeat", source.tell() - here)
            item = subpattern[-1] if subpattern else None
            if item is None or item[0] == "at":
                raise source.error("nothing to repeat", source.tell() - here + len(this))
            if item[0] == "repeat":
                raise source.error("multiple repeat", source.tell() - here + len(this))
            if item[0] == "group" and item[1] is None:
                body = item[2]
            else:
                body = [item]
            if source.match("?"):
                subpattern[-1] = ("repeat", lo_, hi_, False, body)
            elif source.next == "+":
                raise source.error("possessive quantifiers are not supported")
            else:
                subpattern[-1] = ("repeat", lo_, hi_, True, body)

        elif this == ".":
            append(("any",))

        elif this == "(":
            start = source.tell() - 1
            capture = True
            name = None
            if source.match("?"):
                char = source.get()
                if char is None:
                    raise source.error("unexpected end of pattern")
                if char == "P":
                    if source.match("<"):
                        name = source.getuntil(">", "group name")
                        if not name.isidentifier():
                            raise source.error("bad character in group name %r" % name, len(name) + 1)
                    elif source.match("="):
                        name = source.getuntil(")", "group name")
                        if not name.isidentifier():
                            raise source.error("bad character in group name %r" % name, len(name) + 1)
                        gid = state.groupdict.get(name)
                        if gid is None:
                            raise source.error("unknown group name %r" % name, len(name) + 1)
                        if not state.checkgroup(gid):
                            raise source.error("cannot refer to an open group", len(name) + 1)
                        state.checklookbehindgroup(gid, source)
                        append(("ref", gid))
                        continue
                    else:
                        char = source.get()
                        if char is None:
                            raise source.error("unexpected end of pattern")
                        raise source.error("unknown extension ?P" + char, len(char) + 2)
                elif char == ":":
                    capture = False
                elif char in "=!<":
                    behind = False
                    if char == "<":
                        char = source.get()
                        if char is None:
                            raise source.error("unexpected end of pattern")
                        if char not in "=!":
                            raise source.error("unknown extension ?<" + char, len(char) + 2)
                        behind = True
                        lookbehindgroups = state.lookbehindgroups
                        if lookbehindgroups is None:
                            state.lookbehindgroups = state.groups
                    p = _parse_sub(source, state, nested + 1)
                    if behind:
                        if lookbehindgroups is None:
                            state.lookbehindgroups = None
                    if not source.match(")"):
                        raise source.error("missing ), unterminated subpattern", source.tell() - start)
                    width = 0
                    if behind:
                        lo, hi = getwidth(p, state)
                        if lo != hi:
                            raise error("look-behind requires fixed-width pattern")
                        width = lo
                    append(("look", behind, char == "!", p, width))
                    continue
                else:
                    raise source.error("unknown extension ?" + char, len(char) + 1)

            group = state.opengroup(name, source) if capture else None
            p = _parse_sub(source, state, nested + 1)
            if not source.match(")"):
                raise source.error("missing ), unterminated subpattern", source.tell() - start)
            if group is not None:
                state.closegroup(group, p)
            append(("group", group, p))

        elif this == "^":
            append(("at", "bol"))

        elif this == "$":
            append(("at", "eol"))

        else:  # pragma: no cover
            raise AssertionError("unsupported special character %r" % (this,))

    return subpattern
