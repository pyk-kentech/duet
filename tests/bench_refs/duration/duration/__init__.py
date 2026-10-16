import re

_UNITS = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
_RE = re.compile(r"(?:([0-9]+)d)?(?:([0-9]+)h)?(?:([0-9]+)m)?(?:([0-9]+)s)?", re.ASCII)


def parse(text):
    if not isinstance(text, str):
        raise TypeError("문자열이어야 합니다")
    m = _RE.fullmatch(text)
    if not text or m is None or not any(m.groups()):
        raise ValueError(f"잘못된 기간: {text!r}")
    return sum(int(g) * sec for g, (_, sec) in zip(m.groups(), _UNITS) if g is not None)


def format(seconds):
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise TypeError("int 여야 합니다")
    if seconds < 0:
        raise ValueError("음수")
    if seconds == 0:
        return "0s"
    parts = []
    for unit, sec in _UNITS:
        q, seconds = divmod(seconds, sec)
        if q:
            parts.append(f"{q}{unit}")
    return "".join(parts)
