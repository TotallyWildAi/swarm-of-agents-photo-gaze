"""Tests for threshold example generation and caching."""
import pytest
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import ProcessingJob, Folder, Photo, ThresholdExample
from app.processing.threshold_examples import (
    generate_threshold_examples,
    get_threshold_examples,
    EXAMPLE_THRESHOLDS
)


@pytest.fixture
def setup_test_data(db: Session):
    """Create test folder, processing job, and photos."""
    # Create folder
    folder = Folder(name="Test Folder", path="/test")
    db.add(folder)
    db.flush()
    
    # Create processing job
    job = ProcessingJob(folder_id=folder.id, status="processing")
    db.add(job)
    db.flush()
    
    # Create sample photos
    photos = []
    for i in range(5):
        photo = Photo(
            folder_id=folder.id,
            filename=f"photo_{i}.jpg",
            file_path=f"/test/photo_{i}.jpg"
        )
        db.add(photo)
        photos.append(photo)
    
    db.commit()
    return {
        "folder": folder,
        "job": job,
        "photos": photos
    }


def test_generate_threshold_examples_creates_five_thresholds(db: Session, setup_test_data):
    """Test that exactly 5 threshold examples are generated."""
    data = setup_test_data
    photo_ids = [p.id for p in data["photos"]]
    
    examples = generate_threshold_examples(
        db=db,
        processing_job_id=data["job"].id,
        sample_photo_ids=photo_ids
    )
    
    assert len(examples) == 5
    assert len(EXAMPLE_THRESHOLDS) == 5


def test_threshold_examples_cover_strict_to_loose_range(db: Session, setup_test_data):
    """Test that thresholds range from strict (0.9) to loose (0.3)."""
    data = setup_test_data
    photo_ids = [p.id for p in data["photos"]]
    
    examples = generate_threshold_examples(
        db=db,
        processing_job_id=data["job"].id,
        sample_photo_ids=photo_ids
    )
    
    thresholds = sorted([ex.threshold for ex in examples])
    assert thresholds[0] == 0.3  # Loosest
    assert thresholds[-1] == 0.9  # Strictest
    assert min(thresholds) >= 0.0
    assert max(thresholds) <= 1.0


def test_threshold_examples_cached_in_database(db: Session, setup_test_data):
    """Test that threshold examples are persisted in PostgreSQL."""
    data = setup_test_data
    photo_ids = [p.id for p in data["photos"]]
    
    generate_threshold_examples(
        db=db,
        processing_job_id=data["job"].id,
        sample_photo_ids=photo_ids
    )
    
    # Query database directly to verify persistence
    cached_examples = db.query(ThresholdExample).filter(
        ThresholdExample.processing_job_id == data["job"].id
    ).all()
    
    assert len(cached_examples) == 5
    for example in cached_examples:
        assert example.processing_job_id == data["job"].id
        assert example.threshold in EXAMPLE_THRESHOLDS
        assert example.match_count >= 0
        assert isinstance(example.sample_matches, list)


def test_get_threshold_examples_retrieves_cached_results(db: Session, setup_test_data):
    """Test that cached threshold examples can be retrieved for UI display."""
    data = setup_test_data
    photo_ids = [p.id for p in data["photos"]]
    
    generate_threshold_examples(
        db=db,
        processing_job_id=data["job"].id,
        sample_photo_ids=photo_ids
    )
    
    # Retrieve examples
    examples = get_threshold_examples(
        db=db,
        processing_job_id=data["job"].id
    )
    
    assert len(examples) == 5
    # Verify examples are ordered by threshold (descending)
    thresholds = [ex["threshold"] for ex in examples]
    assert thresholds == sorted(thresholds, reverse=True)
    
    # Verify all required fields are present
    for example in examples:
        assert "id" in example
        assert "threshold" in example
        assert "match_count" in example
        assert "sample_matches" in example
        assert "created_at" in example


def test_threshold_examples_have_sample_matches(db: Session, setup_test_data):
    """Test that threshold examples include sample match data for UI preview."""
    data = setup_test_data
    photo_ids = [p.id for p in data["photos"]]
    
    examples = generate_threshold_examples(
        db=db,
        processing_job_id=data["job"].id,
        sample_photo_ids=photo_ids
    )
    
    for example in examples:
        assert isinstance(example.sample_matches, list)
        # Each sample match should have required fields
        for match in example.sample_matches:
            assert "photo_id" in match
            assert "similarity_score" in match
            assert "filename" in match


def test_generate_threshold_examples_invalid_job_id(db: Session):
    """Test that invalid processing job ID raises error."""
    with pytest.raises(ValueError, match="Processing job .* not found"):
        generate_threshold_examples(
            db=db,
            processing_job_id=99999,
            sample_photo_ids=[]
        )
