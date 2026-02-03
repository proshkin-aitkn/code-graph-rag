from loguru import logger

from . import logs as ls
from .config import settings
from .constants import PAYLOAD_NODE_ID, PAYLOAD_QUALIFIED_NAME
from .utils.dependencies import has_qdrant_client

if has_qdrant_client():
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    _CLIENT: QdrantClient | None = None

    def get_qdrant_client() -> QdrantClient:
        global _CLIENT
        if _CLIENT is None:
            if settings.QDRANT_HOST:
                _CLIENT = QdrantClient(
                    host=settings.QDRANT_HOST, port=settings.QDRANT_PORT
                )
            else:
                _CLIENT = QdrantClient(path=settings.QDRANT_DB_PATH)
            if not _CLIENT.collection_exists(settings.QDRANT_COLLECTION_NAME):
                _CLIENT.create_collection(
                    collection_name=settings.QDRANT_COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=settings.QDRANT_VECTOR_DIM, distance=Distance.COSINE
                    ),
                )
        return _CLIENT

    _QDRANT_LOCK_WARNING_SHOWN = False

    def store_embedding(
        node_id: int, embedding: list[float], qualified_name: str
    ) -> None:
        global _QDRANT_LOCK_WARNING_SHOWN
        try:
            client = get_qdrant_client()
            client.upsert(
                collection_name=settings.QDRANT_COLLECTION_NAME,
                points=[
                    PointStruct(
                        id=node_id,
                        vector=embedding,
                        payload={
                            PAYLOAD_NODE_ID: node_id,
                            PAYLOAD_QUALIFIED_NAME: qualified_name,
                        },
                    )
                ],
            )
        except Exception as e:
            err_str = str(e)
            if "already accessed by another instance" in err_str:
                if not _QDRANT_LOCK_WARNING_SHOWN:
                    logger.warning(
                        "Qdrant storage is locked by another process. "
                        "Either set QDRANT_HOST for server mode (supports concurrent access) "
                        "or stop other processes using the local Qdrant storage."
                    )
                    _QDRANT_LOCK_WARNING_SHOWN = True
            else:
                logger.warning(
                    ls.EMBEDDING_STORE_FAILED.format(name=qualified_name, error=e)
                )

    def search_embeddings(
        query_embedding: list[float], top_k: int | None = None
    ) -> list[tuple[int, float]]:
        effective_top_k = top_k if top_k is not None else settings.QDRANT_TOP_K
        try:
            client = get_qdrant_client()
            result = client.query_points(
                collection_name=settings.QDRANT_COLLECTION_NAME,
                query=query_embedding,
                limit=effective_top_k,
            )
            return [
                (hit.payload[PAYLOAD_NODE_ID], hit.score)
                for hit in result.points
                if hit.payload is not None
            ]
        except Exception as e:
            logger.warning(ls.EMBEDDING_SEARCH_FAILED.format(error=e))
            return []

    def clear_project_vectors(project_name: str) -> int:
        """
        Delete all vectors for a specific project.

        Args:
            project_name: The project name prefix (e.g., 'sked_ai')

        Returns:
            Number of vectors deleted
        """

        try:
            client = get_qdrant_client()

            points, _ = client.scroll(
                collection_name=settings.QDRANT_COLLECTION_NAME,
                limit=50000,
                with_payload=True,
                with_vectors=False,
            )

            project_prefix = f"{project_name}."
            ids_to_delete = [
                p.id
                for p in points
                if p.payload
                and p.payload.get(PAYLOAD_QUALIFIED_NAME, "").startswith(project_prefix)
            ]

            if ids_to_delete:
                client.delete(
                    collection_name=settings.QDRANT_COLLECTION_NAME,
                    points_selector=ids_to_delete,
                )
                logger.info(
                    f"Deleted {len(ids_to_delete)} vectors for project '{project_name}'"
                )

            return len(ids_to_delete)
        except Exception as e:
            logger.warning(f"Failed to clear vectors for project '{project_name}': {e}")
            return 0

else:

    def store_embedding(
        node_id: int, embedding: list[float], qualified_name: str
    ) -> None:
        pass

    def search_embeddings(
        query_embedding: list[float], top_k: int | None = None
    ) -> list[tuple[int, float]]:
        return []

    def clear_project_vectors(project_name: str) -> int:
        return 0
