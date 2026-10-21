"""DB-API-like surface: connect(), Connection, Cursor."""

from __future__ import annotations

from collections.abc import Sequence

from .engine import Database
from .errors import Error
from .parser import parse_one, parse_script


class Cursor:
    def __init__(self, rows: list, names: list | None, rowcount: int):
        self._rows = rows
        self._pos = 0
        self.description = None if names is None else tuple((n, None, None, None, None, None, None) for n in names)
        self.rowcount = rowcount

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return tuple(row)

    def fetchall(self) -> list:
        rest = [tuple(r) for r in self._rows[self._pos:]]
        self._pos = len(self._rows)
        return rest

    def fetchmany(self, size: int = 1) -> list:
        out = []
        for _ in range(size):
            r = self.fetchone()
            if r is None:
                break
            out.append(r)
        return out

    def __iter__(self):
        return self

    def __next__(self):
        r = self.fetchone()
        if r is None:
            raise StopIteration
        return r

    def close(self) -> None:
        pass


def _check_param(v):
    if v is None or isinstance(v, (int, float, str)):
        if isinstance(v, bool):
            return int(v)
        return v
    raise Error(f"unsupported parameter type: {type(v).__name__}")


class Connection:
    def __init__(self):
        self._db = Database()

    def execute(self, sql: str, params: Sequence = ()) -> Cursor:
        stmt, nparams = parse_one(sql)
        params = tuple(_check_param(p) for p in params)
        if len(params) != nparams:
            raise Error(f"Incorrect number of bindings supplied. The current statement uses {nparams}, "
                        f"and there are {len(params)} supplied.")
        rows, names, rowcount = self._db.execute(stmt, params, sql)
        return Cursor(rows, names, rowcount)

    def executescript(self, sql: str) -> Cursor:
        for stmt in parse_script(sql):
            self._db.execute(stmt, (), sql)
        return Cursor([], None, -1)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def connect() -> Connection:
    return Connection()
