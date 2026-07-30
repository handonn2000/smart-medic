"""L2 · the indent stack → a section tree and an ancestor path.

Three indent tiers `{0, 4, 8}` are enough for this corpus; a fourth never appears.
A section opens on a header line and closes when a header at the same or a
shallower level arrives.

What this is FOR: `section(offset)` is the assertion scope. "Tiền sử bệnh nội
khoa:" over a bullet list is why those bullets are `isHistorical`, and getting the
tree wrong puts the flag on the wrong half of the document.

One rule earns its keep beyond plain headers: a short unpunctuated line followed
by a bullet also opens a section. In `42.txt`, "Thuốc trước khi nhập viện" has no
colon and no enumerator, yet the three drug names under it belong to nothing else.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

from .lines import HEADER_KINDS, Line, LineKind
from .rules import LayoutRules, default_rules

__all__ = ["SectionNode", "build_outline", "ROOT_TITLE"]

ROOT_TITLE = "<document>"


@dataclass
class SectionNode:
    """A span of the document with a title and a place in the tree."""

    id: int
    title: str
    kind: LineKind | None          # None for the synthetic root
    level: int
    start: int                     # raw offset where the scope starts
    end: int                       # raw offset where it ends, exclusive
    header_line: int | None = None
    parent: "SectionNode | None" = field(default=None, repr=False)
    children: list["SectionNode"] = field(default_factory=list, repr=False)

    def ancestors(self) -> tuple["SectionNode", ...]:
        """Root first, this node last."""
        chain: list[SectionNode] = []
        node: SectionNode | None = self
        while node is not None:
            chain.append(node)
            node = node.parent
        return tuple(reversed(chain))

    def path(self) -> tuple[str, ...]:
        """Ancestor titles, root first — the section context of an offset."""
        return tuple(n.title for n in self.ancestors())

    def contains(self, offset: int) -> bool:
        return self.start <= offset < self.end

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def _opens_section(
    line: Line, following: list[Line], r: LayoutRules
) -> bool:
    if line.kind.value in r.open_on:
        return True
    if line.kind is not LineKind.PROSE:
        return False
    body = line.content.strip()
    if not body or len(body) > r.prose_header_max_chars:
        return False
    if r.prose_header_forbidden_tail.search(body):
        return False
    if not r.prose_header_requires_following_bullet:
        return True
    for nxt in following:
        if nxt.kind is LineKind.BLANK:
            continue
        return nxt.kind is LineKind.BULLET and nxt.level >= line.level
    return False


def build_outline(
    lines: tuple[Line, ...], doc_length: int, rules: LayoutRules | None = None
) -> SectionNode:
    """Build the tree and return its root, which spans the whole document."""
    r = rules or default_rules()
    root = SectionNode(
        id=0, title=ROOT_TITLE, kind=None, level=-1, start=0, end=doc_length
    )
    stack: list[SectionNode] = [root]
    next_id = 1

    for i, line in enumerate(lines):
        if line.kind is LineKind.BLANK:
            continue
        ahead = lines[i + 1 : i + 1 + r.outline_lookahead_lines]
        if not _opens_section(line, list(ahead), r):
            continue

        # close every section at this level or deeper
        while len(stack) > 1 and stack[-1].level >= line.level:
            stack.pop().end = line.start

        parent = stack[-1]
        title = (line.label or line.content).strip()
        node = SectionNode(
            id=next_id,
            title=title,
            kind=line.kind,
            level=line.level,
            start=line.start,
            end=parent.end,
            header_line=line.index,
            parent=parent,
        )
        next_id += 1
        parent.children.append(node)
        stack.append(node)

    while len(stack) > 1:
        stack.pop().end = doc_length
    return root


class SectionIndex:
    """`section(offset)` — the deepest node containing the offset.

    Siblings never overlap and are stored in document order, so a binary search
    at each level descends the tree in O(depth · log children); depth is 3.
    """

    def __init__(self, root: SectionNode):
        self._root = root
        self._starts = {
            id(n): [c.start for c in n.children] for n in root.walk()
        }

    def __call__(self, offset: int) -> SectionNode:
        node = self._root
        while True:
            starts = self._starts[id(node)]
            i = bisect_right(starts, offset) - 1
            if i < 0 or not node.children[i].contains(offset):
                return node
            node = node.children[i]
