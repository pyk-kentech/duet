"""원문을 토큰으로 자르는 토크나이저.

규칙 (README 의 "토큰" 절과 같다):

* 토큰은 단어 글자(유니코드 글자·숫자·밑줄, :func:`findex.textutil.is_word_char`)가
  이어진 것이다. 한글·한자도 글자이므로 공백이나 문장부호가 나올 때까지 한 토큰이다.
* 단어 안의 결합 표시(유니코드 범주 Mn)는 단어의 일부다: 분해형(NFD) ``nai\\u0308ve`` 는
  한 토큰이다.
* 두 **글자** 사이에 낀 아포스트로피(``'`` 또는 ``’``)는 지우고 앞뒤를 잇는다:
  ``don't`` -> ``dont``, ``O’Brien`` -> ``OBrien``.
* 두 **숫자** 사이에 낀 마침표는 토큰에 남긴다: ``3.14`` 는 한 토큰이다.
* 그 밖의 모든 문자(공백, 문장부호, 하이픈, 기호)는 토큰을 가른다.
  ``e-mail`` 은 ``e`` 와 ``mail`` 두 토큰이다.

**하이픈 단어** (:func:`iter_words`): 하이픈(``-``) 하나를 사이에 두고 붙어 있는 토큰들
(``e-mail``, ``state-of-the-art``)은 한 단어로 묶는다. 하이픈이 둘 이상 붙어 있거나
(``a--b``) 앞뒤에 있으면(``-x``, ``x-``) 묶지 않는다.

토큰에는 원문에서의 위치(``start``, ``end``)가 붙지만, 아포스트로피를 지운 토큰의 길이는
``end - start`` 와 다를 수 있다. 정규화(대소문자 등)는 여기서 하지 않는다 — 분석기의 몫이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from findex.textutil import APOSTROPHES, is_mark, is_word_char


@dataclass(frozen=True)
class Token:
    """원문의 토큰 하나. ``text`` 는 원문 그대로(아포스트로피만 빠짐)."""

    text: str
    start: int
    end: int


@dataclass(frozen=True)
class Word:
    """하이픈으로 묶인 토큰들(하이픈 단어) 또는 토큰 하나."""

    parts: tuple[Token, ...]

    @property
    def start(self) -> int:
        return self.parts[0].start

    @property
    def end(self) -> int:
        return self.parts[-1].end

    @property
    def hyphenated(self) -> bool:
        return len(self.parts) > 1

    @property
    def joined(self) -> str:
        """조각을 이은 글자 (``e-mail`` -> ``email``)."""
        return "".join(p.text for p in self.parts)


def _letter(ch: str) -> bool:
    return ch.isalpha() or is_mark(ch)


def _joins_apostrophe(text: str, i: int, buf: list[str]) -> bool:
    """``text[i]`` 가 두 글자 사이의 아포스트로피인가."""
    if not buf or text[i] not in APOSTROPHES:
        return False
    if i + 1 >= len(text):
        return False
    return _letter(buf[-1]) and text[i + 1].isalpha()


def _joins_decimal(text: str, i: int, buf: list[str]) -> bool:
    """``text[i]`` 가 두 숫자 사이의 마침표인가."""
    if not buf or text[i] != ".":
        return False
    if i + 1 >= len(text):
        return False
    return buf[-1].isdigit() and text[i + 1].isdigit()


def iter_tokens(text: str) -> Iterator[Token]:
    """``text`` 의 토큰을 앞에서부터 하나씩 돌려준다."""
    buf: list[str] = []
    start = -1
    for i, ch in enumerate(text):
        if is_word_char(ch) or (buf and is_mark(ch)):
            if not buf:
                start = i
            buf.append(ch)
        elif _joins_apostrophe(text, i, buf):
            continue                      # dropped, the word goes on
        elif _joins_decimal(text, i, buf):
            buf.append(ch)
        elif buf:
            yield Token("".join(buf), start, i)
            buf = []
    if buf:
        yield Token("".join(buf), start, len(text))


def iter_words(text: str) -> Iterator[Word]:
    """토큰을 하이픈 단어로 묶어 돌려준다 (하이픈 하나로 붙은 토큰들)."""
    group: list[Token] = []
    for tok in iter_tokens(text):
        if group:
            prev = group[-1]
            if tok.start == prev.end + 1 and text[prev.end] == "-":
                group.append(tok)
                continue
            yield Word(tuple(group))
        group = [tok]
    if group:
        yield Word(tuple(group))


def tokenize(text: str) -> list[Token]:
    """``text`` 의 토큰 목록."""
    return list(iter_tokens(text))


def words(text: str) -> list[str]:
    """토큰의 글자만 (디버깅·테스트용)."""
    return [t.text for t in iter_tokens(text)]
