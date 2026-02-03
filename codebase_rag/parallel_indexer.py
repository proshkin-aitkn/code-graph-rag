from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .graph_updater import GraphUpdater

PROGRESS_LOG = Path("/tmp/graph-code-progress.log")


def _log_progress(message: str) -> None:
    """Write progress message to the progress log file."""
    try:
        with PROGRESS_LOG.open("a") as f:
            import datetime

            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            f.write(f"[{timestamp}] {message}\n")
            f.flush()
    except Exception:
        pass


def _worker_process(
    worker_id: int,
    file_paths: list[str],
    repo_path_str: str,
    host: str,
    port: int,
    batch_size: int,
    generate_embeddings: bool,
) -> int:
    """
    Worker process that handles a group of files from start to finish.
    Retries failed files up to 3 times.

    Returns number of files processed.
    """
    import time
    from pathlib import Path

    from loguru import logger

    from .graph_updater import GraphUpdater
    from .parser_loader import load_parsers
    from .services.graph_service import MemgraphIngestor

    stagger_delay = worker_id * 0.3
    if stagger_delay > 0:
        time.sleep(stagger_delay)

    repo_path = Path(repo_path_str)
    file_count = len(file_paths)

    parallel_batch_size = min(batch_size, 50)

    logger.info(
        f"Worker {worker_id}: Starting with {file_count} files (batch_size={parallel_batch_size})"
    )
    _log_progress(f"Worker {worker_id}: Starting with {file_count} files")

    total_processed = 0
    max_retries = 3
    failed_files_prev = file_paths

    for retry_round in range(max_retries):
        try:
            parsers, queries = load_parsers()

            ingestor = MemgraphIngestor(
                host=host, port=port, batch_size=parallel_batch_size
            )

            with ingestor:
                updater = GraphUpdater(
                    ingestor=ingestor,
                    repo_path=repo_path,
                    parsers=parsers,
                    queries=queries,
                )

                processed = 0
                failed_files = []

                files_to_process = failed_files_prev
                for i, fp_str in enumerate(files_to_process):
                    filepath = Path(fp_str)
                    try:
                        content = filepath.read_bytes()
                        updater._process_single_file_with_content(filepath, content)
                        processed += 1

                        if retry_round == 0 and (i + 1) % 50 == 0:
                            logger.info(
                                f"Worker {worker_id}: Processed {i + 1}/{len(files_to_process)} files"
                            )
                            _log_progress(
                                f"Worker {worker_id}: {i + 1}/{len(files_to_process)} files"
                            )
                    except Exception as e:
                        failed_files.append(fp_str)
                        if retry_round == 0:
                            logger.debug(
                                f"Worker {worker_id}: Failed {filepath.name}: {e}"
                            )

                if retry_round == 0 and generate_embeddings:
                    logger.info(f"Worker {worker_id}: Generating embeddings...")
                    _log_progress(f"Worker {worker_id}: Generating embeddings...")
                    _generate_embeddings_for_files(
                        updater, file_paths, repo_path, worker_id
                    )

            total_processed += processed
            failed_files_prev = failed_files

            if not failed_files:
                break

            if retry_round < max_retries - 1:
                logger.info(
                    f"Worker {worker_id}: Retrying {len(failed_files)} failed files (round {retry_round + 2})"
                )
                time.sleep(1.0 + worker_id * 0.2)

        except Exception as e:
            logger.error(f"Worker {worker_id}: Error in round {retry_round + 1}: {e}")
            if retry_round == max_retries - 1:
                _log_progress(f"Worker {worker_id}: ERROR after retries - {e}")
            time.sleep(2.0)

    logger.info(f"Worker {worker_id}: Completed {total_processed}/{file_count} files")
    _log_progress(f"Worker {worker_id}: DONE - {total_processed}/{file_count} files")
    return total_processed


def _generate_embeddings_for_files(
    updater: GraphUpdater,  # noqa: F821
    file_paths: list[str],
    repo_path: Path,  # noqa: F821
    worker_id: int,
) -> None:
    """Generate embeddings only for functions in the specified files."""
    from pathlib import Path

    from loguru import logger

    from . import constants as cs
    from .config import settings
    from .services import QueryProtocol
    from .utils.dependencies import has_semantic_dependencies

    if not has_semantic_dependencies():
        return

    if not isinstance(updater.ingestor, QueryProtocol):
        return

    try:
        from .embedder import embed_code
        from .vector_store import store_embedding

        relative_paths = set()
        for fp_str in file_paths:
            try:
                rel_path = str(Path(fp_str).relative_to(repo_path))
                relative_paths.add(rel_path)
            except ValueError:
                relative_paths.add(fp_str)

        results = updater.ingestor.fetch_all(
            cs.CYPHER_QUERY_EMBEDDINGS,
            {"project_name": updater.project_name + "."},
        )

        if not results:
            return

        filtered_results = []
        for row in results:
            file_path = row.get(cs.KEY_PATH)
            if file_path and str(file_path) in relative_paths:
                filtered_results.append(row)

        if not filtered_results:
            logger.info(
                f"Worker {worker_id}: No functions to embed from {len(file_paths)} files"
            )
            return

        logger.info(
            f"Worker {worker_id}: Generating embeddings for {len(filtered_results)} functions"
        )

        embedded_count = 0
        for row in filtered_results:
            parsed = updater._parse_embedding_result(row)
            if parsed is None:
                continue

            node_id = parsed[cs.KEY_NODE_ID]
            qualified_name = parsed[cs.KEY_QUALIFIED_NAME]
            start_line = parsed.get(cs.KEY_START_LINE)
            end_line = parsed.get(cs.KEY_END_LINE)
            file_path = parsed.get(cs.KEY_PATH)

            if start_line is None or end_line is None or file_path is None:
                continue

            source_code = updater._extract_source_code(
                qualified_name, file_path, start_line, end_line
            )
            if source_code:
                try:
                    embedding = embed_code(source_code)
                    store_embedding(node_id, embedding, qualified_name)
                    embedded_count += 1

                    if embedded_count % settings.EMBEDDING_PROGRESS_INTERVAL == 0:
                        logger.debug(
                            f"Worker {worker_id}: Embedded {embedded_count}/{len(filtered_results)}"
                        )
                except Exception as e:
                    logger.warning(
                        f"Worker {worker_id}: Failed to embed {qualified_name}: {e}"
                    )

        _generate_section_embeddings_for_files(
            updater, relative_paths, embed_code, store_embedding, worker_id
        )

        logger.info(f"Worker {worker_id}: Completed {embedded_count} embeddings")

    except Exception as e:
        logger.warning(f"Worker {worker_id}: Embedding generation failed: {e}")


def _generate_section_embeddings_for_files(
    updater: GraphUpdater,  # noqa: F821
    relative_paths: set[str],
    embed_func: Callable[[str], list[float]],  # noqa: F821
    store_func: Callable[[int, list[float], str], None],  # noqa: F821
    worker_id: int,
) -> None:
    """Generate embeddings for markdown sections from specified files."""
    from loguru import logger

    from . import constants as cs
    from .services import QueryProtocol

    if not isinstance(updater.ingestor, QueryProtocol):
        return

    results = updater.ingestor.fetch_all(
        cs.CYPHER_QUERY_SECTION_EMBEDDINGS,
        {"project_name": updater.project_name + "."},
    )

    if not results:
        return

    filtered_results = []
    for row in results:
        qn = row.get(cs.KEY_QUALIFIED_NAME, "")
        if isinstance(qn, str):
            for rel_path in relative_paths:
                path_qn = rel_path.replace("/", ".").replace("\\", ".")
                if path_qn.endswith(".md"):
                    path_qn = path_qn[:-3]
                if path_qn in qn:
                    filtered_results.append(row)
                    break

    if not filtered_results:
        return

    embedded_count = 0
    for row in filtered_results:
        node_id = row.get(cs.KEY_NODE_ID)
        qualified_name = row.get(cs.KEY_QUALIFIED_NAME)
        name = row.get(cs.KEY_NAME)
        content = row.get("content")

        if not isinstance(node_id, int) or not isinstance(qualified_name, str):
            continue

        name_str = str(name) if name else ""
        content_str = str(content) if content else ""
        text_to_embed = f"# {name_str}\n\n{content_str}" if content_str else name_str

        if not text_to_embed:
            continue

        try:
            embedding = embed_func(text_to_embed)
            store_func(node_id, embedding, qualified_name)
            embedded_count += 1
        except Exception as e:
            logger.warning(
                f"Worker {worker_id}: Failed to embed section {qualified_name}: {e}"
            )

    if embedded_count:
        logger.info(
            f"Worker {worker_id}: Generated {embedded_count} section embeddings"
        )


def _identify_structure_before_parallel(
    repo_path: Path,
    host: str,
    port: int,
    batch_size: int,
) -> None:
    """
    Identify and create Package/Folder structure before parallel file processing.

    This ensures parent nodes exist when workers try to create File->Parent relationships.
    Workers link to Folders by path, so we create Folder nodes for ALL directories
    (including package directories) to ensure relationships can be created.
    """
    from .parser_loader import load_parsers
    from .parsers.structure_processor import StructureProcessor
    from .services.graph_service import MemgraphIngestor
    from .utils.path_utils import should_skip_path

    logger.info("Identifying repository structure (packages, folders)...")
    _log_progress("Identifying repository structure...")

    parsers, queries = load_parsers()
    project_name = repo_path.resolve().name

    with MemgraphIngestor(host=host, port=port, batch_size=batch_size) as ingestor:
        from . import constants as cs

        ingestor.ensure_node_batch(cs.NODE_PROJECT, {cs.KEY_NAME: project_name})

        structure_processor = StructureProcessor(
            ingestor=ingestor,
            repo_path=repo_path,
            project_name=project_name,
            queries=queries,
        )
        structure_processor.identify_structure()

        directories = set()
        for path in repo_path.rglob(cs.GLOB_ALL):
            if path.is_dir() and not should_skip_path(path, repo_path):
                directories.add(path)

        for root in directories:
            relative_root = root.relative_to(repo_path)
            if relative_root != Path("."):
                ingestor.ensure_node_batch(
                    cs.NodeLabel.FOLDER,
                    {cs.KEY_PATH: str(relative_root), cs.KEY_NAME: root.name},
                )

        ingestor.flush_all()

    logger.info("Structure identification complete")
    _log_progress("Structure identification complete")


def run_parallel_indexing(
    file_paths: Sequence[Path],
    repo_path: Path,
    host: str,
    port: int,
    batch_size: int,
    num_workers: int,
    generate_embeddings: bool = True,
) -> int:
    """
    Run parallel indexing by splitting files across worker processes.

    Args:
        file_paths: List of files to process
        repo_path: Repository root path
        host: Memgraph host
        port: Memgraph port
        batch_size: Batch size for DB operations
        num_workers: Number of parallel workers
        generate_embeddings: Whether to generate embeddings

    Returns:
        Total number of files processed
    """
    if not file_paths:
        return 0

    file_count = len(file_paths)

    if num_workers <= 1 or file_count < num_workers * 2:
        logger.info(f"Processing {file_count} files sequentially")
        return _worker_process(
            worker_id=0,
            file_paths=[str(fp) for fp in file_paths],
            repo_path_str=str(repo_path),
            host=host,
            port=port,
            batch_size=batch_size,
            generate_embeddings=generate_embeddings,
        )

    _identify_structure_before_parallel(repo_path, host, port, batch_size)

    groups: list[list[str]] = [[] for _ in range(num_workers)]
    for i, fp in enumerate(file_paths):
        groups[i % num_workers].append(str(fp))

    logger.info(
        f"Splitting {file_count} files across {num_workers} workers "
        f"(~{file_count // num_workers} files each)"
    )

    try:
        PROGRESS_LOG.write_text("")
    except Exception:
        pass
    _log_progress(
        f"=== Starting parallel indexing: {file_count} files, {num_workers} workers ==="
    )

    worker_args = [
        (
            worker_id,
            groups[worker_id],
            str(repo_path),
            host,
            port,
            batch_size,
            generate_embeddings,
        )
        for worker_id in range(num_workers)
        if groups[worker_id]
    ]

    try:
        ctx = mp.get_context("spawn")
    except ValueError:
        ctx = mp.get_context()

    logger.info(f"Starting {len(worker_args)} worker processes...")

    with ctx.Pool(processes=len(worker_args)) as pool:
        async_result = pool.starmap_async(_worker_process, worker_args)
        try:
            results = async_result.get(timeout=600 * len(worker_args))
        except mp.TimeoutError:
            logger.error("Parallel indexing timed out")
            _log_progress("=== TIMEOUT - Parallel indexing timed out ===")
            pool.terminate()
            return 0

    total_processed = sum(results)
    logger.info(
        f"Parallel indexing complete: {total_processed}/{file_count} files processed"
    )
    _log_progress(f"=== COMPLETE: {total_processed}/{file_count} files processed ===")

    return total_processed
