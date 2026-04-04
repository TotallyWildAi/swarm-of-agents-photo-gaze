"""Input validation module for API endpoints."""
import os
import uuid
from typing import Optional


def validate_folder_path(folder_path: str) -> Optional[str]:
    """Validate folder path exists and is a directory.
    
    Args:
        folder_path: Path to validate
    
    Returns:
        Error message if invalid, None if valid
    """
    if not folder_path or not isinstance(folder_path, str):
        return "Folder path must be a non-empty string"
    
    if not os.path.exists(folder_path):
        return f"Path does not exist: {folder_path}"
    
    if not os.path.isdir(folder_path):
        return f"Path is not a directory: {folder_path}"
    
    return None


def validate_photo_id(photo_id: int) -> Optional[str]:
    """Validate photo ID is a positive integer.
    
    Args:
        photo_id: Photo ID to validate
    
    Returns:
        Error message if invalid, None if valid
    """
    if not isinstance(photo_id, int):
        return "Photo ID must be an integer"
    
    if photo_id <= 0:
        return "Photo ID must be a positive integer"
    
    if photo_id > 2147483647:  # Max 32-bit signed int
        return "Photo ID exceeds maximum value"
    
    return None


def validate_thumbnail_size(size: int) -> Optional[str]:
    """Validate thumbnail size is within acceptable range.
    
    Args:
        size: Thumbnail size in pixels
    
    Returns:
        Error message if invalid, None if valid
    """
    if not isinstance(size, int):
        return "Size must be an integer"
    
    if size < 32:
        return "Size must be at least 32 pixels"
    
    if size > 2048:
        return "Size must not exceed 2048 pixels"
    
    return None


def validate_pagination(skip: int, limit: int) -> Optional[str]:
    """Validate pagination parameters.
    
    Args:
        skip: Number of items to skip
        limit: Maximum items to return
    
    Returns:
        Error message if invalid, None if valid
    """
    if not isinstance(skip, int) or not isinstance(limit, int):
        return "skip and limit must be integers"
    
    if skip < 0:
        return "skip must be non-negative"
    
    if limit < 1:
        return "limit must be at least 1"
    
    if limit > 1000:
        return "limit must not exceed 1000"
    
    if skip > 1000000:
        return "skip must not exceed 1000000"
    
    return None


def validate_similarity_filters(min_similarity: float, min_quality: float) -> Optional[str]:
    """Validate similarity and quality filter parameters.
    
    Args:
        min_similarity: Minimum similarity score (0.0-1.0)
        min_quality: Minimum quality score (0.0-1.0)
    
    Returns:
        Error message if invalid, None if valid
    """
    if not isinstance(min_similarity, (int, float)) or not isinstance(min_quality, (int, float)):
        return "min_similarity and min_quality must be numbers"
    
    if min_similarity < 0.0 or min_similarity > 1.0:
        return "min_similarity must be between 0.0 and 1.0"
    
    if min_quality < 0.0 or min_quality > 1.0:
        return "min_quality must be between 0.0 and 1.0"
    
    return None


def validate_sort_by(sort_by: str) -> Optional[str]:
    """Validate sort_by parameter.
    
    Args:
        sort_by: Sort field name
    
    Returns:
        Error message if invalid, None if valid
    """
    if not isinstance(sort_by, str):
        return "sort_by must be a string"
    
    if sort_by not in ["similarity", "quality"]:
        return f"Invalid sort_by: {sort_by}. Must be 'similarity' or 'quality'."
    
    return None


def validate_job_id(job_id: str) -> Optional[str]:
    """Validate job ID is a valid UUID format.
    
    Args:
        job_id: Job ID to validate
    
    Returns:
        Error message if invalid, None if valid
    """
    if not isinstance(job_id, str):
        return "Job ID must be a string"
    
    if not job_id.strip():
        return "Job ID must not be empty"
    
    # Validate UUID format (standard UUID v4)
    try:
        uuid.UUID(job_id)
    except ValueError:
        return f"Invalid job ID format: {job_id}. Must be a valid UUID."
    
    return None
