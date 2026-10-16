import json
from pathlib import Path


class StoreError(Exception):
    pass


class TodoStore:
    def __init__(self, path):
        self.path = Path(path)
        self.next_id = 1
        self._items = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError as e:
                raise StoreError(f"올바른 JSON 이 아닙니다: {e}") from e
            if (not isinstance(data, dict) or not isinstance(data.get("next_id"), int)
                    or not isinstance(data.get("items"), list)):
                raise StoreError("형식이 다릅니다")
            self.next_id = data["next_id"]
            self._items = data["items"]

    def _save(self):
        data = {"next_id": self.next_id, "items": self._items}
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _find(self, id_):
        for x in self._items:
            if x["id"] == id_:
                return x
        raise KeyError(id_)

    def add(self, title):
        title = title.strip()
        if not title:
            raise ValueError("빈 제목")
        id_ = self.next_id
        self._items.append({"id": id_, "title": title, "done": False})
        self.next_id += 1
        self._save()
        return id_

    def done(self, id_):
        self._find(id_)["done"] = True
        self._save()

    def remove(self, id_):
        self._items.remove(self._find(id_))
        self._save()

    def items(self, include_done=True):
        return [dict(x) for x in sorted(self._items, key=lambda x: x["id"]) if include_done or not x["done"]]
