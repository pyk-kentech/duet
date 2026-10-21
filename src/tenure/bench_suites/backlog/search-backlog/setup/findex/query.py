"""검색어 언어: 렉서와 재귀 하강 파서.

문법 (README 의 "검색어" 절)::

    query    := or_expr
    or_expr  := and_expr ("OR" and_expr)*
    and_expr := unary (["AND"] unary)*          # 나란히 쓰면 AND
    unary    := "NOT" unary | "-" unary | primary
    primary  := "(" or_expr ")" | PHRASE | FIELD ":" PHRASE | WORD

* 연산자 ``AND``, ``OR``, ``NOT`` 은 **대문자일 때만** 연산자다. 소문자 ``and``/``or``/``not``
  은 보통 단어다(기본 설정에서는 불용어라 무시된다). 우선순위: NOT > AND > OR.
* ``-단어`` 는 ``NOT 단어`` 의 줄임이다. ``-`` 는 토큰의 맨 앞에 붙어 있을 때만 그런 뜻이다.
  ``-"구절"``, ``-(묶음)``, ``-tag:x`` 도 된다. 홀로 선 ``-`` 는 무시한다.
* ``"..."`` 는 구절이다(큰따옴표만). ``title:"..."`` 처럼 필드를 붙일 수 있다.
  ``tag:"..."`` 는 공백이 든 태그를 거르는 태그 필터다.
* ``title:단어``, ``body:단어`` 는 그 필드만 찾는다. ``tag:값`` 은 태그 필터, ``date:범위`` 는
  날짜 필터다. 필드 이름은 소문자만 알아본다. 모르는 이름이 붙은 단어(``foo:bar``)는
  보통 단어로 본다.
* ``단어*`` 는 접두어 검색이다. ``*`` 앞은 두 글자 이상이어야 한다. 접두어는 어간 추출을
  하지 않는다.

파서는 분석(정규화·불용어·어간)을 하지 않는다. 분석은 검색할 때 :mod:`findex.search` 가
분석기로 한다. 접두어만은 여기서 소문자로 바꿔 둔다.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Iterator, Union

from findex.errors import QuerySyntaxError

TEXT_FIELD_NAMES = ("title", "body")
OPERATORS = ("AND", "OR", "NOT")
MIN_PREFIX = 2


# ====================================================================== AST
@dataclass(frozen=True)
class TermQ:
    word: str                 # raw word as typed (analyzed later)
    field: str | None = None


@dataclass(frozen=True)
class PhraseQ:
    text: str                 # raw phrase text without quotes
    field: str | None = None


@dataclass(frozen=True)
class PrefixQ:
    prefix: str               # lower-cased prefix without the trailing '*'
    field: str | None = None


@dataclass(frozen=True)
class TagQ:
    tag: str                  # raw tag value


@dataclass(frozen=True)
class DateQ:
    start: date | None
    end: date | None


@dataclass(frozen=True)
class AndQ:
    items: tuple


@dataclass(frozen=True)
class OrQ:
    items: tuple


@dataclass(frozen=True)
class NotQ:
    item: object


Node = Union[TermQ, PhraseQ, PrefixQ, TagQ, DateQ, AndQ, OrQ, NotQ]


# ====================================================================== lexer
@dataclass(frozen=True)
class Tok:
    kind: str                 # LPAREN RPAREN PHRASE WORD AND OR NOT
    text: str = ""
    field: str | None = None


def _read_phrase(q: str, i: int) -> tuple[str, int]:
    """``q[i]`` 가 여는 따옴표. (구절 내용, 닫는 따옴표 다음 위치)."""
    j = q.find('"', i + 1)
    if j < 0:
        raise QuerySyntaxError("닫히지 않은 따옴표가 있습니다")
    return q[i + 1:j], j + 1


def lex(q: str) -> list[Tok]:
    out: list[Tok] = []
    i, n = 0, len(q)
    while i < n:
        ch = q[i]
        if ch.isspace():
            i += 1
        elif ch == "(":
            out.append(Tok("LPAREN"))
            i += 1
        elif ch == ")":
            out.append(Tok("RPAREN"))
            i += 1
        elif ch == '"':
            text, i = _read_phrase(q, i)
            out.append(Tok("PHRASE", text))
        elif ch == "-":
            # "-term" is the short form of "NOT term"; a lone "-" means nothing
            if i + 1 < n and not q[i + 1].isspace():
                out.append(Tok("NOT"))
            i += 1
        else:
            j = i
            while j < n and not q[j].isspace() and q[j] not in '()"':
                j += 1
            word = q[i:j]
            if word.endswith(":") and j < n and q[j] == '"':
                text, j = _read_phrase(q, j)
                out.append(Tok("PHRASE", text, field=word[:-1]))
            elif word in OPERATORS:
                out.append(Tok(word))
            else:
                out.append(Tok("WORD", word))
            i = j
    return out


# ====================================================================== dates
_PARTIAL_DATE = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")


def _partial_date(text: str, *, end: bool) -> date:
    """``2024`` / ``2024-03`` / ``2024-03-05`` -> 그 기간의 첫날(또는 끝날)."""
    m = _PARTIAL_DATE.fullmatch(text)
    if not m:
        raise QuerySyntaxError(f"잘못된 날짜입니다: {text}")
    year = int(m.group(1))
    try:
        if m.group(2) is None:
            return date(year, 12, 31) if end else date(year, 1, 1)
        month = int(m.group(2))
        if m.group(3) is None:
            last = calendar.monthrange(year, month)[1]
            return date(year, month, last if end else 1)
        return date(year, month, int(m.group(3)))
    except (ValueError, calendar.IllegalMonthError):
        raise QuerySyntaxError(f"없는 날짜입니다: {text}") from None


def parse_date_range(value: str) -> DateQ:
    """``date:`` 뒤의 값. ``A..B``(양 끝 포함), ``A..``, ``..B``, ``A``(그 기간 전체)."""
    if ".." in value:
        a, _, b = value.partition("..")
        start = _partial_date(a, end=False) if a else None
        end = _partial_date(b, end=True) if b else None
        if start is None and end is None:
            raise QuerySyntaxError("날짜 범위가 비어 있습니다")
    else:
        if not value:
            raise QuerySyntaxError("date: 뒤에 날짜가 없습니다")
        start = _partial_date(value, end=False)
        end = _partial_date(value, end=True)
    if start and end and start > end:
        raise QuerySyntaxError(f"날짜 범위의 시작이 끝보다 늦습니다: {value}")
    return DateQ(start, end)


# ====================================================================== parser
def _word_node(text: str) -> Node:
    if ":" in text:
        name, _, value = text.partition(":")
        if name in TEXT_FIELD_NAMES:
            if not value:
                raise QuerySyntaxError(f"{name}: 뒤에 검색어가 없습니다")
            return _plain_or_prefix(value, name)
        if name == "tag":
            if not value:
                raise QuerySyntaxError("tag: 뒤에 태그가 없습니다")
            return TagQ(value)
        if name == "date":
            return parse_date_range(value)
    return _plain_or_prefix(text, None)


def _plain_or_prefix(text: str, field: str | None) -> Node:
    if text.endswith("*"):
        prefix = text.rstrip("*")
        if len(prefix) < MIN_PREFIX:
            raise QuerySyntaxError(f"접두어는 {MIN_PREFIX}글자 이상이어야 합니다: {text}")
        return PrefixQ(prefix.lower(), field)
    return TermQ(text, field)


class _Parser:
    def __init__(self, toks: list[Tok]):
        self.toks = toks
        self.i = 0

    def peek(self) -> Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def advance(self) -> Tok:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def parse(self) -> Node | None:
        if not self.toks:
            return None
        node = self.or_expr()
        if self.peek() is not None:
            tok = self.peek()
            if tok.kind == "RPAREN":
                raise QuerySyntaxError("짝이 없는 닫는 괄호가 있습니다")
            raise QuerySyntaxError(f"예상하지 못한 토큰: {tok.text or tok.kind}")
        return node

    def or_expr(self) -> Node:
        items = [self.and_expr()]
        while self.peek() is not None and self.peek().kind == "OR":
            self.advance()
            items.append(self.and_expr())
        return items[0] if len(items) == 1 else OrQ(tuple(items))

    def and_expr(self) -> Node:
        items = [self.unary()]
        while True:
            tok = self.peek()
            if tok is None or tok.kind in ("OR", "RPAREN"):
                break
            if tok.kind == "AND":
                self.advance()
            items.append(self.unary())
        return items[0] if len(items) == 1 else AndQ(tuple(items))

    def unary(self) -> Node:
        tok = self.peek()
        if tok is not None and tok.kind == "NOT":
            self.advance()
            nxt = self.peek()
            if nxt is None or nxt.kind in ("RPAREN", "OR", "AND"):
                raise QuerySyntaxError("NOT 뒤에 검색어가 없습니다")
            return NotQ(self.unary())
        return self.primary()

    def primary(self) -> Node:
        tok = self.peek()
        if tok is None:
            raise QuerySyntaxError("검색어가 끝났는데 검색어가 더 필요합니다")
        self.advance()
        if tok.kind == "LPAREN":
            if self.peek() is not None and self.peek().kind == "RPAREN":
                raise QuerySyntaxError("빈 괄호입니다")
            node = self.or_expr()
            if self.peek() is None or self.peek().kind != "RPAREN":
                raise QuerySyntaxError("닫히지 않은 괄호가 있습니다")
            self.advance()
            return node
        if tok.kind == "PHRASE":
            if tok.field == "tag":
                if not tok.text.strip():
                    raise QuerySyntaxError("tag: 뒤에 태그가 없습니다")
                return TagQ(tok.text)       # tag:"machine learning"
            if tok.field is not None and tok.field not in TEXT_FIELD_NAMES:
                raise QuerySyntaxError(f"구절에 쓸 수 없는 필드입니다: {tok.field}")
            return PhraseQ(tok.text, tok.field)
        if tok.kind == "WORD":
            return _word_node(tok.text)
        if tok.kind == "RPAREN":
            raise QuerySyntaxError("짝이 없는 닫는 괄호가 있습니다")
        raise QuerySyntaxError(f"{tok.kind} 앞에 검색어가 없습니다")


def parse(q: str) -> Node | None:
    """검색어 문자열 -> AST. 빈 검색어는 ``None``."""
    if not isinstance(q, str):
        raise TypeError("검색어는 문자열이어야 합니다")
    return _Parser(lex(q)).parse()


# ====================================================================== helpers
def iter_positive(node: Node | None) -> Iterator[Node]:
    """NOT 아래가 아닌 단어·구절·접두어 노드들 (강조할 대상)."""
    if node is None:
        return
    if isinstance(node, (AndQ, OrQ)):
        for item in node.items:
            yield from iter_positive(item)
    elif isinstance(node, NotQ):
        return
    elif isinstance(node, (TermQ, PhraseQ, PrefixQ)):
        yield node


def describe(node: Node | None) -> str:
    """디버깅용 사람이 읽을 수 있는 형태."""
    if node is None:
        return "<empty>"
    if isinstance(node, TermQ):
        return f"{node.field}:{node.word}" if node.field else node.word
    if isinstance(node, PhraseQ):
        return f'{node.field}:"{node.text}"' if node.field else f'"{node.text}"'
    if isinstance(node, PrefixQ):
        return f"{node.field}:{node.prefix}*" if node.field else f"{node.prefix}*"
    if isinstance(node, TagQ):
        return f"tag:{node.tag}"
    if isinstance(node, DateQ):
        return f"date:{node.start or ''}..{node.end or ''}"
    if isinstance(node, NotQ):
        return f"NOT {describe(node.item)}"
    joiner = " AND " if isinstance(node, AndQ) else " OR "
    return "(" + joiner.join(describe(i) for i in node.items) + ")"
