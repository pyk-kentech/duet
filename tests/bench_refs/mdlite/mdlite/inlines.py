"""Inline parsing: code spans, emphasis (delimiter algorithm), links, images, autolinks, breaks."""

from __future__ import annotations

import re
import unicodedata

from .node import Node

ESCAPABLE = "!\"#$%&'()*+,./:;<=>?@[\\]^_`{|}~-"
_ESC_CLASS = r"[!\"#$%&'()*+,./:;<=>?@\[\\\]^_`{|}~-]"

RE_BACKSLASH_ESCAPE = re.compile(r"\\(" + _ESC_CLASS + ")")
RE_LINK_TITLE = re.compile(
    r'"(?:\\' + _ESC_CLASS + r'|\\[^\\]|[^\\"\x00])*"'
    r"|'(?:\\" + _ESC_CLASS + r"|\\[^\\]|[^\\'\x00])*'"
    r"|\((?:\\" + _ESC_CLASS + r"|\\[^\\]|[^\\()\x00])*\)"
)
RE_DEST_BRACES = re.compile(r"<(?:[^<>\n\\\x00]|\\.)*>")
RE_TICKS = re.compile(r"`+")
RE_EMAIL_AUTOLINK = re.compile(
    r"<([a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*)>"
)
RE_AUTOLINK = re.compile(r"<[A-Za-z][A-Za-z0-9.+-]{1,31}:[^<>\x00-\x20]*>")
RE_SPNL = re.compile(r" *(?:\n *)?")
RE_INITIAL_SPACE = re.compile(r" *")
RE_SPACE_AT_EOL = re.compile(r" *(?:\n|$)")
RE_LINK_LABEL = re.compile(r"\[(?:[^\\\[\]]|\\.){0,1000}\]", re.S)
RE_MAIN = re.compile(r"[^\n`\[\]\\!<&*_'\"]+")
RE_WS_COLLAPSE = re.compile(r"[ \t\r\n]+")

_URL_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789;/?:@&=+$,-_.!~*'()#")
_HEX = set("0123456789abcdefABCDEF")


def unescape_string(s: str) -> str:
    """Replace backslash escapes of ASCII punctuation by the character (no entities)."""
    if "\\" not in s:
        return s
    return RE_BACKSLASH_ESCAPE.sub(lambda m: m.group(1), s)


def normalize_uri(s: str) -> str:
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "%" and i + 2 < n and s[i + 1] in _HEX and s[i + 2] in _HEX:
            out.append(s[i:i + 3])
            i += 3
            continue
        if ord(c) < 128:
            out.append(c if c in _URL_SAFE else "%%%02X" % ord(c))
        else:
            out.append("".join("%%%02X" % b for b in c.encode("utf-8", "surrogatepass")))
        i += 1
    return "".join(out)


def normalize_reference(label: str) -> str:
    """[label] -> matching key: strip, collapse whitespace, Unicode case fold."""
    return RE_WS_COLLAPSE.sub(" ", label[1:-1].strip()).casefold()


def is_unicode_whitespace(c: str) -> bool:
    return c in "\t\n\f\r" or unicodedata.category(c) == "Zs"


def is_punctuation(c: str) -> bool:
    if c in ESCAPABLE:
        return True
    return unicodedata.category(c)[0] in ("P", "S")


def text(s: str) -> Node:
    n = Node("text")
    n.literal = s
    return n


class Delimiter:
    __slots__ = ("cc", "numdelims", "origdelims", "node", "previous", "next", "can_open", "can_close")

    def __init__(self, cc, numdelims, node, previous, can_open, can_close):
        self.cc = cc
        self.numdelims = numdelims
        self.origdelims = numdelims
        self.node = node
        self.previous = previous
        self.next = None
        self.can_open = can_open
        self.can_close = can_close


class Bracket:
    __slots__ = ("node", "previous", "previous_delimiter", "index", "image", "active", "bracket_after")

    def __init__(self, node, previous, previous_delimiter, index, image):
        self.node = node
        self.previous = previous
        self.previous_delimiter = previous_delimiter
        self.index = index
        self.image = image
        self.active = True
        self.bracket_after = False


class InlineParser:
    def __init__(self) -> None:
        self.subject = ""
        self.pos = 0
        self.delimiters: Delimiter | None = None
        self.brackets: Bracket | None = None
        self.refmap: dict[str, tuple[str, str]] = {}

    # --- low level -------------------------------------------------------
    def match(self, regex: re.Pattern) -> str | None:
        m = regex.match(self.subject, self.pos)
        if m is None:
            return None
        self.pos = m.end()
        return m.group(0)

    def peek(self) -> str:
        return self.subject[self.pos] if self.pos < len(self.subject) else ""

    def spnl(self) -> bool:
        self.match(RE_SPNL)
        return True

    # --- inline constructs -------------------------------------------------
    def parse_backticks(self, block: Node) -> bool:
        m = RE_TICKS.match(self.subject, self.pos)
        if m is None:
            return False
        ticks = m.group(0)
        self.pos = m.end()
        after_open = self.pos
        while True:
            m2 = RE_TICKS.search(self.subject, self.pos)
            if m2 is None:
                break
            self.pos = m2.end()
            if m2.group(0) == ticks:
                node = Node("code")
                contents = self.subject[after_open:m2.start()].replace("\n", " ")
                if (contents and contents.strip(" ") != "" and contents[0] == " "
                        and contents[-1] == " "):
                    node.literal = contents[1:-1]
                else:
                    node.literal = contents
                block.append_child(node)
                return True
        self.pos = after_open
        block.append_child(text(ticks))
        return True

    def parse_backslash(self, block: Node) -> bool:
        self.pos += 1
        c = self.peek()
        if c == "\n":
            self.pos += 1
            block.append_child(Node("linebreak"))
        elif c != "" and c in ESCAPABLE:
            block.append_child(text(c))
            self.pos += 1
        else:
            block.append_child(text("\\"))
        return True

    def parse_autolink(self, block: Node) -> bool:
        m = self.match(RE_EMAIL_AUTOLINK)
        if m is not None:
            dest = m[1:-1]
            node = Node("link")
            node.destination = normalize_uri("mailto:" + dest)
            node.append_child(text(dest))
            block.append_child(node)
            return True
        m = self.match(RE_AUTOLINK)
        if m is not None:
            dest = m[1:-1]
            node = Node("link")
            node.destination = normalize_uri(dest)
            node.append_child(text(dest))
            block.append_child(node)
            return True
        return False

    def scan_delims(self, cc: str):
        numdelims = 0
        startpos = self.pos
        while self.peek() == cc:
            numdelims += 1
            self.pos += 1
        if numdelims == 0:
            return None
        char_before = "\n" if startpos == 0 else self.subject[startpos - 1]
        char_after = self.peek() or "\n"
        after_ws = is_unicode_whitespace(char_after)
        after_p = is_punctuation(char_after)
        before_ws = is_unicode_whitespace(char_before)
        before_p = is_punctuation(char_before)
        left = not after_ws and (not after_p or before_ws or before_p)
        right = not before_ws and (not before_p or after_ws or after_p)
        if cc == "_":
            can_open = left and (not right or before_p)
            can_close = right and (not left or after_p)
        else:
            can_open = left
            can_close = right
        self.pos = startpos
        return numdelims, can_open, can_close

    def handle_delim(self, cc: str, block: Node) -> bool:
        res = self.scan_delims(cc)
        if res is None:
            return False
        numdelims, can_open, can_close = res
        startpos = self.pos
        self.pos += numdelims
        node = text(self.subject[startpos:self.pos])
        block.append_child(node)
        if can_open or can_close:
            d = Delimiter(cc, numdelims, node, self.delimiters, can_open, can_close)
            if d.previous is not None:
                d.previous.next = d
            self.delimiters = d
        return True

    def remove_delimiter(self, d: Delimiter) -> None:
        if d.previous is not None:
            d.previous.next = d.next
        if d.next is None:
            self.delimiters = d.previous
        else:
            d.next.previous = d.previous

    @staticmethod
    def remove_delimiters_between(bottom: Delimiter, top: Delimiter) -> None:
        if bottom.next is not top:
            bottom.next = top
            top.previous = bottom

    def process_emphasis(self, stack_bottom: Delimiter | None) -> None:
        openers_bottom = {}
        for cc in "_*":
            for can_open in (False, True):
                for mod in range(3):
                    openers_bottom[(cc, can_open, mod)] = stack_bottom
        closer = self.delimiters
        while closer is not None and closer.previous is not stack_bottom:
            closer = closer.previous
        while closer is not None:
            if not closer.can_close:
                closer = closer.next
                continue
            key = (closer.cc, closer.can_open, closer.origdelims % 3)
            opener = closer.previous
            opener_found = False
            while opener is not None and opener is not stack_bottom and opener is not openers_bottom[key]:
                odd_match = ((closer.can_open or opener.can_close)
                             and closer.origdelims % 3 != 0
                             and (opener.origdelims + closer.origdelims) % 3 == 0)
                if opener.cc == closer.cc and opener.can_open and not odd_match:
                    opener_found = True
                    break
                opener = opener.previous
            old_closer = closer
            if not opener_found:
                closer = closer.next
            else:
                use = 2 if closer.numdelims >= 2 and opener.numdelims >= 2 else 1
                opener_inl = opener.node
                closer_inl = closer.node
                opener.numdelims -= use
                closer.numdelims -= use
                opener_inl.literal = opener_inl.literal[:len(opener_inl.literal) - use]
                closer_inl.literal = closer_inl.literal[:len(closer_inl.literal) - use]
                emph = Node("emph" if use == 1 else "strong")
                tmp = opener_inl.next
                while tmp is not None and tmp is not closer_inl:
                    nxt = tmp.next
                    tmp.unlink()
                    emph.append_child(tmp)
                    tmp = nxt
                opener_inl.insert_after(emph)
                self.remove_delimiters_between(opener, closer)
                if opener.numdelims == 0:
                    opener_inl.unlink()
                    self.remove_delimiter(opener)
                if closer.numdelims == 0:
                    closer_inl.unlink()
                    tempstack = closer.next
                    self.remove_delimiter(closer)
                    closer = tempstack
            if not opener_found:
                openers_bottom[key] = old_closer.previous
                if not old_closer.can_open:
                    self.remove_delimiter(old_closer)
        while self.delimiters is not None and self.delimiters is not stack_bottom:
            self.remove_delimiter(self.delimiters)

    def parse_link_title(self) -> str | None:
        t = self.match(RE_LINK_TITLE)
        if t is None:
            return None
        return unescape_string(t[1:-1])

    def parse_link_destination(self) -> str | None:
        res = self.match(RE_DEST_BRACES)
        if res is not None:
            return normalize_uri(unescape_string(res[1:-1]))
        if self.peek() == "<":
            return None
        savepos = self.pos
        openparens = 0
        c = ""
        while True:
            c = self.peek()
            if c == "":
                break
            if c == "\\" and self.pos + 1 < len(self.subject) and self.subject[self.pos + 1] in ESCAPABLE:
                self.pos += 2
            elif c == "(":
                self.pos += 1
                openparens += 1
            elif c == ")":
                if openparens < 1:
                    break
                self.pos += 1
                openparens -= 1
            elif c in " \t\n\x0b\x0c\r":
                break
            else:
                self.pos += 1
        if self.pos == savepos and c != ")":
            return None
        if openparens != 0:
            return None
        return normalize_uri(unescape_string(self.subject[savepos:self.pos]))

    def parse_link_label(self) -> int:
        m = RE_LINK_LABEL.match(self.subject, self.pos)
        if m is None or len(m.group(0)) > 1001:
            return 0
        self.pos = m.end()
        return len(m.group(0))

    def add_bracket(self, node: Node, index: int, image: bool) -> None:
        if self.brackets is not None:
            self.brackets.bracket_after = True
        self.brackets = Bracket(node, self.brackets, self.delimiters, index, image)

    def remove_bracket(self) -> None:
        self.brackets = self.brackets.previous

    def parse_open_bracket(self, block: Node) -> bool:
        startpos = self.pos
        self.pos += 1
        node = text("[")
        block.append_child(node)
        self.add_bracket(node, startpos, False)
        return True

    def parse_bang(self, block: Node) -> bool:
        startpos = self.pos
        self.pos += 1
        if self.peek() == "[":
            self.pos += 1
            node = text("![")
            block.append_child(node)
            self.add_bracket(node, startpos + 1, True)
        else:
            block.append_child(text("!"))
        return True

    def parse_close_bracket(self, block: Node) -> bool:
        self.pos += 1
        startpos = self.pos
        opener = self.brackets
        if opener is None:
            block.append_child(text("]"))
            return True
        if not opener.active:
            block.append_child(text("]"))
            self.remove_bracket()
            return True
        is_image = opener.image
        savepos = self.pos
        matched = False
        dest = title = None
        if self.peek() == "(":
            self.pos += 1
            ok = False
            if self.spnl():
                dest = self.parse_link_destination()
                if dest is not None:
                    self.spnl()
                    if self.subject[self.pos - 1] in " \t\n\x0b\x0c\r":
                        title = self.parse_link_title()
                    self.spnl()
                    if self.peek() == ")":
                        ok = True
            if ok:
                self.pos += 1
                matched = True
            else:
                self.pos = savepos
        if not matched:
            beforelabel = self.pos
            n = self.parse_link_label()
            reflabel = None
            if n > 2:
                reflabel = self.subject[beforelabel:beforelabel + n]
            elif not opener.bracket_after:
                reflabel = self.subject[opener.index:startpos]
            if n == 0:
                self.pos = savepos
            if reflabel:
                link = self.refmap.get(normalize_reference(reflabel))
                if link is not None:
                    dest, title = link
                    matched = True
        if matched:
            node = Node("image" if is_image else "link")
            node.destination = dest
            node.title = title or ""
            tmp = opener.node.next
            while tmp is not None:
                nxt = tmp.next
                tmp.unlink()
                node.append_child(tmp)
                tmp = nxt
            block.append_child(node)
            self.process_emphasis(opener.previous_delimiter)
            self.remove_bracket()
            opener.node.unlink()
            if not is_image:
                o = self.brackets
                while o is not None:
                    if not o.image:
                        o.active = False
                    o = o.previous
            return True
        self.remove_bracket()
        self.pos = startpos
        block.append_child(text("]"))
        return True

    def parse_string(self, block: Node) -> bool:
        m = self.match(RE_MAIN)
        if m is None:
            return False
        block.append_child(text(m))
        return True

    def parse_newline(self, block: Node) -> bool:
        self.pos += 1
        lastc = block.last_child
        if lastc is not None and lastc.type == "text" and lastc.literal.endswith(" "):
            hard = lastc.literal.endswith("  ")
            lastc.literal = lastc.literal.rstrip(" ")
            block.append_child(Node("linebreak" if hard else "softbreak"))
        else:
            block.append_child(Node("softbreak"))
        self.match(RE_INITIAL_SPACE)
        return True

    # --- link reference definitions -----------------------------------------
    def parse_reference(self, s: str, refmap: dict) -> int:
        self.subject = s
        self.pos = 0
        startpos = 0
        n = self.parse_link_label()
        if n == 0:
            return 0
        rawlabel = self.subject[:n]
        if self.peek() == ":":
            self.pos += 1
        else:
            self.pos = startpos
            return 0
        self.spnl()
        dest = self.parse_link_destination()
        if dest is None:
            self.pos = startpos
            return 0
        beforetitle = self.pos
        self.spnl()
        title = None
        if self.pos != beforetitle:
            title = self.parse_link_title()
        if title is None:
            self.pos = beforetitle
        at_line_end = True
        if self.match(RE_SPACE_AT_EOL) is None:
            if title is None:
                at_line_end = False
            else:
                title = None
                self.pos = beforetitle
                at_line_end = self.match(RE_SPACE_AT_EOL) is not None
        if not at_line_end:
            self.pos = startpos
            return 0
        normlabel = normalize_reference(rawlabel)
        if normlabel == "":
            self.pos = startpos
            return 0
        if normlabel not in refmap:
            refmap[normlabel] = (dest, "" if title is None else title)
        return self.pos - startpos

    # --- driver ----------------------------------------------------------
    def parse_inline(self, block: Node) -> bool:
        c = self.peek()
        if c == "":
            return False
        if c == "\n":
            res = self.parse_newline(block)
        elif c == "\\":
            res = self.parse_backslash(block)
        elif c == "`":
            res = self.parse_backticks(block)
        elif c in "*_":
            res = self.handle_delim(c, block)
        elif c == "[":
            res = self.parse_open_bracket(block)
        elif c == "!":
            res = self.parse_bang(block)
        elif c == "]":
            res = self.parse_close_bracket(block)
        elif c == "<":
            res = self.parse_autolink(block)
        elif c in "&'\"":
            res = False
        else:
            res = self.parse_string(block)
        if not res:
            self.pos += 1
            block.append_child(text(c))
        return True

    def parse(self, block: Node) -> None:
        self.subject = block.string_content.strip()
        self.pos = 0
        self.delimiters = None
        self.brackets = None
        while self.parse_inline(block):
            pass
        block.string_content = ""
        self.process_emphasis(None)
