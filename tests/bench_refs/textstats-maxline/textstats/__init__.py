"""참조 구현(-L 추가판): 숨은 테스트 검증용."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Counts:
    lines: int = 0
    words: int = 0
    chars: int = 0
    bytes: int = 0
    max_line_length: int = 0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(self.lines + other.lines, self.words + other.words, self.chars + other.chars,
                      self.bytes + other.bytes, max(self.max_line_length, other.max_line_length))


def count(data: bytes) -> Counts:
    text = data.decode("utf-8", errors="replace")
    return Counts(
        lines=data.count(b"\n"),
        words=len(data.split()),
        chars=len(text),
        bytes=len(data),
        max_line_length=max((len(part) for part in text.split("\n")), default=0),
    )
