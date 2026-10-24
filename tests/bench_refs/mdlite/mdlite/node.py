"""Document tree nodes (doubly linked, like the CommonMark reference parser)."""

from __future__ import annotations

CONTAINERS = {
    "document", "block_quote", "list", "item", "paragraph", "heading",
    "emph", "strong", "link", "image",
}


class Node:
    def __init__(self, type_: str, start_line: int = 0) -> None:
        self.type = type_
        self.parent: Node | None = None
        self.first_child: Node | None = None
        self.last_child: Node | None = None
        self.prev: Node | None = None
        self.next: Node | None = None
        self.open = True
        self.start_line = start_line
        self.end_line = 0
        self.string_content = ""
        self.literal = ""
        # block-specific
        self.level = 0
        self.list_data: dict | None = None
        self.info = ""
        self.is_fenced = False
        self.fence_char = ""
        self.fence_length = 0
        self.fence_offset = 0
        # link / image
        self.destination = ""
        self.title = ""

    @property
    def is_container(self) -> bool:
        return self.type in CONTAINERS

    def append_child(self, child: Node) -> None:
        child.unlink()
        child.parent = self
        if self.last_child is not None:
            self.last_child.next = child
            child.prev = self.last_child
            self.last_child = child
        else:
            self.first_child = child
            self.last_child = child

    def unlink(self) -> None:
        if self.prev is not None:
            self.prev.next = self.next
        elif self.parent is not None:
            self.parent.first_child = self.next
        if self.next is not None:
            self.next.prev = self.prev
        elif self.parent is not None:
            self.parent.last_child = self.prev
        self.parent = None
        self.next = None
        self.prev = None

    def insert_after(self, sibling: Node) -> None:
        sibling.unlink()
        sibling.next = self.next
        if sibling.next is not None:
            sibling.next.prev = sibling
        sibling.prev = self
        self.next = sibling
        sibling.parent = self.parent
        if sibling.next is None and sibling.parent is not None:
            sibling.parent.last_child = sibling

    def children(self):
        c = self.first_child
        while c is not None:
            nxt = c.next
            yield c
            c = nxt
