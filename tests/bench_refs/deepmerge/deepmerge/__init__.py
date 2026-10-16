import copy
import json


def merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        raise TypeError("dict 끼리만 병합합니다")
    out = copy.deepcopy(base)
    for k, v in override.items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def merge_all(*configs):
    out = {}
    for c in configs:
        out = merge(out, c)
    return out


def parse_overrides(items):
    out = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"'=' 가 없습니다: {item!r}")
        path, raw = item.split("=", 1)
        keys = path.split(".")
        if any(not k for k in keys):
            raise ValueError(f"빈 키: {item!r}")
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        node = out
        for k in keys[:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value
    return out
