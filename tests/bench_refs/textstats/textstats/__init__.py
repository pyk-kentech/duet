"""wc 비슷한 줄·단어·글자·바이트 세기."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Counts:
    lines: int = 0
    words: int = 0
    chars: int = 0
    bytes: int = 0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(self.lines + other.lines, self.words + other.words,
                      self.chars + other.chars, self.bytes + other.bytes)


def count(data: bytes) -> Counts:
    return Counts(
        lines=data.count(b"\n"),
        words=len(data.split()),
        chars=len(data.decode("utf-8", errors="replace")),
        bytes=len(data),
    )
