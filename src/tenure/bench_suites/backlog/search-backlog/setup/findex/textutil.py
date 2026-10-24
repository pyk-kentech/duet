"""문자열 도우미.

색인어의 표준형은 :func:`normalize` 로 만든다(NFC + casefold). 분석기(``analyzer``)는
모든 색인어를 이 함수로 만든다.

이 모듈에는 여러 모듈이 같이 쓰는 작은 도우미만 둔다. 무거운 처리는 넣지 않는다.
"""

from __future__ import annotations

import unicodedata

#: 단어 안에서 글자 사이에 끼면 지우고 앞뒤를 잇는 아포스트로피들 ("don't" -> "dont").
APOSTROPHES = "'’"

#: 스니펫 앞뒤가 잘렸음을 보여 주는 표시.
ELLIPSIS = "…"


def normalize(text: str) -> str:
    """색인어 표준형: 유니코드 NFC 로 합친 뒤 casefold.

    >>> normalize("Straße")
    'strasse'
    """
    return unicodedata.normalize("NFC", text).casefold()


def is_word_char(ch: str) -> bool:
    """단어를 이루는 글자인가 (유니코드 글자·숫자·밑줄)."""
    return ch.isalnum() or ch == "_"


def strip_apostrophes(word: str) -> str:
    """단어 안의 아포스트로피를 지운다 ("O'Brien" -> "OBrien")."""
    for a in APOSTROPHES:
        word = word.replace(a, "")
    return word


def squeeze_spaces(text: str) -> str:
    """줄바꿈·탭·연속 공백을 공백 하나로 바꾸고 앞뒤 공백을 지운다."""
    return " ".join(text.split())


def cut_at_space(text: str, limit: int) -> int:
    """``text[:limit]`` 안에서 마지막 공백의 위치를 돌려준다 (없으면 ``limit``).

    스니펫을 단어 중간에서 자르지 않으려고 쓴다.
    """
    if len(text) <= limit:
        return len(text)
    cut = text.rfind(" ", 0, limit + 1)
    for ws in ("\n", "\t"):
        cut = max(cut, text.rfind(ws, 0, limit + 1))
    return cut if cut > 0 else limit


def plural(n: int, word: str) -> str:
    """CLI 메시지용: ``plural(3, "문서")`` -> ``"문서 3개"``."""
    return f"{word} {n}개"
