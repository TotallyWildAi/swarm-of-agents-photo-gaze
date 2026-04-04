"""Unit tests for Qdrant threshold filtering and result ranking."""
import pytest
import time
from app.qdrant_client import QdrantClient


class TestQdrantThresholdFiltering:
    """Test Qdrant client threshold filtering and result ranking."""
    
    @pytest.fixture
    def qdrant_client(self):
        """Provide a Qdrant client instance for testing."""
        client = QdrantClient(collection_name="test_threshold")
        # Clean up before test
        client.delete_collection()
        # Recreate collection
        from qdrant_client.models import Distance, VectorParams
        try:
            client.client.create_collection(
                collection_name="test_threshold",
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
            )
        except Exception:
            pass  # Collection may already exist
        yield client
        # Clean up after test
        client.delete_collection()
    
    @pytest.mark.unit
    def test_threshold_filtering_excludes_low_scores(self, qdrant_client):
        """Verify threshold parameter filters out results below threshold."""
        # Insert vectors with varying similarity to query
        points = [
            ("point_1", [0.1] * 1024, {"photo_id": 1}),  # Very similar
            ("point_2", [0.5] * 1024, {"photo_id": 2}),  # Medium similarity
            ("point_3", [0.9] * 1024, {"photo_id": 3}),  # Very dissimilar
        ]
        qdrant_client.batch_insert(points)
        
        # Search with high threshold
        query_vector = [0.1] * 1024
        results_no_threshold = qdrant_client.similarity_search(query_vector, limit=10, threshold=0.0)
        results_high_threshold = qdrant_client.similarity_search(query_vector, limit=10, threshold=0.5)
        
        # High threshold should return fewer results
        assert len(results_high_threshold) <= len(results_no_threshold)
        # All results should meet threshold
        assert all(r["score"] >= 0.5 for r in results_high_threshold)
    
    @pytest.mark.unit
    def test_results_ranked_by_score_descending(self, qdrant_client):
        """Verify results are ranked by similarity score in descending order."""
        # Insert vectors with known similarity values
        points = [
            ("point_1", [0.1] * 1024, {"photo_id": 1}),
            ("point_2", [0.2] * 1024, {"photo_id": 2}),
            ("point_3", [0.3] * 1024, {"photo_id": 3}),
            ("point_4", [0.4] * 1024, {"photo_id": 4}),
        ]
        qdrant_client.batch_insert(points)
        
        # Search and verify ranking
        query_vector = [0.1] * 1024
        results = qdrant_client.similarity_search(query_vector, limit=10)
        
        # Verify results are sorted by score descending
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), f"Scores not in descending order: {scores}"
    
    @pytest.mark.unit
    def test_threshold_with_performance(self, qdrant_client):
        """Verify threshold filtering maintains sub-100ms performance."""
        # Insert many vectors
        points = [(f"point_{i}", [float(i % 10) / 10] * 1024, {"idx": i}) for i in range(100)]
        qdrant_client.batch_insert(points)
        
        # Measure search time with threshold
        query_vector = [0.5] * 1024
        start_time = time.time()
        results = qdrant_client.similarity_search(query_vector, limit=10, threshold=0.3)
        elapsed_ms = (time.time() - start_time) * 1000
        
        assert elapsed_ms < 100, f"Search took {elapsed_ms:.2f}ms, expected < 100ms"
        # All results should meet threshold
        assert all(r["score"] >= 0.3 for r in results)
    
    @pytest.mark.unit
    def test_batch_search_with_threshold(self, qdrant_client):
        """Verify batch search respects threshold parameter."""
        # Insert test vectors
        points = [
            ("point_1", [0.1] * 1024, {"photo_id": 1}),
            ("point_2", [0.5] * 1024, {"photo_id": 2}),
            ("point_3", [0.9] * 1024, {"photo_id": 3}),
        ]
        qdrant_client.batch_insert(points)
        
        # Batch search with threshold
        query_vectors = [[0.1] * 1024, [0.5] * 1024]
        results = qdrant_client.batch_search(query_vectors, limit=10, threshold=0.4)
        
        # All results in all queries should meet threshold
        for query_results in results:
            assert all(r["score"] >= 0.4 for r in query_results)
    
    @pytest.mark.unit
    def test_threshold_zero_returns_all_results(self, qdrant_client):
        """Verify threshold=0.0 returns all results (no filtering)."""
        # Insert test vectors
        points = [
            ("point_1", [0.1] * 1024, {"photo_id": 1}),
            ("point_2", [0.5] * 1024, {"photo_id": 2}),
            ("point_3", [0.9] * 1024, {"photo_id": 3}),
        ]
        qdrant_client.batch_insert(points)
        
        # Search with threshold=0.0 should return all results
        query_vector = [0.5] * 1024
        results = qdrant_client.similarity_search(query_vector, limit=10, threshold=0.0)
        
        assert len(results) == 3
