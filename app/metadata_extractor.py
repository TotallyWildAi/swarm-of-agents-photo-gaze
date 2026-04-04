"""Image metadata extraction with format validation and file hashing."""
import os
import hashlib
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from PIL import Image


@dataclass
class ImageMetadata:
    """Structured metadata for an image file."""
    filename: str
    file_path: str
    file_size: int
    width: int
    height: int
    format: str
    creation_timestamp: float
    file_hash: str


SUPPORTED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'RAW'}


def extract_metadata(file_path: str) -> ImageMetadata:
    """Extract metadata from an image file.
    
    Validates that the file is a supported image format (JPEG, PNG, WebP, RAW),
    extracts dimensions, file size, creation timestamp, and computes SHA256 hash.
    
    Args:
        file_path: Path to the image file
    
    Returns:
        ImageMetadata object with extracted information
    
    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file format is not supported or image cannot be opened
    """
    # Validate file exists
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    # Get file size and creation timestamp
    file_size = os.path.getsize(file_path)
    creation_timestamp = os.path.getctime(file_path)
    
    # Compute SHA256 hash of file
    file_hash = _compute_file_hash(file_path)
    
    # Open image and extract dimensions
    try:
        with Image.open(file_path) as img:
            # Get image format (PIL returns uppercase format name)
            image_format = img.format
            if image_format is None:
                raise ValueError(f"Cannot determine image format for {file_path}")
            
            # Validate format is supported
            if image_format not in SUPPORTED_FORMATS:
                raise ValueError(
                    f"Unsupported image format: {image_format}. "
                    f"Supported formats: {', '.join(sorted(SUPPORTED_FORMATS))}"
                )
            
            # Extract dimensions
            width, height = img.size
    except (IOError, OSError) as e:
        raise ValueError(f"Cannot open image file {file_path}: {e}")
    
    return ImageMetadata(
        filename=os.path.basename(file_path),
        file_path=file_path,
        file_size=file_size,
        width=width,
        height=height,
        format=image_format,
        creation_timestamp=creation_timestamp,
        file_hash=file_hash,
    )


def _compute_file_hash(file_path: str, algorithm: str = 'sha256') -> str:
    """Compute hash of file contents.
    
    Args:
        file_path: Path to the file
        algorithm: Hash algorithm to use (default: sha256)
    
    Returns:
        Hexadecimal hash string
    """
    hash_obj = hashlib.new(algorithm)
    with open(file_path, 'rb') as f:
        # Read file in chunks to handle large files efficiently
        for chunk in iter(lambda: f.read(8192), b''):
            hash_obj.update(chunk)
    return hash_obj.hexdigest()


def validate_image_format(file_path: str) -> bool:
    """Check if file is a supported image format.
    
    Args:
        file_path: Path to the file
    
    Returns:
        True if file is a supported format, False otherwise
    """
    if not os.path.exists(file_path):
        return False
    
    try:
        with Image.open(file_path) as img:
            return img.format in SUPPORTED_FORMATS
    except (IOError, OSError):
        return False

