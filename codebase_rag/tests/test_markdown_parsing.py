from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from tree_sitter import Language, Parser

from codebase_rag import constants as cs
from codebase_rag.parsers.handlers.markdown import MarkdownHandler
from codebase_rag.parsers.md.document_processor import MarkdownDocumentProcessor
from codebase_rag.tests.conftest import (
    create_and_run_updater,
    create_mock_node,
    get_nodes,
    get_relationships,
)

if TYPE_CHECKING:
    from codebase_rag.types_defs import ASTNode

try:
    import tree_sitter_markdown as tsmd

    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False


@pytest.fixture
def markdown_parser() -> Parser | None:
    if not MARKDOWN_AVAILABLE:
        return None
    language = Language(tsmd.language())
    return Parser(language)


@pytest.fixture
def mock_ingestor() -> MagicMock:
    from codebase_rag.services.graph_service import MemgraphIngestor

    return MagicMock(spec=MemgraphIngestor)


@pytest.fixture
def mock_function_registry() -> MagicMock:
    mock = MagicMock()
    mock.find_ending_with.return_value = []
    mock.get.return_value = None
    return mock


class TestMarkdownHandler:
    """Tests for the MarkdownHandler class."""

    def test_extract_heading_level_h1(self) -> None:
        handler = MarkdownHandler()
        h1_marker = create_mock_node(cs.TS_MD_ATX_H1_MARKER, text="#")
        heading = create_mock_node(
            cs.TS_MD_ATX_HEADING,
            children=[h1_marker],
        )
        assert handler.extract_heading_level(heading) == 1

    def test_extract_heading_level_h2(self) -> None:
        handler = MarkdownHandler()
        h2_marker = create_mock_node(cs.TS_MD_ATX_H2_MARKER, text="##")
        heading = create_mock_node(
            cs.TS_MD_ATX_HEADING,
            children=[h2_marker],
        )
        assert handler.extract_heading_level(heading) == 2

    def test_extract_heading_level_h3(self) -> None:
        handler = MarkdownHandler()
        h3_marker = create_mock_node(cs.TS_MD_ATX_H3_MARKER, text="###")
        heading = create_mock_node(
            cs.TS_MD_ATX_HEADING,
            children=[h3_marker],
        )
        assert handler.extract_heading_level(heading) == 3

    def test_extract_heading_text_with_heading_content(self) -> None:
        handler = MarkdownHandler()
        inline = create_mock_node(cs.TS_MD_INLINE, text="My Heading")
        content = create_mock_node(cs.TS_MD_HEADING_CONTENT, children=[inline])
        heading = create_mock_node(cs.TS_MD_ATX_HEADING, children=[content])
        assert handler.extract_heading_text(heading) == "My Heading"

    def test_extract_heading_text_with_inline_directly(self) -> None:
        handler = MarkdownHandler()
        inline = create_mock_node(cs.TS_MD_INLINE, text="Direct Inline")
        heading = create_mock_node(cs.TS_MD_ATX_HEADING, children=[inline])
        assert handler.extract_heading_text(heading) == "Direct Inline"

    def test_extract_heading_text_non_heading_returns_none(self) -> None:
        handler = MarkdownHandler()
        paragraph = create_mock_node(cs.TS_MD_PARAGRAPH, text="Not a heading")
        assert handler.extract_heading_text(paragraph) is None

    def test_is_code_block_fenced(self) -> None:
        handler = MarkdownHandler()
        code_block = create_mock_node(cs.TS_MD_FENCED_CODE_BLOCK)
        assert handler.is_code_block(code_block) is True

    def test_is_code_block_indented(self) -> None:
        handler = MarkdownHandler()
        code_block = create_mock_node(cs.TS_MD_INDENTED_CODE_BLOCK)
        assert handler.is_code_block(code_block) is True

    def test_is_code_block_paragraph_returns_false(self) -> None:
        handler = MarkdownHandler()
        paragraph = create_mock_node(cs.TS_MD_PARAGRAPH)
        assert handler.is_code_block(paragraph) is False

    def test_extract_code_block_language_with_info_string(self) -> None:
        handler = MarkdownHandler()
        info_string = create_mock_node(cs.TS_MD_INFO_STRING, text="python")
        code_block = create_mock_node(
            cs.TS_MD_FENCED_CODE_BLOCK, children=[info_string]
        )
        assert handler.extract_code_block_language(code_block) == "python"

    def test_extract_code_block_language_with_language_node(self) -> None:
        handler = MarkdownHandler()
        language_node = create_mock_node(cs.TS_MD_LANGUAGE, text="javascript")
        code_block = create_mock_node(
            cs.TS_MD_FENCED_CODE_BLOCK, children=[language_node]
        )
        assert handler.extract_code_block_language(code_block) == "javascript"

    def test_extract_code_block_language_no_info(self) -> None:
        handler = MarkdownHandler()
        code_block = create_mock_node(cs.TS_MD_FENCED_CODE_BLOCK, children=[])
        assert handler.extract_code_block_language(code_block) is None

    def test_extract_code_block_language_non_fenced_returns_none(self) -> None:
        handler = MarkdownHandler()
        code_block = create_mock_node(cs.TS_MD_INDENTED_CODE_BLOCK)
        assert handler.extract_code_block_language(code_block) is None

    def test_extract_code_block_content_fenced(self) -> None:
        handler = MarkdownHandler()
        content = create_mock_node(cs.TS_MD_CODE_FENCE_CONTENT, text="print('hello')")
        code_block = create_mock_node(cs.TS_MD_FENCED_CODE_BLOCK, children=[content])
        assert handler.extract_code_block_content(code_block) == "print('hello')"

    def test_extract_code_block_content_indented(self) -> None:
        handler = MarkdownHandler()
        code_block = create_mock_node(
            cs.TS_MD_INDENTED_CODE_BLOCK, text="    indented code"
        )
        assert handler.extract_code_block_content(code_block) == "    indented code"

    def test_extract_link_destination(self) -> None:
        handler = MarkdownHandler()
        dest = create_mock_node(cs.TS_MD_LINK_DESTINATION, text="https://example.com")
        link = create_mock_node(cs.TS_MD_LINK, children=[dest])
        assert handler.extract_link_destination(link) == "https://example.com"

    def test_extract_link_destination_non_link_returns_none(self) -> None:
        handler = MarkdownHandler()
        paragraph = create_mock_node(cs.TS_MD_PARAGRAPH)
        assert handler.extract_link_destination(paragraph) is None

    def test_extract_link_text(self) -> None:
        handler = MarkdownHandler()
        text = create_mock_node(cs.TS_MD_LINK_TEXT, text="Click here")
        link = create_mock_node(cs.TS_MD_LINK, children=[text])
        assert handler.extract_link_text(link) == "Click here"


@pytest.mark.skipif(not MARKDOWN_AVAILABLE, reason="tree-sitter-markdown not available")
class TestMarkdownHandlerWithParser:
    """Tests for MarkdownHandler using actual tree-sitter parsing."""

    def test_extract_heading_level_from_parsed_markdown(
        self, markdown_parser: Parser
    ) -> None:
        handler = MarkdownHandler()
        code = b"# Heading Level 1\n\n## Heading Level 2\n\n### Heading Level 3\n"
        tree = markdown_parser.parse(code)

        headings = [
            node
            for node in self._walk_tree(tree.root_node)
            if node.type == cs.TS_MD_ATX_HEADING
        ]

        assert len(headings) >= 3
        assert handler.extract_heading_level(headings[0]) == 1
        assert handler.extract_heading_level(headings[1]) == 2
        assert handler.extract_heading_level(headings[2]) == 3

    def test_extract_code_block_language_from_parsed_markdown(
        self, markdown_parser: Parser
    ) -> None:
        handler = MarkdownHandler()
        code = b"```python\nprint('hello')\n```\n"
        tree = markdown_parser.parse(code)

        code_blocks = [
            node
            for node in self._walk_tree(tree.root_node)
            if node.type == cs.TS_MD_FENCED_CODE_BLOCK
        ]

        assert len(code_blocks) >= 1
        language = handler.extract_code_block_language(code_blocks[0])
        assert language is not None
        assert "python" in language.lower()

    def _walk_tree(self, node: ASTNode) -> list[ASTNode]:
        """Walk the AST tree and yield all nodes."""
        nodes: list[ASTNode] = [node]
        for child in node.children:
            nodes.extend(self._walk_tree(child))
        return nodes


@pytest.mark.skipif(not MARKDOWN_AVAILABLE, reason="tree-sitter-markdown not available")
class TestMarkdownDocumentProcessor:
    """Tests for the MarkdownDocumentProcessor class."""

    def test_process_document_creates_document_node(
        self,
        markdown_parser: Parser,
        mock_ingestor: MagicMock,
        mock_function_registry: MagicMock,
        temp_repo: Path,
    ) -> None:
        processor = MarkdownDocumentProcessor(
            ingestor=mock_ingestor,
            repo_path=temp_repo,
            project_name="test_project",
            function_registry=mock_function_registry,
        )

        md_file = temp_repo / "README.md"
        md_file.write_text("# My Title\n\nSome content here.\n")

        code = md_file.read_bytes()
        tree = markdown_parser.parse(code)
        processor.process_document(md_file, tree.root_node)

        doc_calls = [
            call
            for call in mock_ingestor.ensure_node_batch.call_args_list
            if call[0][0] == cs.NodeLabel.DOCUMENT
        ]
        assert len(doc_calls) >= 1

        doc_props = doc_calls[0][0][1]
        assert doc_props[cs.KEY_PATH] == "README.md"
        assert doc_props[cs.KEY_NAME] == "README.md"
        assert doc_props["title"] == "My Title"

    def test_process_document_creates_section_nodes(
        self,
        markdown_parser: Parser,
        mock_ingestor: MagicMock,
        mock_function_registry: MagicMock,
        temp_repo: Path,
    ) -> None:
        processor = MarkdownDocumentProcessor(
            ingestor=mock_ingestor,
            repo_path=temp_repo,
            project_name="test_project",
            function_registry=mock_function_registry,
        )

        md_file = temp_repo / "guide.md"
        md_file.write_text(
            "# Installation\n\nInstall the package.\n\n## Prerequisites\n\nYou need Python.\n"
        )

        code = md_file.read_bytes()
        tree = markdown_parser.parse(code)
        processor.process_document(md_file, tree.root_node)

        section_calls = [
            call
            for call in mock_ingestor.ensure_node_batch.call_args_list
            if call[0][0] == cs.NodeLabel.SECTION
        ]
        assert len(section_calls) >= 2

        section_names = [call[0][1][cs.KEY_NAME] for call in section_calls]
        assert "Installation" in section_names
        assert "Prerequisites" in section_names

    def test_process_document_creates_code_example_nodes(
        self,
        markdown_parser: Parser,
        mock_ingestor: MagicMock,
        mock_function_registry: MagicMock,
        temp_repo: Path,
    ) -> None:
        processor = MarkdownDocumentProcessor(
            ingestor=mock_ingestor,
            repo_path=temp_repo,
            project_name="test_project",
            function_registry=mock_function_registry,
        )

        md_file = temp_repo / "example.md"
        md_file.write_text(
            "# Example\n\nHere's some code:\n\n```python\nprint('hello')\n```\n"
        )

        code = md_file.read_bytes()
        tree = markdown_parser.parse(code)
        processor.process_document(md_file, tree.root_node)

        code_calls = [
            call
            for call in mock_ingestor.ensure_node_batch.call_args_list
            if call[0][0] == cs.NodeLabel.CODE_EXAMPLE
        ]
        assert len(code_calls) >= 1

        code_props = code_calls[0][0][1]
        assert "python" in code_props["language"].lower()

    def test_process_document_creates_section_relationships(
        self,
        markdown_parser: Parser,
        mock_ingestor: MagicMock,
        mock_function_registry: MagicMock,
        temp_repo: Path,
    ) -> None:
        processor = MarkdownDocumentProcessor(
            ingestor=mock_ingestor,
            repo_path=temp_repo,
            project_name="test_project",
            function_registry=mock_function_registry,
        )

        md_file = temp_repo / "nested.md"
        md_file.write_text("# Main\n\nIntro.\n\n## Sub Section\n\nDetails.\n")

        code = md_file.read_bytes()
        tree = markdown_parser.parse(code)
        processor.process_document(md_file, tree.root_node)

        contains_section_calls = [
            call
            for call in mock_ingestor.ensure_relationship_batch.call_args_list
            if call[0][1] == cs.RelationshipType.CONTAINS_SECTION
        ]
        assert len(contains_section_calls) >= 2

    def test_process_document_creates_code_example_relationships(
        self,
        markdown_parser: Parser,
        mock_ingestor: MagicMock,
        mock_function_registry: MagicMock,
        temp_repo: Path,
    ) -> None:
        processor = MarkdownDocumentProcessor(
            ingestor=mock_ingestor,
            repo_path=temp_repo,
            project_name="test_project",
            function_registry=mock_function_registry,
        )

        md_file = temp_repo / "code.md"
        md_file.write_text(
            "# Code Examples\n\n```javascript\nconsole.log('hi');\n```\n"
        )

        code = md_file.read_bytes()
        tree = markdown_parser.parse(code)
        processor.process_document(md_file, tree.root_node)

        code_example_calls = [
            call
            for call in mock_ingestor.ensure_relationship_batch.call_args_list
            if call[0][1] == cs.RelationshipType.CONTAINS_CODE_EXAMPLE
        ]
        assert len(code_example_calls) >= 1

    def test_extract_document_title_from_h1(
        self,
        markdown_parser: Parser,
        mock_ingestor: MagicMock,
        mock_function_registry: MagicMock,
        temp_repo: Path,
    ) -> None:
        processor = MarkdownDocumentProcessor(
            ingestor=mock_ingestor,
            repo_path=temp_repo,
            project_name="test_project",
            function_registry=mock_function_registry,
        )

        md_file = temp_repo / "titled.md"
        md_file.write_text("# Custom Title\n\nContent goes here.\n")

        code = md_file.read_bytes()
        tree = markdown_parser.parse(code)
        processor.process_document(md_file, tree.root_node)

        doc_calls = [
            call
            for call in mock_ingestor.ensure_node_batch.call_args_list
            if call[0][0] == cs.NodeLabel.DOCUMENT
        ]
        assert len(doc_calls) >= 1
        assert doc_calls[0][0][1]["title"] == "Custom Title"

    def test_extract_document_title_falls_back_to_filename(
        self,
        markdown_parser: Parser,
        mock_ingestor: MagicMock,
        mock_function_registry: MagicMock,
        temp_repo: Path,
    ) -> None:
        processor = MarkdownDocumentProcessor(
            ingestor=mock_ingestor,
            repo_path=temp_repo,
            project_name="test_project",
            function_registry=mock_function_registry,
        )

        md_file = temp_repo / "no_title.md"
        md_file.write_text("## Subsection\n\nNo H1 here.\n")

        code = md_file.read_bytes()
        tree = markdown_parser.parse(code)
        processor.process_document(md_file, tree.root_node)

        doc_calls = [
            call
            for call in mock_ingestor.ensure_node_batch.call_args_list
            if call[0][0] == cs.NodeLabel.DOCUMENT
        ]
        assert len(doc_calls) >= 1
        assert doc_calls[0][0][1]["title"] == "no_title"


@pytest.mark.skipif(not MARKDOWN_AVAILABLE, reason="tree-sitter-markdown not available")
class TestMarkdownIntegration:
    """Integration tests for markdown processing with GraphUpdater."""

    def test_graph_updater_processes_markdown_files(
        self,
        temp_repo: Path,
        mock_ingestor: MagicMock,
    ) -> None:
        md_file = temp_repo / "README.md"
        md_file.write_text(
            "# Project Title\n\n## Installation\n\nRun the install command.\n\n"
            "```bash\npip install mypackage\n```\n"
        )

        create_and_run_updater(temp_repo, mock_ingestor, skip_if_missing="markdown")

        doc_nodes = get_nodes(mock_ingestor, cs.NodeLabel.DOCUMENT)
        assert len(doc_nodes) >= 1

        section_nodes = get_nodes(mock_ingestor, cs.NodeLabel.SECTION)
        assert len(section_nodes) >= 2

        code_nodes = get_nodes(mock_ingestor, cs.NodeLabel.CODE_EXAMPLE)
        assert len(code_nodes) >= 1

    def test_graph_updater_creates_markdown_relationships(
        self,
        temp_repo: Path,
        mock_ingestor: MagicMock,
    ) -> None:
        md_file = temp_repo / "guide.md"
        md_file.write_text(
            "# Guide\n\nWelcome.\n\n## Getting Started\n\nLet's begin.\n\n"
            "```python\nimport mylib\n```\n"
        )

        create_and_run_updater(temp_repo, mock_ingestor, skip_if_missing="markdown")

        section_rels = get_relationships(
            mock_ingestor, cs.RelationshipType.CONTAINS_SECTION
        )
        assert len(section_rels) >= 2

        code_rels = get_relationships(
            mock_ingestor, cs.RelationshipType.CONTAINS_CODE_EXAMPLE
        )
        assert len(code_rels) >= 1

    def test_multiple_markdown_files_processed(
        self,
        temp_repo: Path,
        mock_ingestor: MagicMock,
    ) -> None:
        (temp_repo / "README.md").write_text("# Main README\n\nIntro.\n")
        (temp_repo / "CONTRIBUTING.md").write_text("# Contributing\n\nHow to help.\n")
        (temp_repo / "docs").mkdir()
        (temp_repo / "docs" / "guide.md").write_text("# Guide\n\nDetailed guide.\n")

        create_and_run_updater(temp_repo, mock_ingestor, skip_if_missing="markdown")

        doc_nodes = get_nodes(mock_ingestor, cs.NodeLabel.DOCUMENT)
        assert len(doc_nodes) >= 3


@pytest.fixture
def temp_repo() -> Path:
    import shutil
    import tempfile

    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)
