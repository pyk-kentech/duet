"""HTML output in the same layout as the CommonMark reference renderer."""

from __future__ import annotations

import re

from .node import Node

_XML_SPECIAL = re.compile(r'[&<>"]')
_REPL = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def escape_xml(s: str) -> str:
    return _XML_SPECIAL.sub(lambda m: _REPL[m.group(0)], s)


class HtmlRenderer:
    def __init__(self) -> None:
        self.buf: list[str] = []
        self.last_out = "\n"
        self.disable_tags = 0

    def lit(self, s: str) -> None:
        self.buf.append(s)
        self.last_out = s

    def out(self, s: str) -> None:
        self.lit(escape_xml(s))

    def cr(self) -> None:
        if self.last_out != "\n":
            self.lit("\n")

    def tag(self, name: str, attrs: list[tuple[str, str]] | None = None, selfclosing: bool = False) -> None:
        if self.disable_tags > 0:
            return
        s = "<" + name
        for k, v in attrs or ():
            s += " " + k + '="' + v + '"'
        if selfclosing:
            s += " /"
        s += ">"
        self.buf.append(s)
        self.last_out = ">"

    def render(self, doc: Node) -> str:
        self._node(doc)
        return "".join(self.buf)

    def _node(self, node: Node) -> None:
        handler = getattr(self, "_" + node.type)
        handler(node, True)
        if node.is_container:
            for child in node.children():
                self._node(child)
            handler(node, False)

    # --- node handlers ---------------------------------------------------------
    def _document(self, node: Node, entering: bool) -> None:
        pass

    def _text(self, node: Node, entering: bool) -> None:
        self.out(node.literal)

    def _softbreak(self, node: Node, entering: bool) -> None:
        self.lit("\n")

    def _linebreak(self, node: Node, entering: bool) -> None:
        self.tag("br", [], True)
        self.cr()

    def _link(self, node: Node, entering: bool) -> None:
        if entering:
            attrs = [("href", escape_xml(node.destination))]
            if node.title:
                attrs.append(("title", escape_xml(node.title)))
            self.tag("a", attrs)
        else:
            self.tag("/a")

    def _image(self, node: Node, entering: bool) -> None:
        if entering:
            if self.disable_tags == 0:
                self.lit('<img src="' + escape_xml(node.destination) + '" alt="')
            self.disable_tags += 1
        else:
            self.disable_tags -= 1
            if self.disable_tags == 0:
                if node.title:
                    self.lit('" title="' + escape_xml(node.title))
                self.lit('" />')

    def _emph(self, node: Node, entering: bool) -> None:
        self.tag("em" if entering else "/em")

    def _strong(self, node: Node, entering: bool) -> None:
        self.tag("strong" if entering else "/strong")

    def _paragraph(self, node: Node, entering: bool) -> None:
        grandparent = node.parent.parent if node.parent is not None else None
        if grandparent is not None and grandparent.type == "list" and grandparent.list_data["tight"]:
            return
        if entering:
            self.cr()
            self.tag("p")
        else:
            self.tag("/p")
            self.cr()

    def _heading(self, node: Node, entering: bool) -> None:
        name = "h%d" % node.level
        if entering:
            self.cr()
            self.tag(name)
        else:
            self.tag("/" + name)
            self.cr()

    def _code(self, node: Node, entering: bool) -> None:
        self.tag("code")
        self.out(node.literal)
        self.tag("/code")

    def _code_block(self, node: Node, entering: bool) -> None:
        words = re.split(r"\s+", node.info) if node.info else []
        attrs = []
        if words and words[0]:
            cls = escape_xml(words[0])
            if not cls.startswith("language-"):
                cls = "language-" + cls
            attrs.append(("class", cls))
        self.cr()
        self.tag("pre")
        self.tag("code", attrs)
        self.out(node.literal)
        self.tag("/code")
        self.tag("/pre")
        self.cr()

    def _thematic_break(self, node: Node, entering: bool) -> None:
        self.cr()
        self.tag("hr", [], True)
        self.cr()

    def _block_quote(self, node: Node, entering: bool) -> None:
        self.cr()
        self.tag("blockquote" if entering else "/blockquote")
        self.cr()

    def _list(self, node: Node, entering: bool) -> None:
        ld = node.list_data
        name = "ul" if ld["type"] == "bullet" else "ol"
        if entering:
            attrs = []
            if ld["start"] is not None and ld["start"] != 1:
                attrs.append(("start", str(ld["start"])))
            self.cr()
            self.tag(name, attrs)
            self.cr()
        else:
            self.cr()
            self.tag("/" + name)
            self.cr()

    def _item(self, node: Node, entering: bool) -> None:
        if entering:
            self.tag("li")
        else:
            self.tag("/li")
            self.cr()
