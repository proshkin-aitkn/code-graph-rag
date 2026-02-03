from __future__ import annotations

from typing import TYPE_CHECKING

from ... import constants as cs
from ..utils import safe_decode_text
from .base import BaseLanguageHandler

if TYPE_CHECKING:
    from ...types_defs import ASTNode


class MarkdownHandler(BaseLanguageHandler):
    """Handler for parsing markdown documents."""

    def extract_heading_level(self, node: ASTNode) -> int:
        """Extract the heading level (1-6) from a heading node."""
        if node.type == cs.TS_MD_SETEXT_HEADING:
            for child in node.children:
                if child.type == "setext_h1_underline":
                    return 1
                if child.type == "setext_h2_underline":
                    return 2
            return 1

        if node.type == cs.TS_MD_ATX_HEADING:
            for child in node.children:
                if child.type in cs.MD_HEADING_MARKERS:
                    marker_index = cs.MD_HEADING_MARKERS.index(child.type)
                    return marker_index + 1
            return 1

        return 0

    def extract_heading_text(self, node: ASTNode) -> str | None:
        """Extract the text content from a heading node."""
        if node.type not in (cs.TS_MD_ATX_HEADING, cs.TS_MD_SETEXT_HEADING):
            return None

        for child in node.children:
            if child.type == cs.TS_MD_HEADING_CONTENT:
                return self._extract_inline_text(child)
            if child.type == cs.TS_MD_INLINE:
                return safe_decode_text(child)
            if child.type == cs.TS_MD_PARAGRAPH:
                return self._extract_inline_text(child)

        return None

    def _extract_inline_text(self, node: ASTNode) -> str | None:
        """Extract text from inline content nodes."""
        for child in node.children:
            if child.type == cs.TS_MD_INLINE:
                return safe_decode_text(child)
        return safe_decode_text(node)

    def is_code_block(self, node: ASTNode) -> bool:
        """Check if a node is a code block."""
        return node.type in (cs.TS_MD_FENCED_CODE_BLOCK, cs.TS_MD_INDENTED_CODE_BLOCK)

    def extract_code_block_language(self, node: ASTNode) -> str | None:
        """Extract the language identifier from a fenced code block."""
        if node.type != cs.TS_MD_FENCED_CODE_BLOCK:
            return None

        for child in node.children:
            if child.type == cs.TS_MD_INFO_STRING:
                info_text = safe_decode_text(child)
                if info_text:
                    return info_text.split()[0].strip()
            if child.type == cs.TS_MD_LANGUAGE:
                return safe_decode_text(child)

        return None

    def extract_code_block_content(self, node: ASTNode) -> str | None:
        """Extract the content from a code block."""
        if node.type == cs.TS_MD_FENCED_CODE_BLOCK:
            for child in node.children:
                if child.type == cs.TS_MD_CODE_FENCE_CONTENT:
                    return safe_decode_text(child)
            return self._extract_fenced_code_content(node)

        if node.type == cs.TS_MD_INDENTED_CODE_BLOCK:
            return safe_decode_text(node)

        return None

    def _extract_fenced_code_content(self, node: ASTNode) -> str | None:
        """Extract code content from fenced code block by finding text between fences."""
        content_parts: list[str] = []
        in_content = False

        for child in node.children:
            if child.type in ("fenced_code_block_delimiter", "code_fence_content"):
                if child.type == "fenced_code_block_delimiter":
                    if not in_content:
                        in_content = True
                    else:
                        break
                elif in_content:
                    text = safe_decode_text(child)
                    if text:
                        content_parts.append(text)
            elif in_content and child.text:
                text = safe_decode_text(child)
                if text:
                    content_parts.append(text)

        return "\n".join(content_parts) if content_parts else None

    def extract_link_destination(self, node: ASTNode) -> str | None:
        """Extract the URL/destination from a link node."""
        if node.type != cs.TS_MD_LINK:
            return None

        for child in node.children:
            if child.type == cs.TS_MD_LINK_DESTINATION:
                return safe_decode_text(child)

        return None

    def extract_link_text(self, node: ASTNode) -> str | None:
        """Extract the text content from a link node."""
        if node.type != cs.TS_MD_LINK:
            return None

        for child in node.children:
            if child.type == cs.TS_MD_LINK_TEXT:
                return safe_decode_text(child)

        return None
