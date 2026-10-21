"""아주 단순한 영어 어간 추출기.

색인과 검색이 같은 규칙을 쓰기만 하면 되므로 정확한 언어학적 어간이 목표가 아니다.
규칙은 위에서부터 **처음 맞는 하나만** 적용한다. 다음 경우에는 아무것도 하지 않는다.

* 길이가 3 이하인 단어
* 글자(``str.isalpha``)가 아닌 문자가 섞인 단어 (숫자, 밑줄 등)
* :data:`EXCEPTIONS` 에 있는 단어 (그 값으로 바꾼다)

=========  ======================================  ==========================
규칙        조건                                      예
=========  ======================================  ==========================
``ies``    남는 부분이 2글자 이상이면 ``y`` 로         studies -> study
``sses``   ``ss`` 로                                  classes -> class
``ss``     그대로                                     class -> class
``us``     그대로                                     status -> status
``is``     그대로                                     analysis -> analysis
``s``      뗀다                                       cats -> cat
``ing``    남는 부분이 3글자 이상이면 뗀다(*)          running -> run
``ed``     남는 부분이 3글자 이상이면 뗀다(*)          stopped -> stop
``ly``     남는 부분이 4글자 이상이면 뗀다             quickly -> quick
=========  ======================================  ==========================

(*) 떼고 난 끝이 같은 자음 두 개이면(``l``, ``s``, ``z`` 제외) 하나를 더 뗀다.
"""

from __future__ import annotations

VOWELS = frozenset("aeiou")

#: 규칙 대신 이 값을 쓴다.
EXCEPTIONS: dict[str, str] = {
    "news": "news",
    "series": "series",
    "species": "species",
    "physics": "physics",
    "children": "child",
    "people": "person",
    "mice": "mouse",
    "feet": "foot",
    "teeth": "tooth",
    "data": "data",
}

_KEEP_DOUBLE = frozenset("lsz")


def _undouble(word: str) -> str:
    if len(word) >= 2 and word[-1] == word[-2] and word[-1] not in VOWELS and word[-1] not in _KEEP_DOUBLE:
        return word[:-1]
    return word


def stem(word: str) -> str:
    """``word`` (이미 정규화된 소문자 단어)의 어간."""
    if word in EXCEPTIONS:
        return EXCEPTIONS[word]
    if len(word) <= 3 or not word.isalpha():
        return word
    if word.endswith("ies"):
        return word[:-3] + "y" if len(word) - 3 >= 2 else word
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("s"):
        return word[:-1]
    if word.endswith("ing"):
        rest = word[:-3]
        return _undouble(rest) if len(rest) >= 3 else word
    if word.endswith("ed"):
        rest = word[:-2]
        return _undouble(rest) if len(rest) >= 3 else word
    if word.endswith("ly"):
        rest = word[:-2]
        return rest if len(rest) >= 4 else word
    return word


def stem_all(words: list[str]) -> list[str]:
    return [stem(w) for w in words]
