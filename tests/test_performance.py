"""Performance tests for embedding generation, vector search, and UI latency."""
import pytest
import time
import torch
from app.embedding_generator import EmbeddingGenerator
from app.qdrant_client import QdrantClient
from PIL import Image
import io
import numpy as np


class TestEmbeddingPerformance:
    """Test embedding generation latency and M1 device detection."""
    
    @pytest.fixture
    def embedding_gen(self):
        """Create EmbeddingGenerator instance."""
        return EmbeddingGenerator()
    
    @pytest.fixture
    def sample_image(self):
        """Create a sample image for testing."""
        img = Image.new('RGB', (256, 256), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        return img_bytes.getvalue()
    
    def test_device_detection_m1(self, embedding_gen):
        """Verify M1/MPS device detection when available."""
        # Device should be one of: 'mps', 'cuda', or 'cpu'
        assert embedding_gen.device in ['mps', 'cuda', 'cpu']
        # If MPS is available, it should be selected
        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            assert embedding_gen.device == 'mps'
    
    def test_embedding_generation_latency(self, embedding_gen, sample_image):
        """Verify embedding generation completes in reasonable time."""
        start = time.time()
        embedding, confidence = embedding_gen.generate_embedding(sample_image)
        elapsed = time.time() - start
        
        # Should complete in under 5 seconds (generous for CPU)
        assert elapsed < 5.0, f'Embedding generation took {elapsed:.2f}s'
        # Verify output shape
        assert len(embedding) == 1024
        assert isinstance(confidence, float)
        assert confidence > 0
    
    def test_embedding_consistency(self, embedding_gen, sample_image):
        """Verify embeddings are deterministic (same input = same output)."""
        emb1, conf1 = embedding_gen.generate_embedding(sample_image)
        emb2, conf2 = embedding_gen.generate_embedding(sample_image)
        
        # Embeddings should be identical
        assert np.allclose(emb1, emb2, atol=1e-5)
        assert np.isclose(conf1, conf2, atol=1e-5)


class TestVectorSearchPerformance:
    """Test vector search latency and caching."""
    
    @pytest.fixture
    def qdrant_client(self):
        """Create QdrantClient instance (in-memory for testing)."""
        return QdrantClient(url='http://localhost:6333')
    
    def test_search_cache_hit_latency(self, qdrant_client):
        """Verify cached search completes in <100ms."""
        query_vector = [0.1] * 1024
        
        # First search (cache miss)
        start = time.time()
        result1 = qdrant_client.similarity_search(query_vector, limit=10)
        first_elapsed = time.time() - start
        
        # Second search (cache hit) should be much faster
        start = time.time()
        result2 = qdrant_client.similarity_search(query_vector, limit=10)
        cached_elapsed = time.time() - start
        
        # Cached search should complete in <100ms
        assert cached_elapsed < 0.1, f'Cached search took {cached_elapsed:.3f}s'
        # Results should be identical
        assert result1 == result2
    
    def test_cache_key_generation(self, qdrant_client):
        """Verify cache key generation is deterministic."""
        query_vector = [0.1, 0.2, 0.3] + [0.0] * 1021
        
        key1 = qdrant_client._cache_key(query_vector, 10, 0.5)
        key2 = qdrant_client._cache_key(query_vector, 10, 0.5)
        key3 = qdrant_client._cache_key(query_vector, 20, 0.5)  # Different limit
        
        assert key1 == key2, 'Cache keys should be deterministic'
        assert key1 != key3, 'Different parameters should produce different keys'
    
    def test_cache_clear(self, qdrant_client):
        """Verify cache can be cleared."""
        query_vector = [0.1] * 1024
        
        # Populate cache
        qdrant_client.similarity_search(query_vector, limit=10)
        assert len(qdrant_client._search_cache) > 0
        
        # Clear cache
        qdrant_client.clear_cache()
        assert len(qdrant_client._search_cache) == 0


class TestUIRenderingPerformance:
    """Test React component rendering latency (via snapshot/structure tests)."""
    
    def test_memoization_prevents_rerenders(self):
        """Verify React.memo and useMemo prevent unnecessary re-renders.
        
        This is a structural test that verifies the component uses memoization.
        Full rendering tests require Jest/React Testing Library.
        """
        # Read the component file and verify memoization patterns
        with open('src/components/SimilarPhotosGrid.tsx', 'r') as f:
            content = f.read()
            # Verify React.memo is used
            assert 'React.memo' in content, 'PhotoItem should use React.memo'
            # Verify useMemo is used
            assert 'useMemo' in content, 'Component should use useMemo for pagination'
            # Verify useCallback is used
            assert 'useCallback' in content, 'Component should use useCallback for handlers'
    
    def test_virtualization_pagination(self):
        """Verify component implements pagination for large lists."""
        with open('src/components/SimilarPhotosGrid.tsx', 'r') as f:
            content = f.read()
            # Verify pagination logic
            assert 'pageSize' in content, 'Component should support pageSize prop'
            assert 'paginatedPhotos' in content, 'Component should paginate results'
            assert 'currentPage' in content, 'Component should track current page'

