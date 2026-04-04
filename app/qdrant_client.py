"""Qdrant vector database client with batch operations and similarity search."""
import os
import time
from typing import List, Dict, Tuple
from qdrant_client import QdrantClient as QdrantBaseClient
from qdrant_client.models import PointStruct, Distance, VectorParams


class QdrantClient:
    """Client for Qdrant vector database with batch insert and search capabilities."""
    
    def __init__(self, url: str = None, collection_name: str = "embeddings"):
        """Initialize Qdrant client.
        
        Args:
            url: Qdrant server URL (defaults to QDRANT_URL env var or http://localhost:6333)
            collection_name: Name of the collection to use (default: embeddings)
        """
        self.url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self.collection_name = collection_name
        self.client = QdrantBaseClient(url=self.url)
    
    def batch_insert(self, points: List[Tuple[str, List[float], Dict]]) -> bool:
        """Insert multiple vectors into Qdrant collection.
        
        Args:
            points: List of tuples (point_id, vector, payload) where:
                - point_id: unique string identifier
                - vector: list of floats (1024-dim)
                - payload: dict with metadata
        
        Returns:
            True if insertion succeeded, False otherwise
        """
        try:
            qdrant_points = [
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload
                )
                for point_id, vector, payload in points
            ]
            self.client.upsert(
                collection_name=self.collection_name,
                points=qdrant_points
            )
            return True
        except Exception as e:
            print(f"Error during batch insert: {e}")
            return False
    
    def similarity_search(self, query_vector: List[float], limit: int = 10, threshold: float = 0.0) -> List[Dict]:
        """Search for similar vectors in Qdrant collection with optional threshold filtering.
        
        Args:
            query_vector: Query vector (1024-dim list of floats)
            limit: Maximum number of results to return
            threshold: Minimum similarity score to include in results (default: 0.0, range: 0.0-1.0)
        
        Returns:
            List of dicts with keys: id, score, payload, filtered by threshold and ranked by score descending
        try:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit
            )
            # Filter results by threshold and convert to dicts (already ranked by score descending from Qdrant)
            filtered_results = [
                {
                    "id": result.id,
                    "score": result.score,
                    "payload": result.payload
                }
                for result in results
                if result.score >= threshold
            ]
            return filtered_results
        except Exception as e:
            print(f"Error during similarity search: {e}")
            return []
    
    def batch_search(self, query_vectors: List[List[float]], limit: int = 10, threshold: float = 0.0) -> List[List[Dict]]:
        """Perform multiple similarity searches in batch with optional threshold filtering.
        
        Args:
            query_vectors: List of query vectors (each 1024-dim)
            limit: Maximum number of results per query
            threshold: Minimum similarity score to include in results (default: 0.0)
        
        Returns:
            List of result lists, one per query vector, filtered by threshold and ranked by score descending
        """
        results = []
        for query_vector in query_vectors:
            search_results = self.similarity_search(query_vector, limit, threshold)
            results.append(search_results)
        return results
    
    def delete_collection(self) -> bool:
        """Delete the collection (for testing/cleanup).
        
        Returns:
            True if deletion succeeded, False otherwise
        """
        try:
            self.client.delete_collection(self.collection_name)
            return True
        except Exception as e:
            print(f"Error deleting collection: {e}")
            return False

