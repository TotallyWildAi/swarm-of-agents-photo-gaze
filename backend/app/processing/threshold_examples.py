"""Generate and cache threshold examples during photo processing."""
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models import ThresholdExample, ProcessingJob, Photo
from app.search.search import search_similar_photos


# Threshold values covering strict to loose matching range
EXAMPLE_THRESHOLDS = [0.9, 0.7, 0.5, 0.4, 0.3]


def generate_threshold_examples(
    db: Session,
    processing_job_id: int,
    sample_photo_ids: List[int],
    max_samples_per_threshold: int = 3
) -> List[ThresholdExample]:
    """
    Generate and cache threshold examples for a processing job.
    
    Args:
        db: Database session
        processing_job_id: ID of the processing job
        sample_photo_ids: List of photo IDs to use for generating examples
        max_samples_per_threshold: Maximum number of sample matches to cache per threshold
    
    Returns:
        List of created ThresholdExample records
    """
    examples = []
    
    # Get the processing job to verify it exists
    job = db.query(ProcessingJob).filter(ProcessingJob.id == processing_job_id).first()
    if not job:
        raise ValueError(f"Processing job {processing_job_id} not found")
    
    # Generate examples for each threshold
    for threshold in EXAMPLE_THRESHOLDS:
        sample_matches = []
        total_matches = 0
        
        # Collect sample matches from sample photos
        for photo_id in sample_photo_ids[:3]:  # Use up to 3 sample photos
            photo = db.query(Photo).filter(Photo.id == photo_id).first()
            if not photo:
                continue
            
            # Search for similar photos at this threshold
            matches = search_similar_photos(
                db=db,
                photo_id=photo_id,
                threshold=threshold,
                limit=max_samples_per_threshold
            )
            
            # Track total matches and collect samples
            total_matches += len(matches)
            for match in matches[:max_samples_per_threshold]:
                sample_matches.append({
                    "photo_id": match.get("id"),
                    "similarity_score": match.get("similarity_score"),
                    "filename": match.get("filename")
                })
        
        # Create threshold example record
        example = ThresholdExample(
            processing_job_id=processing_job_id,
            threshold=threshold,
            match_count=total_matches,
            sample_matches=sample_matches
        )
        db.add(example)
        examples.append(example)
    
    db.commit()
    return examples


def get_threshold_examples(
    db: Session,
    processing_job_id: int
) -> List[Dict[str, Any]]:
    """
    Retrieve cached threshold examples for a processing job.
    
    Args:
        db: Database session
        processing_job_id: ID of the processing job
    
    Returns:
        List of threshold example dictionaries
    """
    examples = db.query(ThresholdExample).filter(
        ThresholdExample.processing_job_id == processing_job_id
    ).order_by(ThresholdExample.threshold.desc()).all()
    
    return [
        {
            "id": ex.id,
            "threshold": ex.threshold,
            "match_count": ex.match_count,
            "sample_matches": ex.sample_matches,
            "created_at": ex.created_at.isoformat()
        }
        for ex in examples
    ]
