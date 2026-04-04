"""Security utilities for path validation and sanitization."""
import os
from pathlib import Path
from typing import Optional


# Allowed base directories for file operations
ALLOWED_BASE_PATHS = [
    os.path.abspath(os.getenv("PHOTOS_FOLDER", "./photos")),
    os.path.abspath(os.getenv("CACHE_FOLDER", "./cache")),
    os.path.abspath(os.getenv("THUMBNAILS_FOLDER", "./thumbnails")),
]


def is_safe_path(file_path: str) -> bool:
    """Check if a file path is safe and within allowed directories.
    
    Prevents directory traversal attacks by ensuring the resolved path
    is within one of the allowed base directories.
    
    Args:
        file_path: Path to validate
    
    Returns:
        True if path is safe, False otherwise
    """
    if not file_path or not isinstance(file_path, str):
        return False
    
    try:
        # Resolve to absolute path and remove any .. or . components
        resolved_path = os.path.abspath(os.path.normpath(file_path))
        
        # Check if resolved path is within any allowed base path
        for allowed_base in ALLOWED_BASE_PATHS:
            allowed_base = os.path.abspath(allowed_base)
            # Use os.path.commonpath to check if resolved_path is under allowed_base
            try:
                common = os.path.commonpath([resolved_path, allowed_base])
                if common == allowed_base:
                    return True
            except ValueError:
                # Paths on different drives on Windows
                continue
        
        return False
    except Exception:
        return False


def sanitize_path(file_path: str) -> str:
    """Sanitize a file path by resolving to absolute path.
    
    Args:
        file_path: Path to sanitize
    
    Returns:
        Absolute normalized path
    """
    return os.path.abspath(os.path.normpath(file_path))
