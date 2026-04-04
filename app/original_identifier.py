"""Logic to identify original photo in similarity group using confidence scores, resolution, and metadata."""
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from app.metadata_extractor import ImageMetadata


@dataclass
class OriginalPhotoResult:
    """Result of original photo identification with ranking details."""
    photo_id: str
    filename: str
    file_path: str
    confidence_score: float
    resolution_megapixels: float
    file_size: int
    creation_timestamp: float
    rank_reason: str  # Why this photo was selected as original


def identify_original(
    similarity_group: List[Dict],
    metadata_map: Dict[str, ImageMetadata],
    confidence_scores: Dict[str, float]
) -> Optional[OriginalPhotoResult]:
    """Identify the original photo in a similarity group.
    
    Ranking criteria (in order of priority):
    1. Highest DINOv2 confidence score (model confidence in embedding quality)
    2. Highest resolution (megapixels = width * height / 1_000_000)
    3. Largest file size (bytes)
    4. Earliest creation date (for identical duplicates)
    
    Args:
        similarity_group: List of dicts from Qdrant with keys: id, score, payload
        metadata_map: Dict mapping photo_id (str) to ImageMetadata objects
        confidence_scores: Dict mapping photo_id (str) to DINOv2 confidence scores (L2 norm before normalization)
    
    Returns:
        OriginalPhotoResult with selected photo and ranking reason, or None if group is empty
    """
    if not similarity_group:
        return None
    
    # Build ranking list with all scoring criteria
    candidates = []
    for item in similarity_group:
        photo_id = str(item.get('id'))
        metadata = metadata_map.get(photo_id)
        confidence = confidence_scores.get(photo_id, 0.0)
        
        if metadata is None:
            continue  # Skip photos without metadata
        
        # Calculate resolution in megapixels
        resolution_mp = (metadata.width * metadata.height) / 1_000_000
        
        candidates.append({
            'photo_id': photo_id,
            'metadata': metadata,
            'confidence_score': confidence,
            'resolution_mp': resolution_mp,
            'file_size': metadata.file_size,
            'creation_timestamp': metadata.creation_timestamp,
        })
    
    if not candidates:
        return None
    
    # Sort by: confidence (desc), resolution (desc), file_size (desc), creation_timestamp (asc)
    # Negative values for descending sort, positive for ascending
    candidates.sort(
        key=lambda c: (
            -c['confidence_score'],  # Higher confidence first
            -c['resolution_mp'],      # Higher resolution first
            -c['file_size'],          # Larger file first
            c['creation_timestamp'],  # Earlier creation first
        )
    )
    
    # Select the top-ranked candidate
    winner = candidates[0]
    metadata = winner['metadata']
    
    # Determine why this photo was selected
    rank_reason = _determine_rank_reason(winner, candidates)
    
    return OriginalPhotoResult(
        photo_id=winner['photo_id'],
        filename=metadata.filename,
        file_path=metadata.file_path,
        confidence_score=winner['confidence_score'],
        resolution_megapixels=winner['resolution_mp'],
        file_size=winner['file_size'],
        creation_timestamp=winner['creation_timestamp'],
        rank_reason=rank_reason,
    )


def _determine_rank_reason(winner: Dict, candidates: List[Dict]) -> str:
    """Determine why the winner was selected as original.
    
    Args:
        winner: The selected candidate
        candidates: All candidates sorted by ranking
    
    Returns:
        Human-readable reason for selection
    """
    if len(candidates) == 1:
        return 'Only photo in similarity group'
    
    runner_up = candidates[1]
    
    # Check which criterion differentiated winner from runner-up
    if winner['confidence_score'] > runner_up['confidence_score']:
        return f"Highest confidence score ({winner['confidence_score']:.4f} vs {runner_up['confidence_score']:.4f})"
    
    if winner['resolution_mp'] > runner_up['resolution_mp']:
        return f"Highest resolution ({winner['resolution_mp']:.2f}MP vs {runner_up['resolution_mp']:.2f}MP)"
    
    if winner['file_size'] > runner_up['file_size']:
        return f"Largest file size ({winner['file_size']} vs {runner_up['file_size']} bytes)"
    
    if winner['creation_timestamp'] < runner_up['creation_timestamp']:
        return f"Earliest creation date (identical duplicates)"
    
    return 'Selected as original'

