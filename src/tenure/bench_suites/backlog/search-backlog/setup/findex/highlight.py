"""강조(highlight)와 스니펫.

원문에서 검색어에 맞는 단어를 찾아 표시(기본 ``[`` 와 ``]``)로 감싼다. **원문은 바꾸지
않고** 표시만 끼워 넣는다(대소문자·철자 그대로).

어떤 단어를 강조하나 (README 의 "강조와 스니펫" 절):

* NOT 아래가 아닌 단어·구절·접두어가 대상이다. ``tag:``, ``date:`` 는 강조하지 않는다.
* 필드를 정한 검색어(``title:x``)는 그 필드를 강조할 때만 쓴다.
* 구절의 단어는 **구절로 붙어 있지 않아도 각각** 강조한다.
* 비교는 색인과 같은 규칙(대소문자 무시, 어간)으로 한다. 불용어는 강조하지 않는다.
* 접두어는 그 접두어로 시작하는 단어를 강조한다.

스니펫 (``Index.snippet``) 은 본문에서 잘라 낸 한 토막이다.

* 본문이 ``length`` 글자 이하이면 본문 전체.
* 맞은 단어가 없으면 앞에서부터 ``length`` 글자 안의 마지막 공백까지.
* 맞은 단어가 있으면 첫 번째 맞은 단어의 30글자 앞(그 사이의 첫 공백 다음)에서 시작해
  ``length`` 글자 안의 마지막 공백까지.
* 앞이 잘렸으면 맨 앞에, 뒤가 잘렸으면 맨 뒤에 ``…`` 를 붙인다. 줄바꿈·연속 공백은
  공백 하나로 바꾼다. ``length`` 는 표시와 ``…`` 를 세지 않은 원문 글자 수다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from findex.analyzer import Analyzer
from findex.query import PhraseQ, PrefixQ, TermQ, iter_positive
from findex.stemmer import stem
from findex.textutil import ELLIPSIS, cut_at_space, squeeze_spaces, strip_apostrophes

DEFAULT_MARKERS = ("[", "]")
SNIPPET_LENGTH = 120
MIN_SNIPPET_LENGTH = 20
CONTEXT = 30

# words as the highlighter sees them: decimals, or word runs joined by apostrophes
_WORD_RE = re.compile(r"\d+(?:\.\d+)+|\w+(?:['’]\w+)*")

Span = tuple[int, int]


@dataclass(frozen=True)
class Matcher:
    terms: frozenset[str]
    prefixes: tuple[str, ...]
    stem: bool

    def matches(self, word: str) -> bool:
        low = strip_apostrophes(word).lower()
        if any(low.startswith(p) for p in self.prefixes):
            return True
        if self.stem:
            low = stem(low)
        return low in self.terms

    def __bool__(self) -> bool:
        return bool(self.terms or self.prefixes)


def build_matcher(node, analyzer: Analyzer, field: str) -> Matcher:
    """검색어 AST 에서 ``field`` 를 강조할 때 쓸 비교기를 만든다."""
    terms: set[str] = set()
    prefixes: list[str] = []
    for part in iter_positive(node):
        if part.field not in (None, field):
            continue
        if isinstance(part, PrefixQ):
            prefixes.append(part.prefix)
        elif isinstance(part, TermQ):
            terms.update(analyzer.query_terms(part.word))
        elif isinstance(part, PhraseQ):
            terms.update(analyzer.query_terms(part.text))
    return Matcher(frozenset(terms), tuple(prefixes), analyzer.stem)


def find_spans(text: str, matcher: Matcher) -> list[Span]:
    """강조할 단어들의 (시작, 끝) 위치."""
    if not matcher:
        return []
    return [(m.start(), m.end()) for m in _WORD_RE.finditer(text) if matcher.matches(m.group())]


def mark(text: str, spans: list[Span], markers: tuple[str, str] = DEFAULT_MARKERS) -> str:
    """``spans`` 를 표시로 감싼 문자열."""
    open_, close = markers
    out: list[str] = []
    last = 0
    for start, end in spans:
        if start < last:
            continue
        out.append(text[last:start])
        out.append(open_ + text[start:end] + close)
        last = end
    out.append(text[last:])
    return "".join(out)


def check_markers(markers: object) -> tuple[str, str]:
    if (not isinstance(markers, (tuple, list)) or len(markers) != 2
            or not all(isinstance(m, str) for m in markers)):
        raise ValueError("markers 는 (여는 표시, 닫는 표시) 두 문자열이어야 합니다")
    return markers[0], markers[1]


def snippet(text: str, spans: list[Span], length: int = SNIPPET_LENGTH,
            markers: tuple[str, str] = DEFAULT_MARKERS) -> str:
    """본문 한 토막 (모듈 설명의 규칙)."""
    if isinstance(length, bool) or not isinstance(length, int) or length < MIN_SNIPPET_LENGTH:
        raise ValueError(f"length 는 {MIN_SNIPPET_LENGTH} 이상의 정수여야 합니다: {length!r}")
    n = len(text)
    if n <= length:
        start, end = 0, n
    elif not spans:
        start, end = 0, cut_at_space(text, length)
    else:
        first = spans[0][0]
        start = max(0, first - CONTEXT)
        if start > 0:
            gap = text[start:first]
            k = -1
            for i, ch in enumerate(gap):
                if ch.isspace():
                    k = i
                    break
            start = start + k + 1 if k >= 0 else first
        if start + length >= n:
            end = n
        else:
            end = start + cut_at_space(text[start:], length)
    inside = [(s - start, e - start) for s, e in spans if s >= start and e <= end]
    body = squeeze_spaces(mark(text[start:end], inside, markers))
    return (ELLIPSIS if start > 0 else "") + body + (ELLIPSIS if end < n else "")
