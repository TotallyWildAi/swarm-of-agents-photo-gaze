"""Unit tests for Qdrant vector database client operations."""
import pytest
import time
from app.qdrant_client import QdrantClient


class TestQdrantClient:
    """Test Qdrant client batch insert and similarity search operations."""
    
    @pytest.fixture
    def qdrant_client(self):
        """Provide a Qdrant client instance for testing."""
        client = QdrantClient(collection_name="test_embeddings")
        # Clean up before test
        client.delete_collection()
        # Recreate collection
        from qdrant_client.models import Distance, VectorParams
        try:
            client.client.create_collection(
                collection_name="test_embeddings",
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
            )
        except Exception:
            pass  # Collection may already exist
        yield client
        # Clean up after test
        client.delete_collection()
    
    @pytest.mark.unit
    def test_batch_insert_success(self, qdrant_client):
        """Verify batch insert of vectors succeeds."""
        points = [
            ("point_1", [0.1] * 1024, {"photo_id": 1}),
            ("point_2", [0.2] * 1024, {"photo_id": 2}),
            ("point_3", [0.3] * 1024, {"photo_id": 3}),
        ]
        result = qdrant_client.batch_insert(points)
        assert result is True
    
    @pytest.mark.unit
    def test_similarity_search_returns_results(self, qdrant_client):
        """Verify similarity search returns matching vectors."""
        # Insert test vectors
        points = [
            ("point_1", [0.1] * 1024, {"photo_id": 1}),
            ("point_2", [0.1] * 1024, {"photo_id": 2}),  # Similar to query
            ("point_3", [0.9] * 1024, {"photo_id": 3}),  # Dissimilar
        ]
        qdrant_client.batch_insert(points)
        
        # Search with similar vector
        query_vector = [0.1] * 1024
        results = qdrant_client.similarity_search(query_vector, limit=2)
        
        assert len(results) > 0
        assert all("id" in r and "score" in r and "payload" in r for r in results)
    
    @pytest.mark.unit
    def test_similarity_search_performance(self, qdrant_client):
        """Verify similarity search completes in under 100ms."""
        # Insert test vectors
        points = [(f"point_{i}", [float(i % 10) / 10] * 1024, {"idx": i}) for i in range(100)]
        qdrant_client.batch_insert(points)
        
        # Measure search time
        query_vector = [0.5] * 1024
        start_time = time.time()
        results = qdrant_client.similarity_search(query_vector, limit=10)
        elapsed_ms = (time.time() - start_time) * 1000
        
        assert elapsed_ms < 100, f"Search took {elapsed_ms:.2f}ms, expected < 100ms"
        assert len(results) > 0
    
    @pytest.mark.unit
    def test_batch_search_multiple_queries(self, qdrant_client):
        """Verify batch search handles multiple query vectors."""
        # Insert test vectors
        points = [
            ("point_1", [0.1] * 1024, {"photo_id": 1}),
            ("point_2", [0.5] * 1024, {"photo_id": 2}),
            ("point_3", [0.9] * 1024, {"photo_id": 3}),
        ]
        qdrant_client.batch_insert(points)
        
        # Batch search with multiple queries
        query_vectors = [[0.1] * 1024, [0.5] * 1024, [0.9] * 1024]
        results = qdrant_client.batch_search(query_vectors, limit=2)
        
        assert len(results) == 3
        assert all(isinstance(r, list) for r in results)
        assert all(len(r) > 0 for r in results)
    
    @pytest.mark.unit
    def test_search_with_limit(self, qdrant_client):
        """Verify search respects limit parameter."""
        # Insert many vectors
        points = [(f"point_{i}", [0.5] * 1024, {"idx": i}) for i in range(50)]
        qdrant_client.batch_insert(points)
        
        # Search with limit
        query_vector = [0.5] * 1024
        results = qdrant_client.similarity_search(query_vector, limit=5)
        
        assert len(results) <= 5
    
    @pytest.mark.unit
    def test_batch_insert_with_metadata(self, qdrant_client):
        """Verify batch insert preserves metadata in payload."""
        points = [
            ("point_1", [0.1] * 1024, {"photo_id": 1, "model": "clip"}),
            ("point_2", [0.2] * 1024, {"photo_id": 2, "model": "resnet"}),
        ]
        qdrant_client.batch_insert(points)
        
        # Search and verify payload
        results = qdrant_client.similarity_search([0.1] * 1024, limit=1)
        assert len(results) > 0
        assert "payload" in results[0]
        assert "photo_id" in results[0]["payload"]

