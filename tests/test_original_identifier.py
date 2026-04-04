"""Unit tests for original photo identification logic."""
import pytest
from app.original_identifier import identify_original, OriginalPhotoResult
from app.metadata_extractor import ImageMetadata


class TestOriginalIdentifier:
    """Test original photo identification with confidence scores and metadata."""
    
    @pytest.fixture
    def sample_metadata(self):
        """Provide sample ImageMetadata objects for testing."""
        return {
            'photo_1': ImageMetadata(
                filename='photo1.jpg',
                file_path='/photos/photo1.jpg',
                file_size=2_000_000,
                width=4000,
                height=3000,
                format='JPEG',
                creation_timestamp=1000.0,
                file_hash='hash1',
            ),
            'photo_2': ImageMetadata(
                filename='photo2.jpg',
                file_path='/photos/photo2.jpg',
                file_size=1_500_000,
                width=3000,
                height=2000,
                format='JPEG',
                creation_timestamp=2000.0,
                file_hash='hash2',
            ),
            'photo_3': ImageMetadata(
                filename='photo3.jpg',
                file_path='/photos/photo3.jpg',
                file_size=3_000_000,
                width=5000,
                height=4000,
                format='JPEG',
                creation_timestamp=500.0,
                file_hash='hash3',
            ),
        }
    
    @pytest.mark.unit
    def test_single_photo_returns_as_original(self, sample_metadata):
        """Verify single photo in group is identified as original."""
        similarity_group = [{'id': 'photo_1', 'score': 0.95, 'payload': {}}]
        confidence_scores = {'photo_1': 0.85}
        
        result = identify_original(similarity_group, sample_metadata, confidence_scores)
        
        assert result is not None
        assert result.photo_id == 'photo_1'
        assert result.filename == 'photo1.jpg'
        assert result.confidence_score == 0.85
        assert 'Only photo' in result.rank_reason
    
    @pytest.mark.unit
    def test_highest_confidence_score_wins(self, sample_metadata):
        """Verify photo with highest confidence score is selected."""
        similarity_group = [
            {'id': 'photo_1', 'score': 0.95, 'payload': {}},
            {'id': 'photo_2', 'score': 0.92, 'payload': {}},
            {'id': 'photo_3', 'score': 0.90, 'payload': {}},
        ]
        confidence_scores = {
            'photo_1': 0.95,  # Highest
            'photo_2': 0.85,
            'photo_3': 0.75,
        }
        
        result = identify_original(similarity_group, sample_metadata, confidence_scores)
        
        assert result.photo_id == 'photo_1'
        assert result.confidence_score == 0.95
        assert 'confidence score' in result.rank_reason.lower()
    
    @pytest.mark.unit
    def test_resolution_breaks_confidence_tie(self, sample_metadata):
        """Verify resolution is used when confidence scores are equal."""
        similarity_group = [
            {'id': 'photo_1', 'score': 0.95, 'payload': {}},  # 12MP
            {'id': 'photo_2', 'score': 0.95, 'payload': {}},  # 6MP
        ]
        confidence_scores = {
            'photo_1': 0.85,  # Same confidence
            'photo_2': 0.85,
        }
        
        result = identify_original(similarity_group, sample_metadata, confidence_scores)
        
        assert result.photo_id == 'photo_1'  # 4000x3000 = 12MP > 3000x2000 = 6MP
        assert 'resolution' in result.rank_reason.lower()
    
    @pytest.mark.unit
    def test_file_size_breaks_resolution_tie(self, sample_metadata):
        """Verify file size is used when resolution is equal."""
        # Create two photos with same resolution but different sizes
        metadata_same_res = {
            'photo_a': ImageMetadata(
                filename='a.jpg',
                file_path='/photos/a.jpg',
                file_size=3_000_000,  # Larger
                width=4000,
                height=3000,
                format='JPEG',
                creation_timestamp=1000.0,
                file_hash='hash_a',
            ),
            'photo_b': ImageMetadata(
                filename='b.jpg',
                file_path='/photos/b.jpg',
                file_size=1_000_000,  # Smaller
                width=4000,
                height=3000,
                format='JPEG',
                creation_timestamp=2000.0,
                file_hash='hash_b',
            ),
        }
        similarity_group = [
            {'id': 'photo_a', 'score': 0.95, 'payload': {}},
            {'id': 'photo_b', 'score': 0.95, 'payload': {}},
        ]
        confidence_scores = {'photo_a': 0.85, 'photo_b': 0.85}
        
        result = identify_original(similarity_group, metadata_same_res, confidence_scores)
        
        assert result.photo_id == 'photo_a'  # Larger file
        assert 'file size' in result.rank_reason.lower()
    
    @pytest.mark.unit
    def test_earliest_creation_date_breaks_all_ties(self, sample_metadata):
        """Verify earliest creation date is used for identical duplicates."""
        # Create two identical photos with different creation dates
        metadata_identical = {
            'photo_old': ImageMetadata(
                filename='old.jpg',
                file_path='/photos/old.jpg',
                file_size=2_000_000,
                width=4000,
                height=3000,
                format='JPEG',
                creation_timestamp=500.0,  # Earlier
                file_hash='hash_old',
            ),
            'photo_new': ImageMetadata(
                filename='new.jpg',
                file_path='/photos/new.jpg',
                file_size=2_000_000,
                width=4000,
                height=3000,
                format='JPEG',
                creation_timestamp=1000.0,  # Later
                file_hash='hash_new',
            ),
        }
        similarity_group = [
            {'id': 'photo_old', 'score': 0.95, 'payload': {}},
            {'id': 'photo_new', 'score': 0.95, 'payload': {}},
        ]
        confidence_scores = {'photo_old': 0.85, 'photo_new': 0.85}
        
        result = identify_original(similarity_group, metadata_identical, confidence_scores)
        
        assert result.photo_id == 'photo_old'  # Earlier creation date
        assert 'creation date' in result.rank_reason.lower()
    
    @pytest.mark.unit
    def test_empty_similarity_group_returns_none(self):
        """Verify empty group returns None."""
        result = identify_original([], {}, {})
        assert result is None
    
    @pytest.mark.unit
    def test_missing_metadata_skips_photo(self, sample_metadata):
        """Verify photos without metadata are skipped."""
        similarity_group = [
            {'id': 'photo_missing', 'score': 0.95, 'payload': {}},  # No metadata
            {'id': 'photo_1', 'score': 0.90, 'payload': {}},
        ]
        confidence_scores = {'photo_missing': 0.95, 'photo_1': 0.85}
        
        result = identify_original(similarity_group, sample_metadata, confidence_scores)
        
        assert result.photo_id == 'photo_1'  # Only valid photo selected
    
    @pytest.mark.unit
    def test_missing_confidence_score_defaults_to_zero(self, sample_metadata):
        """Verify missing confidence scores default to 0.0."""
        similarity_group = [
            {'id': 'photo_1', 'score': 0.95, 'payload': {}},
            {'id': 'photo_2', 'score': 0.92, 'payload': {}},
        ]
        confidence_scores = {'photo_1': 0.85}  # photo_2 missing
        
        result = identify_original(similarity_group, sample_metadata, confidence_scores)
        
        assert result.photo_id == 'photo_1'  # Higher confidence wins
    
    @pytest.mark.unit
    def test_resolution_calculation_correct(self, sample_metadata):
        """Verify resolution is calculated correctly in megapixels."""
        similarity_group = [{'id': 'photo_1', 'score': 0.95, 'payload': {}}]
        confidence_scores = {'photo_1': 0.85}
        
        result = identify_original(similarity_group, sample_metadata, confidence_scores)
        
        # photo_1: 4000 * 3000 / 1_000_000 = 12.0 MP
        assert result.resolution_megapixels == 12.0
    
    @pytest.mark.unit
    def test_result_contains_all_required_fields(self, sample_metadata):
        """Verify result contains all required metadata fields."""
        similarity_group = [{'id': 'photo_1', 'score': 0.95, 'payload': {}}]
        confidence_scores = {'photo_1': 0.85}
        
        result = identify_original(similarity_group, sample_metadata, confidence_scores)
        
        assert result.photo_id == 'photo_1'
        assert result.filename == 'photo1.jpg'
        assert result.file_path == '/photos/photo1.jpg'
        assert result.confidence_score == 0.85
        assert result.resolution_megapixels == 12.0
        assert result.file_size == 2_000_000
        assert result.creation_timestamp == 1000.0
        assert result.rank_reason is not None

