"""명령줄 도구: ``python -m findex [--index 파일] 명령 ...``.

* 색인 파일(``--index``, 기본 ``findex.json``)이 없으면 빈 색인으로 시작한다.
* 바꾸는 명령(add, import, update, delete, reindex)만 끝난 뒤 저장한다. 오류가 나면 저장하지 않는다.
* 오류는 표준 오류에 ``오류: <메시지>``, 종료 코드 1. (인자 오류는 argparse 가 종료 코드 2)
* 출력은 항상 UTF-8.

출력 형식은 README 의 "CLI" 절에 적혀 있고, 스크립트가 읽으므로 바꾸지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from findex.engine import Index
from findex.errors import FindexError
from findex.facets import format_facets
from findex.query import describe, parse

DEFAULT_INDEX = "findex.json"
WRITE_COMMANDS = frozenset({"add", "import", "merge", "update", "delete", "reindex"})


class CliError(Exception):
    """CLI 에서만 나는 오류 (입력 파일 문제 등)."""


# ====================================================================== helpers
def _open_index(path: Path) -> Index:
    if not path.exists():
        return Index()
    return Index.load(path)


def _read_body(args: argparse.Namespace) -> str | None:
    if getattr(args, "body_file", None):
        try:
            return Path(args.body_file).read_text(encoding="utf-8")
        except OSError as e:
            raise CliError(f"본문 파일을 읽을 수 없습니다: {args.body_file} ({e.strerror})") from None
    return args.body


def format_score(score: float) -> str:
    """CLI 의 점수 표기: 소수 넷째 자리 (API 는 반올림하지 않는다)."""
    return f"{score:.4f}"


def format_document(doc) -> str:
    lines = [
        f"id: {doc.id}",
        f"title: {doc.title}",
        f"tags: {', '.join(doc.tags) if doc.tags else '-'}",
        f"date: {doc.date or '-'}",
        "",
        doc.body,
    ]
    return "\n".join(lines)


def _import_file(index: Index, path: str) -> list[int]:
    try:
        return index.import_jsonl(path)
    except OSError as e:
        raise CliError(f"파일을 읽을 수 없습니다: {path} ({e.strerror})") from None


# ====================================================================== commands
def cmd_add(index: Index, args: argparse.Namespace) -> None:
    doc_id = index.add(args.title, _read_body(args) or "", args.tag or (), args.date)
    print(doc_id)


def cmd_import(index: Index, args: argparse.Namespace) -> None:
    for doc_id in _import_file(index, args.file):
        print(doc_id)


def cmd_export(index: Index, args: argparse.Namespace) -> None:
    try:
        n = index.export_jsonl(args.file)
    except OSError as e:
        raise CliError(f"파일을 쓸 수 없습니다: {args.file} ({e.strerror})") from None
    print(f"내보냄: {n}")


def cmd_merge(index: Index, args: argparse.Namespace) -> None:
    other_path = Path(args.file)
    if not other_path.exists():
        raise CliError(f"합칠 색인 파일이 없습니다: {args.file}")
    for doc_id in index.merge(Index.load(other_path)):
        print(doc_id)


def cmd_update(index: Index, args: argparse.Namespace) -> None:
    tags = [] if args.clear_tags else (args.tag or None)
    index.update(args.id, title=args.title, body=_read_body(args), tags=tags, date=args.date)


def cmd_delete(index: Index, args: argparse.Namespace) -> None:
    index.delete(args.id)


def cmd_get(index: Index, args: argparse.Namespace) -> None:
    doc = index.get(args.id)
    if args.highlight:
        # same layout, with the matched words of title and body marked
        doc = replace(doc, title=index.highlight(doc.id, args.highlight, field="title"),
                      body=index.highlight(doc.id, args.highlight, field="body"))
    print(format_document(doc))


def cmd_terms(index: Index, args: argparse.Namespace) -> None:
    for term, df in index.vocabulary(field=args.field, limit=args.limit):
        print(f"{term}	{df}")


def cmd_search(index: Index, args: argparse.Namespace) -> None:
    results = index.search(args.query, page=args.page, per_page=args.per_page, sort=args.sort)
    if args.json:
        # machine-readable: scores are NOT rounded here
        print(json.dumps(results.to_dict(), ensure_ascii=False))
        return
    print(f"검색 결과 {results.total}건")
    for hit in results.hits:
        print(f"{hit.doc_id}\t{format_score(hit.score)}\t{hit.title}")
        if args.snippets:
            print("    " + index.snippet(hit.doc_id, args.query))


def cmd_facets(index: Index, args: argparse.Namespace) -> None:
    text = format_facets(index.facets(args.query, limit=args.limit))
    if text:
        print(text)


def cmd_suggest(index: Index, args: argparse.Namespace) -> None:
    for term, df in index.suggest(args.prefix, limit=args.limit):
        print(f"{term}\t{df}")


def cmd_similar(index: Index, args: argparse.Namespace) -> None:
    for hit in index.similar(args.id, limit=args.limit):
        print(f"{hit.doc_id}	{format_score(hit.score)}	{hit.title}")


def cmd_explain(index: Index, args: argparse.Namespace) -> None:
    for field, part, score in index.explain(args.id, args.query):
        print(f"{field}	{part}	{format_score(score)}")


def cmd_correct(index: Index, args: argparse.Namespace) -> None:
    fixed = index.correct(args.query)
    if fixed is not None:
        print(fixed)


def cmd_reindex(index: Index, args: argparse.Namespace) -> None:
    print(f"다시 색인함: {index.reindex()}")


def cmd_info(index: Index, args: argparse.Namespace) -> None:
    settings = index.analyzer.settings()
    stopwords = "default" if settings["stopwords"] is None else str(len(settings["stopwords"]))
    print(f"stopwords	{stopwords}")
    print(f"stem	{'yes' if settings['stem'] else 'no'}")
    print("boosts	" + " ".join(f"{k}={v:g}" for k, v in index.boosts.items()))


def cmd_check(index: Index, args: argparse.Namespace) -> int:
    problems = index.check()
    for line in problems:
        print(line)
    if not problems:
        print("OK")
    return 1 if problems else 0


def cmd_parse(index: Index, args: argparse.Namespace) -> None:
    """검색어를 어떻게 읽었는지 보여 준다 (디버깅용)."""
    print(describe(parse(args.query)))


def cmd_stats(index: Index, args: argparse.Namespace) -> None:
    for key, value in index.stats().items():
        print(f"{key}\t{value}")


COMMANDS = {
    "add": cmd_add, "import": cmd_import, "merge": cmd_merge, "update": cmd_update, "delete": cmd_delete, "get": cmd_get,
    "search": cmd_search, "facets": cmd_facets, "suggest": cmd_suggest, "stats": cmd_stats,
    "export": cmd_export, "similar": cmd_similar, "explain": cmd_explain,
    "correct": cmd_correct, "reindex": cmd_reindex, "info": cmd_info, "terms": cmd_terms, "check": cmd_check,
    "parse": cmd_parse,
}


# ====================================================================== parser
def build_parser() -> argparse.ArgumentParser:
    from findex import __version__

    p = argparse.ArgumentParser(prog="findex", description="작은 전문 검색 도구")
    p.add_argument("--index", default=DEFAULT_INDEX, help=f"색인 파일 (기본 {DEFAULT_INDEX})")
    p.add_argument("--version", action="version", version=f"findex {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="문서 추가 (새 id 출력)")
    a.add_argument("title")
    body = a.add_mutually_exclusive_group()
    body.add_argument("--body", default="")
    body.add_argument("--body-file")
    a.add_argument("--tag", action="append", help="여러 번 쓸 수 있다")
    a.add_argument("--date", help="YYYY-MM-DD")

    i = sub.add_parser("import", help="JSON Lines 파일의 문서를 모두 추가 (하나라도 틀리면 아무것도 안 함)")
    i.add_argument("file")

    m = sub.add_parser("merge", help="다른 색인 파일의 문서를 새 id 로 모두 추가 (새 id 출력)")
    m.add_argument("file")

    e = sub.add_parser("export", help="문서를 JSON Lines 파일로 내보내기")
    e.add_argument("file")

    u = sub.add_parser("update", help="문서 고치기 (준 필드만)")
    u.add_argument("id", type=int)
    u.add_argument("--title")
    ubody = u.add_mutually_exclusive_group()
    ubody.add_argument("--body")
    ubody.add_argument("--body-file")
    utags = u.add_mutually_exclusive_group()
    utags.add_argument("--tag", action="append")
    utags.add_argument("--clear-tags", action="store_true")
    u.add_argument("--date")

    d = sub.add_parser("delete", help="문서 지우기")
    d.add_argument("id", type=int)

    g = sub.add_parser("get", help="문서 보기")
    g.add_argument("id", type=int)
    g.add_argument("--highlight", metavar="QUERY", help="이 검색어에 맞는 단어를 [ ] 로 강조")

    t = sub.add_parser("terms", help="많이 나온 색인어")
    t.add_argument("--field", choices=["title", "body"])
    t.add_argument("--limit", type=int, default=20)

    s = sub.add_parser("search", help="검색")
    s.add_argument("query")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--per-page", type=int, default=10)
    s.add_argument("--sort", default="score", choices=["score", "date"])
    s.add_argument("--snippets", action="store_true", help="결과마다 본문 스니펫을 한 줄 더 보여 준다")
    s.add_argument("--json", action="store_true", help="결과를 JSON 한 줄로 (점수 반올림 없음)")

    f = sub.add_parser("facets", help="태그별 문서 수")
    f.add_argument("query", nargs="?")
    f.add_argument("--limit", type=int)

    sg = sub.add_parser("suggest", help="자동 완성")
    sg.add_argument("prefix")
    sg.add_argument("--limit", type=int, default=10)

    sm = sub.add_parser("similar", help="비슷한 문서")
    sm.add_argument("id", type=int)
    sm.add_argument("--limit", type=int, default=5)

    x = sub.add_parser("explain", help="점수 풀이 (디버깅용)")
    x.add_argument("id", type=int)
    x.add_argument("query")

    c = sub.add_parser("correct", help="철자를 고친 검색어 (고칠 것이 없으면 출력 없음)")
    c.add_argument("query")

    sub.add_parser("reindex", help="문서로부터 역색인을 다시 만든다")
    sub.add_parser("info", help="색인 설정")
    sub.add_parser("check", help="색인이 문서와 맞는지 검사 (문제가 있으면 종료 코드 1)")
    pq = sub.add_parser("parse", help="검색어를 어떻게 읽었는지 보기 (디버깅용)")
    pq.add_argument("query")

    sub.add_parser("stats", help="색인 통계")
    return p


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _utf8_output()
    args = build_parser().parse_args(argv)
    path = Path(args.index)
    try:
        index = _open_index(path)
        code = COMMANDS[args.command](index, args)
        if args.command in WRITE_COMMANDS:
            index.save(path)
    except (FindexError, CliError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return code or 0
