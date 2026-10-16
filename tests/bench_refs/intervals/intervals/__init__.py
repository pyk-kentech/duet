"""참조 구현: 숨은 테스트 검증용."""


def _norm(items):
    out = []
    for s, e in items:
        if s > e:
            raise ValueError(f"start > end: {(s, e)}")
        if s < e:
            out.append((s, e))
    return out


def merge(items):
    out: list[tuple[int, int]] = []
    for s, e in sorted(_norm(items)):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def insert(items, new):
    return merge([*items, new])


def subtract(items, cut):
    cs, ce = cut
    if cs > ce:
        raise ValueError(f"start > end: {(cs, ce)}")
    if cs == ce:
        return merge(items)
    out = []
    for s, e in merge(items):
        if ce <= s or e <= cs:
            out.append((s, e))
            continue
        if s < cs:
            out.append((s, cs))
        if ce < e:
            out.append((ce, e))
    return out


def total_length(items):
    return sum(e - s for s, e in merge(items))
