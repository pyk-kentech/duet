"""참조 구현: 숨은 테스트 검증용."""


class ParseError(ValueError):
    def __init__(self, message, lineno):
        super().__init__(f"{lineno}번째 줄: {message}")
        self.lineno = lineno


def _unquote(v):
    if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    return v


def parse(text):
    out: dict[str, dict[str, str]] = {}
    section = ""
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("["):
            if not line.endswith("]"):
                raise ParseError("닫히지 않은 섹션", lineno)
            name = line[1:-1].strip()
            if not name:
                raise ParseError("빈 섹션 이름", lineno)
            section = name
            out.setdefault(section, {})
            continue
        if "=" not in line:
            raise ParseError("= 가 없음", lineno)
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ParseError("빈 키", lineno)
        out.setdefault(section, {})[key] = _unquote(value.strip())
    return out


def _quote(v):
    if v != v.strip() or (len(v) >= 2 and v.startswith('"') and v.endswith('"')):
        return f'"{v}"'
    return v


def dumps(data):
    lines = []
    for k, v in data.get("", {}).items():
        lines.append(f"{k} = {_quote(v)}")
    for name, items in data.items():
        if name == "":
            continue
        lines.append(f"[{name}]")
        for k, v in items.items():
            lines.append(f"{k} = {_quote(v)}")
    return "\n".join(lines) + ("\n" if lines else "")
