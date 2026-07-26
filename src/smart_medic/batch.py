"""Conservative corpus-level post-processing for v3.

The extractor normally works one document at a time.  That is the safest
default, but it cannot recover a redacted medication when an otherwise
identical template is present in another document with the drug visible.  The
resolver below performs one exact, deterministic operation:

* build a local template around every linked plaintext drug;
* replace only the drug anchor with ``<focus>`` while preserving dose, form,
  route and frequency;
* fill an unresolved mask only when all matching templates from *other files*
  agree on the same candidate set.

No fuzzy drug inference is performed here.  Conflicting or weak templates
remain unresolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import norm_text
from .schema import ConceptType, Mention
from .textref import TextRef


_MASK_RE = re.compile(r"\*{3,}")
_TOKEN_RE = re.compile(r"<focus>|<drug>|[^\W_]+(?:[.,][0-9]+)?", re.UNICODE)


@dataclass(frozen=True)
class BatchResolutionStats:
    resolved: int = 0
    exact_line: int = 0
    token_window: int = 0
    conflicts: int = 0


@dataclass(frozen=True)
class _Support:
    filename: str
    candidates: tuple[str, ...]
    kb_rows: tuple[str, ...]
    confidence: float
    surface: str


class CrossDocumentMaskResolver:
    """Resolve masked medications from uniquely agreeing document templates."""

    name = "cross_document_mask_v3_3"
    min_line_words = 4
    min_window_words = 8
    window_tokens = 14

    def __init__(self, *, excluded_support_paths: tuple[str, ...] = ()) -> None:
        # V4 ingredient/brand backoff identifies a medication family, not a
        # fully specified product.  Keeping it out of mask propagation makes
        # the first v4 experiment one controlled change and prevents a broad
        # code from being copied into an information-free redaction.
        self.excluded_support_paths = excluded_support_paths

    def _eligible_support(self, mention: Mention) -> bool:
        return not any(
            mention.provenance.link_path.startswith(prefix)
            for prefix in self.excluded_support_paths
        )

    @staticmethod
    def _line_bounds(raw: str, mention: Mention) -> tuple[int, int]:
        start = raw.rfind("\n", 0, mention.span.start) + 1
        end = raw.find("\n", mention.span.end)
        return start, len(raw) if end < 0 else end

    @staticmethod
    def _focus_shape(mention: Mention) -> str:
        surface = norm_text(mention.span.text)
        if _MASK_RE.search(surface):
            return _MASK_RE.sub("<focus>", surface, count=1)
        anchor = norm_text(mention.provenance.evidence.get("anchor", ""))
        if anchor:
            offset = surface.find(anchor)
            if offset >= 0:
                return surface[:offset] + "<focus>" + surface[offset + len(anchor):]
        return "<focus>"

    def _canonical_line(
        self,
        tref: TextRef,
        focus: Mention,
        mentions: list[Mention],
    ) -> str | None:
        line_start, line_end = self._line_bounds(tref.raw, focus)
        replacements: list[tuple[int, int, str]] = []
        for mention in mentions:
            if (
                mention.type is ConceptType.THUOC
                and line_start <= mention.span.start
                and mention.span.end <= line_end
            ):
                token = self._focus_shape(mention) if mention is focus else "<drug>"
                replacements.append((
                    mention.span.start - line_start,
                    mention.span.end - line_start,
                    token,
                ))

        line = tref.raw[line_start:line_end]
        for start, end, token in sorted(replacements, reverse=True):
            line = line[:start] + token + line[end:]
        canonical = norm_text(_MASK_RE.sub("<drug>", line))
        if canonical.count("<focus>") != 1:
            return None
        words = [
            token for token in _TOKEN_RE.findall(canonical)
            if token not in {"<focus>", "<drug>"}
        ]
        return canonical if len(words) >= self.min_line_words else None

    def _signatures(
        self,
        tref: TextRef,
        focus: Mention,
        mentions: list[Mention],
    ) -> tuple[tuple[str, str], ...]:
        line = self._canonical_line(tref, focus, mentions)
        if line is None:
            return ()
        signatures: list[tuple[str, str]] = [("line", line)]
        tokens = _TOKEN_RE.findall(line)
        try:
            index = tokens.index("<focus>")
        except ValueError:
            return tuple(signatures)
        left = max(0, index - self.window_tokens)
        right = min(len(tokens), index + self.window_tokens + 1)
        window = tokens[left:right]
        words = [token for token in window if token not in {"<focus>", "<drug>"}]
        if len(words) >= self.min_window_words:
            signatures.append(("window", " ".join(window)))
        return tuple(signatures)

    @staticmethod
    def _agreed_support(
        supports: list[_Support], target_file: str
    ) -> tuple[_Support | None, int, bool]:
        usable = [support for support in supports if support.filename != target_file]
        if not usable:
            return None, 0, False
        candidate_sets = {support.candidates for support in usable}
        if len(candidate_sets) != 1:
            return None, len(usable), True
        chosen = min(
            usable,
            key=lambda support: (-support.confidence, support.filename, support.surface),
        )
        return chosen, len(usable), False

    def resolve(self, documents: dict[str, tuple[TextRef, list[Mention]]]) -> BatchResolutionStats:
        index: dict[tuple[str, str], list[_Support]] = {}
        for filename in sorted(documents):
            tref, mentions = documents[filename]
            for mention in mentions:
                if (
                    mention.type is not ConceptType.THUOC
                    or not mention.candidates
                    or _MASK_RE.search(mention.span.text)
                    or not self._eligible_support(mention)
                ):
                    continue
                confidence = mention.provenance.scores.get("confidence", 0.0)
                support = _Support(
                    filename=filename,
                    candidates=mention.candidates,
                    kb_rows=tuple(mention.provenance.kb_rows),
                    confidence=confidence,
                    surface=mention.span.text,
                )
                for signature in self._signatures(tref, mention, mentions):
                    index.setdefault(signature, []).append(support)

        resolved = exact_line = token_window = conflicts = 0
        for filename in sorted(documents):
            tref, mentions = documents[filename]
            for mention in mentions:
                if (
                    mention.type is not ConceptType.THUOC
                    or mention.candidates
                    or not _MASK_RE.search(mention.span.text)
                ):
                    continue
                choices: list[tuple[str, _Support, int]] = []
                saw_conflict = False
                for signature in self._signatures(tref, mention, mentions):
                    support, count, conflict = self._agreed_support(
                        index.get(signature, []), filename
                    )
                    saw_conflict = saw_conflict or conflict
                    if support is not None:
                        choices.append((signature[0], support, count))
                candidate_sets = {choice[1].candidates for choice in choices}
                if saw_conflict or len(candidate_sets) > 1:
                    conflicts += 1
                    continue
                if not choices:
                    continue
                method, support, count = min(
                    choices,
                    key=lambda choice: (0 if choice[0] == "line" else 1, -choice[2]),
                )
                confidence = min(0.94 if method == "line" else 0.90, support.confidence)
                mention.candidates = support.candidates
                mention.provenance.extractor = self.name
                mention.provenance.link_path = "masked_cross_document_template"
                mention.provenance.kb_rows = list(support.kb_rows)
                mention.provenance.scores = {
                    "confidence": confidence,
                    **{f"code:{code}": confidence for code in support.candidates},
                }
                mention.provenance.evidence.update({
                    "resolved_from_file": support.filename,
                    "template_method": method,
                    "template_support": str(count),
                })
                resolved += 1
                if method == "line":
                    exact_line += 1
                else:
                    token_window += 1

        return BatchResolutionStats(resolved, exact_line, token_window, conflicts)
