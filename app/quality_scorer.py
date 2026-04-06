"""Photo quality scoring for ranking duplicates within a similarity group.

Uses file size as a proxy for quality (larger file = more detail / less
compression).  Ties are broken by upload date (earlier = original).
"""
from typing import List, Tuple
from app.models import Photo


class QualityScorer:

    @staticmethod
    def calculate_quality_score(photo: Photo) -> float:
        """Return a deterministic score where higher = better quality.

        Primary signal: file_size (bigger files tend to be higher quality
        or less compressed).
        Tiebreaker: earlier uploaded_at wins (likely the original).
        """
        size_score = float(photo.file_size or 0)

        date_score = 0.0
        if photo.uploaded_at:
            date_score = -photo.uploaded_at.timestamp() / 1_000_000

        return round(size_score + date_score, 2)

    @staticmethod
    def rank_similarity_group(photos: List[Photo]) -> List[Tuple[Photo, float]]:
        """Return (photo, score) pairs sorted best-first."""
        scored = [(p, QualityScorer.calculate_quality_score(p)) for p in photos]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    @staticmethod
    def get_best_photo(photos: List[Photo]) -> Photo:
        if not photos:
            raise ValueError("Cannot rank empty photo list")
        return QualityScorer.rank_similarity_group(photos)[0][0]
