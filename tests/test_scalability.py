"""Scalability tests for 100k embeddings with performance verification."""
import pytest
import time
import numpy as np
from app.qdrant_client import QdrantClient


class TestScalability100k:
    """Test system performance with 100k embeddings."""
    
    @pytest.fixture
    def qdrant_client(self):
        """Create QdrantClient instance for scalability testing."""
        return QdrantClient(url='http://localhost:6333')
    
    @pytest.fixture
    def large_embedding_batch(self):
        """Generate 100k random embeddings (1024-dim) for scalability test."""
        np.random.seed(42)  # Deterministic for reproducibility
        embeddings = []
        for i in range(100000):
            # Generate random 1024-dim vector normalized to unit length
            vector = np.random.randn(1024).astype(np.float32)
            vector = vector / np.linalg.norm(vector)  # Normalize
            embeddings.append({
                'id': str(i),
                'vector': vector.tolist(),
                'payload': {
                    'photo_id': f'photo_{i}',
                    'file_path': f'/photos/photo_{i}.jpg',
                    'file_hash': f'hash_{i}'
                }
            })
        return embeddings
    
    def test_batch_insert_100k_embeddings(self, qdrant_client, large_embedding_batch):
        """Verify 100k embeddings can be inserted efficiently."""
        # Convert to batch insert format: (point_id, vector, payload)
        points = [
            (emb['id'], emb['vector'], emb['payload'])
            for emb in large_embedding_batch
        ]
        
        # Measure insertion time
        start = time.time()
        success = qdrant_client.batch_insert(points)
        elapsed = time.time() - start
        
        # Verify insertion succeeded
        assert success, 'Batch insert of 100k embeddings should succeed'
        # Log insertion time for reference (no hard limit, but should be reasonable)
        print(f'Inserted 100k embeddings in {elapsed:.2f}s')
    
    def test_search_latency_under_100ms(self, qdrant_client, large_embedding_batch):
        """Verify search latency stays under 100ms with 100k embeddings."""
        # Insert embeddings first
        points = [
            (emb['id'], emb['vector'], emb['payload'])
            for emb in large_embedding_batch
        ]
        qdrant_client.batch_insert(points)
        
        # Use first embedding as query
        query_vector = large_embedding_batch[0]['vector']
        
        # Measure search latency (first search, cache miss)
        start = time.time()
        results = qdrant_client.similarity_search(query_vector, limit=10, threshold=0.0)
        elapsed = time.time() - start
        
        # Search should complete in <100ms even with 100k embeddings
        assert elapsed < 0.1, f'Search latency {elapsed:.3f}s exceeds 100ms limit'
        # Verify results are returned
        assert len(results) > 0, 'Search should return results'
        assert len(results) <= 10, 'Search should respect limit parameter'
    
    def test_cache_hit_latency_under_10ms(self, qdrant_client, large_embedding_batch):
        """Verify cached search latency is <10ms (significant speedup)."""
        # Insert embeddings
        points = [
            (emb['id'], emb['vector'], emb['payload'])
            for emb in large_embedding_batch
        ]
        qdrant_client.batch_insert(points)
        
        query_vector = large_embedding_batch[0]['vector']
        
        # First search (cache miss)
        qdrant_client.similarity_search(query_vector, limit=10, threshold=0.0)
        
        # Second search (cache hit) should be much faster
        start = time.time()
        results = qdrant_client.similarity_search(query_vector, limit=10, threshold=0.0)
        cached_elapsed = time.time() - start
        
        # Cached search should complete in <10ms
        assert cached_elapsed < 0.01, f'Cached search took {cached_elapsed:.4f}s, expected <10ms'
        # Verify cache is being used
        assert len(qdrant_client._search_cache) > 0, 'Cache should contain entries'
    
    def test_batch_search_maintains_latency(self, qdrant_client, large_embedding_batch):
        """Verify batch search with 10 queries maintains <100ms latency per query."""
        # Insert embeddings
        points = [
            (emb['id'], emb['vector'], emb['payload'])
            for emb in large_embedding_batch
        ]
        qdrant_client.batch_insert(points)
        
        # Create 10 query vectors from the embeddings
        query_vectors = [emb['vector'] for emb in large_embedding_batch[:10]]
        
        # Measure batch search latency
        start = time.time()
        batch_results = qdrant_client.batch_search(query_vectors, limit=10, threshold=0.0)
        total_elapsed = time.time() - start
        avg_latency = total_elapsed / len(query_vectors)
        
        # Verify results structure
        assert len(batch_results) == 10, 'Should return results for all 10 queries'
        for result_list in batch_results:
            assert isinstance(result_list, list), 'Each result should be a list'
            assert len(result_list) <= 10, 'Each result should respect limit'
        
        # Average latency per query should be <100ms
        assert avg_latency < 0.1, f'Avg batch search latency {avg_latency:.3f}s exceeds 100ms'
    
    def test_no_performance_degradation_vs_small_dataset(self, qdrant_client):
        """Verify search performance with 100k embeddings matches small dataset baseline."""
        # Create small dataset (100 embeddings)
        np.random.seed(42)
        small_points = []
        for i in range(100):
            vector = np.random.randn(1024).astype(np.float32)
            vector = vector / np.linalg.norm(vector)
            small_points.append((
                str(i),
                vector.tolist(),
                {'photo_id': f'photo_{i}', 'file_path': f'/photos/photo_{i}.jpg'}
            ))
        
        # Insert small dataset and measure search
        qdrant_client.batch_insert(small_points)
        query_vector = small_points[0][1]
        
        start = time.time()
        small_results = qdrant_client.similarity_search(query_vector, limit=10)
        small_latency = time.time() - start
        
        # Clear for next test
        qdrant_client.clear_cache()
        qdrant_client.delete_collection()
        
        # Create large dataset (100k embeddings)
        np.random.seed(42)
        large_points = []
        for i in range(100000):
            vector = np.random.randn(1024).astype(np.float32)
            vector = vector / np.linalg.norm(vector)
            large_points.append((
                str(i),
                vector.tolist(),
                {'photo_id': f'photo_{i}', 'file_path': f'/photos/photo_{i}.jpg'}
            ))
        
        # Insert large dataset and measure search
        qdrant_client.batch_insert(large_points)
        query_vector = large_points[0][1]
        
        start = time.time()
        large_results = qdrant_client.similarity_search(query_vector, limit=10)
        large_latency = time.time() - start
        
        # Both should complete in <100ms (no significant degradation)
        assert small_latency < 0.1, f'Small dataset search took {small_latency:.3f}s'
        assert large_latency < 0.1, f'Large dataset search took {large_latency:.3f}s'
        # Large dataset should not be significantly slower (allow 2x overhead)
        assert large_latency < small_latency * 2, 'Large dataset should not degrade >2x'
        print(f'Small dataset: {small_latency*1000:.2f}ms, Large dataset: {large_latency*1000:.2f}ms')
