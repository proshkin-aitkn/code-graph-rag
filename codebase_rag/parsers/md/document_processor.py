from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from ... import constants as cs
from ..handlers.markdown import MarkdownHandler
from ..utils import safe_decode_text

if TYPE_CHECKING:
    from tree_sitter import Node

    from ...services import IngestorProtocol
    from ...types_defs import FunctionRegistryTrieProtocol, PropertyDict


class MarkdownDocumentProcessor:
    """Processes markdown documents and extracts structure into the knowledge graph."""

    def __init__(
        self,
        ingestor: IngestorProtocol,
        repo_path: Path,
        project_name: str,
        function_registry: FunctionRegistryTrieProtocol,
    ) -> None:
        self.ingestor = ingestor
        self.repo_path = repo_path
        self.project_name = project_name
        self.function_registry = function_registry
        self.handler = MarkdownHandler()

    def process_document(self, file_path: Path, root_node: Node) -> None:
        """Process a markdown document and extract its structure.

        Args:
            file_path: Path to the markdown file
            root_node: Root AST node from tree-sitter
        """
        relative_path = file_path.relative_to(self.repo_path)
        doc_path = str(relative_path)

        path_parts = relative_path.with_suffix("").parts
        doc_qualified_name = cs.SEPARATOR_DOT.join([self.project_name, *path_parts])

        title = self._extract_document_title(root_node, file_path)

        doc_props: PropertyDict = {
            cs.KEY_PATH: doc_path,
            cs.KEY_NAME: file_path.name,
            cs.KEY_QUALIFIED_NAME: doc_qualified_name,
            "title": title,
        }

        logger.info(f"Processing markdown document: {doc_path}")
        self.ingestor.ensure_node_batch(cs.NodeLabel.DOCUMENT, doc_props)

        self._process_headings(root_node, doc_path, file_path)

    def _extract_document_title(self, root_node: Node, file_path: Path) -> str:
        """Extract document title from first H1 heading or filename."""
        for child in self._walk_tree(root_node):
            if child.type in (cs.TS_MD_ATX_HEADING, cs.TS_MD_SETEXT_HEADING):
                level = self.handler.extract_heading_level(child)
                if level == 1:
                    title = self.handler.extract_heading_text(child)
                    if title:
                        return title.strip()
                    break

        return file_path.stem

    def _process_headings(
        self, root_node: Node, doc_path: str, file_path: Path
    ) -> None:
        """Process all headings in the document and create Section nodes."""
        section_stack: list[tuple[int, str]] = []
        section_counter = 0

        for node in self._walk_tree(root_node):
            if node.type in (cs.TS_MD_ATX_HEADING, cs.TS_MD_SETEXT_HEADING):
                level = self.handler.extract_heading_level(node)
                heading_text = self.handler.extract_heading_text(node)

                if not heading_text:
                    continue

                section_counter += 1
                section_name = self._sanitize_section_name(heading_text)
                section_qn = (
                    f"{self.project_name}.{doc_path}#{section_name}_{section_counter}"
                )

                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()

                section_props: PropertyDict = {
                    cs.KEY_QUALIFIED_NAME: section_qn,
                    cs.KEY_NAME: heading_text.strip(),
                    "level": level,
                    "content": self._extract_section_content(node),
                    cs.KEY_START_LINE: node.start_point[0] + 1,
                    cs.KEY_END_LINE: node.end_point[0] + 1,
                }

                logger.debug(f"Found section: {heading_text} (level {level})")
                self.ingestor.ensure_node_batch(cs.NodeLabel.SECTION, section_props)

                if section_stack:
                    parent_qn = section_stack[-1][1]
                    self.ingestor.ensure_relationship_batch(
                        (cs.NodeLabel.SECTION, cs.KEY_QUALIFIED_NAME, parent_qn),
                        cs.RelationshipType.CONTAINS_SECTION,
                        (cs.NodeLabel.SECTION, cs.KEY_QUALIFIED_NAME, section_qn),
                    )
                else:
                    self.ingestor.ensure_relationship_batch(
                        (cs.NodeLabel.DOCUMENT, cs.KEY_PATH, doc_path),
                        cs.RelationshipType.CONTAINS_SECTION,
                        (cs.NodeLabel.SECTION, cs.KEY_QUALIFIED_NAME, section_qn),
                    )

                section_stack.append((level, section_qn))

                self._process_code_blocks_in_section(
                    node, section_qn, doc_path, file_path
                )

    def _process_code_blocks_in_section(
        self, heading_node: Node, section_qn: str, doc_path: str, file_path: Path
    ) -> None:
        """Process code blocks that follow a heading until the next heading."""
        current = heading_node.next_sibling
        code_block_counter = 0

        while current is not None:
            if current.type in (cs.TS_MD_ATX_HEADING, cs.TS_MD_SETEXT_HEADING):
                break

            if self.handler.is_code_block(current):
                code_block_counter += 1
                self._process_code_block(
                    current, section_qn, doc_path, code_block_counter
                )

            for child in self._walk_tree(current):
                if self.handler.is_code_block(child):
                    code_block_counter += 1
                    self._process_code_block(
                        child, section_qn, doc_path, code_block_counter
                    )

            current = current.next_sibling

    def _process_code_block(
        self,
        node: Node,
        section_qn: str,
        doc_path: str,
        counter: int,
    ) -> None:
        """Create a CodeExample node for a code block."""
        language = self.handler.extract_code_block_language(node) or ""
        content = self.handler.extract_code_block_content(node) or ""

        code_qn = f"{section_qn}:code_{counter}"

        code_props: PropertyDict = {
            cs.KEY_QUALIFIED_NAME: code_qn,
            "language": language,
            "content": content,
            cs.KEY_START_LINE: node.start_point[0] + 1,
            cs.KEY_END_LINE: node.end_point[0] + 1,
        }

        logger.debug(
            f"Found code example: {language} at line {node.start_point[0] + 1}"
        )
        self.ingestor.ensure_node_batch(cs.NodeLabel.CODE_EXAMPLE, code_props)

        self.ingestor.ensure_relationship_batch(
            (cs.NodeLabel.SECTION, cs.KEY_QUALIFIED_NAME, section_qn),
            cs.RelationshipType.CONTAINS_CODE_EXAMPLE,
            (cs.NodeLabel.CODE_EXAMPLE, cs.KEY_QUALIFIED_NAME, code_qn),
        )

        self._link_code_example_to_entities(code_qn, content, language)

    def _link_code_example_to_entities(
        self, code_qn: str, content: str, language: str
    ) -> None:
        """Link code examples to actual code entities in the graph.

        This attempts to find functions/classes referenced in the code example
        and creates DOCUMENTS relationships to them.
        """
        if not content:
            return

        potential_names = self._extract_potential_identifiers(content, language)

        for name in potential_names:
            matches = self.function_registry.find_ending_with(name)
            for match in matches[:3]:
                entity_type = self.function_registry.get(match)
                if entity_type:
                    target_label = self._get_node_label_for_type(entity_type)
                    if target_label:
                        self.ingestor.ensure_relationship_batch(
                            (cs.NodeLabel.CODE_EXAMPLE, cs.KEY_QUALIFIED_NAME, code_qn),
                            cs.RelationshipType.DOCUMENTS,
                            (target_label, cs.KEY_QUALIFIED_NAME, match),
                        )
                        logger.debug(f"Linked code example to {match}")

    def _extract_potential_identifiers(self, content: str, language: str) -> list[str]:
        """Extract potential function/class names from code content."""
        identifiers: list[str] = []

        import re

        if language in ("python", "py"):
            func_pattern = r"def\s+(\w+)\s*\("
            class_pattern = r"class\s+(\w+)\s*[:\(]"
        elif language in ("javascript", "js", "typescript", "ts"):
            func_pattern = r"(?:function\s+(\w+)|(\w+)\s*(?:=|:)\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>))"
            class_pattern = r"class\s+(\w+)"
        elif language in ("rust", "rs"):
            func_pattern = r"fn\s+(\w+)\s*[<\(]"
            class_pattern = r"(?:struct|enum|trait|impl)\s+(\w+)"
        elif language in ("java", "kotlin"):
            func_pattern = (
                r"(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\("
            )
            class_pattern = r"class\s+(\w+)"
        elif language in ("go"):
            func_pattern = r"func\s+(?:\([^)]+\)\s+)?(\w+)\s*\("
            class_pattern = r"type\s+(\w+)\s+struct"
        elif language in ("cpp", "c++", "c"):
            func_pattern = r"(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*\{"
            class_pattern = r"class\s+(\w+)"
        else:
            func_pattern = r"(?:def|fn|func|function)\s+(\w+)"
            class_pattern = r"class\s+(\w+)"

        for pattern in [func_pattern, class_pattern]:
            for match in re.finditer(pattern, content):
                for group in match.groups():
                    if group and len(group) > 2:
                        identifiers.append(group)

        return list(set(identifiers))

    def _get_node_label_for_type(self, entity_type: str) -> cs.NodeLabel | None:
        """Convert entity type string to NodeLabel."""
        type_map = {
            "Function": cs.NodeLabel.FUNCTION,
            "Method": cs.NodeLabel.METHOD,
            "Class": cs.NodeLabel.CLASS,
        }
        return type_map.get(entity_type)

    def _extract_section_content(self, heading_node: Node) -> str:
        """Extract the content following a heading until the next heading."""
        content_parts: list[str] = []
        current = heading_node.next_sibling

        while current is not None:
            if current.type in (cs.TS_MD_ATX_HEADING, cs.TS_MD_SETEXT_HEADING):
                break
            text = safe_decode_text(current)
            if text:
                content_parts.append(text.strip())
            current = current.next_sibling

        return "\n".join(content_parts)[:1000]

    def _sanitize_section_name(self, name: str) -> str:
        """Create a URL-safe section identifier from heading text."""
        import re

        sanitized = re.sub(r"[^\w\s-]", "", name.lower())
        sanitized = re.sub(r"[\s_]+", "-", sanitized)
        return sanitized.strip("-")[:50]

    def _walk_tree(self, node: Node) -> list[Node]:
        """Walk the AST tree and yield all nodes."""
        nodes: list[Node] = [node]
        for child in node.children:
            nodes.extend(self._walk_tree(child))
        return nodes
