"""Block structure parsing (line by line), following the CommonMark parsing strategy."""

from __future__ import annotations

import re

from .inlines import InlineParser, unescape_string
from .node import Node

CODE_INDENT = 4

RE_THEMATIC_BREAK = re.compile(r"(?:\*[ \t]*){3,}$|(?:_[ \t]*){3,}$|(?:-[ \t]*){3,}$")
RE_MAYBE_SPECIAL = re.compile(r"[#`~*+_=<>0-9-]")
RE_NON_SPACE = re.compile(r"[^ \t\f\v\r\n]")
RE_BULLET = re.compile(r"[*+-]")
RE_ORDERED = re.compile(r"([0-9]{1,9})([.)])")
RE_ATX = re.compile(r"#{1,6}(?:[ \t]+|$)")
RE_CODE_FENCE = re.compile(r"`{3,}(?!.*`)|~{3,}")
RE_CLOSING_FENCE = re.compile(r"(?:`{3,}|~{3,})(?=[ \t]*$)")
RE_SETEXT = re.compile(r"(?:=+|-+)[ \t]*$")
RE_ATX_ONLY_CLOSING = re.compile(r"^[ \t]*#+[ \t]*$")
RE_ATX_CLOSING = re.compile(r"[ \t]+#+[ \t]*$")
RE_BLANK_LINE = re.compile(r"[ \t]*$")


def _is_blank(s: str) -> bool:
    return RE_NON_SPACE.search(s) is None


def _ends_with_blank_line(block: Node) -> bool:
    return block.next is not None and block.end_line != block.next.start_line - 1


def _lists_match(a: dict, b: dict) -> bool:
    return a["type"] == b["type"] and a["delimiter"] == b["delimiter"] and a["bullet"] == b["bullet"]


def _can_contain(parent: str, child: str) -> bool:
    if parent in ("document", "block_quote", "item"):
        return child != "item"
    if parent == "list":
        return child == "item"
    return False


_ACCEPTS_LINES = {"paragraph", "code_block"}


class BlockParser:
    def __init__(self) -> None:
        self.doc = Node("document", 1)
        self.tip = self.doc
        self.oldtip = self.doc
        self.refmap: dict[str, tuple[str, str]] = {}
        self.line_number = 0
        self.offset = 0
        self.column = 0
        self.next_nonspace = 0
        self.next_nonspace_column = 0
        self.indent = 0
        self.indented = False
        self.blank = False
        self.partially_consumed_tab = False
        self.all_closed = True
        self.last_matched_container = self.doc
        self.current_line = ""
        self.inline_parser = InlineParser()

    # --- line position helpers ---------------------------------------------------
    def peek(self, pos: int) -> str:
        return self.current_line[pos] if pos < len(self.current_line) else ""

    def find_next_nonspace(self) -> None:
        line = self.current_line
        i = self.offset
        cols = self.column
        c = ""
        while i < len(line):
            c = line[i]
            if c == " ":
                i += 1
                cols += 1
            elif c == "\t":
                i += 1
                cols += 4 - (cols % 4)
            else:
                break
        else:
            c = ""
        self.blank = c in ("", "\n", "\r")
        self.next_nonspace = i
        self.next_nonspace_column = cols
        self.indent = cols - self.column
        self.indented = self.indent >= CODE_INDENT

    def advance_offset(self, count: int, columns: bool) -> None:
        line = self.current_line
        while count > 0 and self.offset < len(line):
            c = line[self.offset]
            if c == "\t":
                chars_to_tab = 4 - (self.column % 4)
                if columns:
                    self.partially_consumed_tab = chars_to_tab > count
                    adv = count if chars_to_tab > count else chars_to_tab
                    self.column += adv
                    self.offset += 0 if self.partially_consumed_tab else 1
                    count -= adv
                else:
                    self.partially_consumed_tab = False
                    self.column += chars_to_tab
                    self.offset += 1
                    count -= 1
            else:
                self.partially_consumed_tab = False
                self.offset += 1
                self.column += 1
                count -= 1

    def advance_next_nonspace(self) -> None:
        self.offset = self.next_nonspace
        self.column = self.next_nonspace_column
        self.partially_consumed_tab = False

    # --- tree helpers --------------------------------------------------------------
    def add_line(self) -> None:
        if self.partially_consumed_tab:
            self.offset += 1
            self.tip.string_content += " " * (4 - (self.column % 4))
        self.tip.string_content += self.current_line[self.offset:] + "\n"

    def add_child(self, tag: str, offset: int) -> Node:
        while not _can_contain(self.tip.type, tag):
            self.finalize(self.tip, self.line_number - 1)
        node = Node(tag, self.line_number)
        self.tip.append_child(node)
        self.tip = node
        return node

    def close_unmatched_blocks(self) -> None:
        if not self.all_closed:
            while self.oldtip is not self.last_matched_container:
                parent = self.oldtip.parent
                self.finalize(self.oldtip, self.line_number - 1)
                self.oldtip = parent
            self.all_closed = True

    # --- continuation checks: 0 matched, 1 not matched, 2 line consumed ---------------
    def continue_block(self, container: Node) -> int:
        t = container.type
        line = self.current_line
        if t in ("document", "list"):
            return 0
        if t == "block_quote":
            if not self.indented and self.peek(self.next_nonspace) == ">":
                self.advance_next_nonspace()
                self.advance_offset(1, False)
                if self.peek(self.offset) in (" ", "\t"):
                    self.advance_offset(1, True)
                return 0
            return 1
        if t == "item":
            ld = container.list_data
            if self.blank:
                if container.first_child is None:
                    return 1
                self.advance_next_nonspace()
                return 0
            if self.indent >= ld["marker_offset"] + ld["padding"]:
                self.advance_offset(ld["marker_offset"] + ld["padding"], True)
                return 0
            return 1
        if t in ("heading", "thematic_break"):
            return 1
        if t == "code_block":
            if container.is_fenced:
                m = None
                if self.indent <= 3 and self.peek(self.next_nonspace) == container.fence_char:
                    m = RE_CLOSING_FENCE.match(line, self.next_nonspace)
                if m is not None and len(m.group(0)) >= container.fence_length:
                    self.finalize(container, self.line_number)
                    return 2
                i = container.fence_offset
                while i > 0 and self.peek(self.offset) in (" ", "\t") and self.peek(self.offset) != "":
                    self.advance_offset(1, True)
                    i -= 1
                return 0
            if self.indent >= CODE_INDENT:
                self.advance_offset(CODE_INDENT, True)
            elif self.blank:
                self.advance_next_nonspace()
            else:
                return 1
            return 0
        if t == "paragraph":
            return 1 if self.blank else 0
        return 1

    # --- finalization -------------------------------------------------------------
    def finalize(self, block: Node, line_number: int) -> None:
        above = block.parent
        block.open = False
        block.end_line = line_number
        t = block.type
        if t == "document":
            self.remove_link_reference_definitions(block)
        elif t == "list":
            item = block.first_child
            tight = True
            while item is not None and tight:
                if item.next is not None and _ends_with_blank_line(item):
                    tight = False
                    break
                sub = item.first_child
                while sub is not None:
                    if sub.next is not None and _ends_with_blank_line(sub):
                        tight = False
                        break
                    sub = sub.next
                item = item.next
            block.list_data["tight"] = tight
            block.end_line = block.last_child.end_line
        elif t == "item":
            if block.last_child is not None:
                block.end_line = block.last_child.end_line
            else:
                block.end_line = block.start_line
        elif t == "code_block":
            if block.is_fenced:
                content = block.string_content
                nl = content.find("\n")
                block.info = unescape_string(content[:nl].strip())
                block.literal = content[nl + 1:]
            else:
                lines = block.string_content.split("\n")
                while RE_BLANK_LINE.fullmatch(lines[-1]):
                    lines.pop()
                block.literal = "\n".join(lines) + "\n"
                block.end_line = block.start_line + len(lines) - 1
            block.string_content = ""
        self.tip = above

    def remove_link_reference_definitions(self, doc: Node) -> None:
        empty = []

        def walk(node: Node) -> None:
            if node.type == "paragraph":
                has_defs = False
                while node.string_content.startswith("["):
                    pos = self.inline_parser.parse_reference(node.string_content, self.refmap)
                    if not pos:
                        break
                    removed = node.string_content[:pos]
                    node.string_content = node.string_content[pos:]
                    has_defs = True
                    node.start_line += len(removed.split("\n")) - 1
                if has_defs and _is_blank(node.string_content):
                    empty.append(node)
            for child in node.children():
                walk(child)

        walk(doc)
        for node in empty:
            node.unlink()

    # --- block starts: 0 no match, 1 container matched, 2 leaf matched ---------------
    def try_block_starts(self, container: Node) -> int:
        line = self.current_line
        nn = self.next_nonspace
        # block quote
        if not self.indented and self.peek(nn) == ">":
            self.advance_next_nonspace()
            self.advance_offset(1, False)
            if self.peek(self.offset) in (" ", "\t") and self.peek(self.offset) != "":
                self.advance_offset(1, True)
            self.close_unmatched_blocks()
            self.add_child("block_quote", self.next_nonspace)
            return 1
        # ATX heading
        if not self.indented:
            m = RE_ATX.match(line, nn)
            if m is not None:
                self.advance_next_nonspace()
                self.advance_offset(len(m.group(0)), False)
                self.close_unmatched_blocks()
                heading = self.add_child("heading", self.next_nonspace)
                heading.level = len(m.group(0).strip())
                content = line[self.offset:]
                content = RE_ATX_ONLY_CLOSING.sub("", content, count=1)
                content = RE_ATX_CLOSING.sub("", content, count=1)
                heading.string_content = content
                self.advance_offset(len(line) - self.offset, False)
                return 2
        # fenced code
        if not self.indented:
            m = RE_CODE_FENCE.match(line, nn)
            if m is not None:
                fence_length = len(m.group(0))
                self.close_unmatched_blocks()
                block = self.add_child("code_block", self.next_nonspace)
                block.is_fenced = True
                block.fence_length = fence_length
                block.fence_char = m.group(0)[0]
                block.fence_offset = self.indent
                self.advance_next_nonspace()
                self.advance_offset(fence_length, False)
                return 2
        # setext heading
        if not self.indented and container.type == "paragraph":
            m = RE_SETEXT.match(line, nn)
            if m is not None:
                self.close_unmatched_blocks()
                while container.string_content.startswith("["):
                    pos = self.inline_parser.parse_reference(container.string_content, self.refmap)
                    if not pos:
                        break
                    container.string_content = container.string_content[pos:]
                if container.string_content:
                    heading = Node("heading", container.start_line)
                    heading.level = 1 if m.group(0)[0] == "=" else 2
                    heading.string_content = container.string_content
                    container.insert_after(heading)
                    container.unlink()
                    self.tip = heading
                    self.advance_offset(len(line) - self.offset, False)
                    return 2
        # thematic break
        if not self.indented and RE_THEMATIC_BREAK.match(line, nn):
            self.close_unmatched_blocks()
            self.add_child("thematic_break", self.next_nonspace)
            self.advance_offset(len(line) - self.offset, False)
            return 2
        # list item
        if not self.indented or container.type == "list":
            data = self.parse_list_marker(container)
            if data is not None:
                self.close_unmatched_blocks()
                if self.tip.type != "list" or not _lists_match(container.list_data, data):
                    lst = self.add_child("list", self.next_nonspace)
                    lst.list_data = data
                item = self.add_child("item", self.next_nonspace)
                item.list_data = data
                return 1
        # indented code
        if self.indented and self.tip.type != "paragraph" and not self.blank:
            self.advance_offset(CODE_INDENT, True)
            self.close_unmatched_blocks()
            self.add_child("code_block", self.offset)
            return 2
        return 0

    def parse_list_marker(self, container: Node) -> dict | None:
        line = self.current_line
        nn = self.next_nonspace
        if self.indent >= 4:
            return None
        data = {"type": None, "tight": True, "bullet": None, "start": None,
                "delimiter": None, "padding": None, "marker_offset": self.indent}
        m = RE_BULLET.match(line, nn)
        if m is not None:
            data["type"] = "bullet"
            data["bullet"] = m.group(0)
        else:
            m = RE_ORDERED.match(line, nn)
            if m is not None and (container.type != "paragraph" or int(m.group(1)) == 1):
                data["type"] = "ordered"
                data["start"] = int(m.group(1))
                data["delimiter"] = m.group(2)
            else:
                return None
        marker_len = len(m.group(0))
        nextc = self.peek(nn + marker_len)
        if nextc not in ("", "\t", " "):
            return None
        if container.type == "paragraph" and not RE_NON_SPACE.search(line[nn + marker_len:]):
            return None
        self.advance_next_nonspace()
        self.advance_offset(marker_len, True)
        spaces_start_col = self.column
        spaces_start_offset = self.offset
        while True:
            self.advance_offset(1, True)
            nextc = self.peek(self.offset)
            if not (self.column - spaces_start_col < 5 and nextc in (" ", "\t") and nextc != ""):
                break
        blank_item = self.peek(self.offset) == ""
        spaces_after = self.column - spaces_start_col
        if spaces_after >= 5 or spaces_after < 1 or blank_item:
            data["padding"] = marker_len + 1
            self.column = spaces_start_col
            self.offset = spaces_start_offset
            if self.peek(self.offset) in (" ", "\t") and self.peek(self.offset) != "":
                self.advance_offset(1, True)
        else:
            data["padding"] = marker_len + spaces_after
        return data

    # --- main loop -----------------------------------------------------------------
    def incorporate_line(self, ln: str) -> None:
        all_matched = True
        container = self.doc
        self.oldtip = self.tip
        self.offset = 0
        self.column = 0
        self.blank = False
        self.partially_consumed_tab = False
        self.line_number += 1
        if "\x00" in ln:
            ln = ln.replace("\x00", "�")
        self.current_line = ln

        while container.last_child is not None and container.last_child.open:
            container = container.last_child
            self.find_next_nonspace()
            r = self.continue_block(container)
            if r == 2:
                return
            if r == 1:
                all_matched = False
                container = container.parent
                break

        self.all_closed = container is self.oldtip
        self.last_matched_container = container

        matched_leaf = container.type != "paragraph" and container.type in _ACCEPTS_LINES
        while not matched_leaf:
            self.find_next_nonspace()
            if not self.indented and not RE_MAYBE_SPECIAL.match(ln, self.next_nonspace):
                self.advance_next_nonspace()
                break
            r = self.try_block_starts(container)
            if r == 1:
                container = self.tip
            elif r == 2:
                container = self.tip
                matched_leaf = True
            else:
                self.advance_next_nonspace()
                break

        if not self.all_closed and not self.blank and self.tip.type == "paragraph":
            self.add_line()  # lazy paragraph continuation
        else:
            self.close_unmatched_blocks()
            if container.type in _ACCEPTS_LINES:
                self.add_line()
            elif self.offset < len(ln) and not self.blank:
                self.add_child("paragraph", self.offset)
                self.advance_next_nonspace()
                self.add_line()

    def parse(self, text: str) -> Node:
        lines = re.split(r"\r\n|\n|\r", text)
        n = len(lines)
        if text.endswith("\n"):
            n -= 1
        for i in range(n):
            self.incorporate_line(lines[i])
        while self.tip is not None:
            self.finalize(self.tip, n)
        self.inline_parser.refmap = self.refmap
        self._process_inlines(self.doc)
        return self.doc

    def _process_inlines(self, node: Node) -> None:
        for child in node.children():
            self._process_inlines(child)
        if node.type in ("paragraph", "heading"):
            self.inline_parser.parse(node)
