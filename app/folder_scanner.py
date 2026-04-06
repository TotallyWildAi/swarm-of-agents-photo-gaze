"""Folder scanner for recursively discovering and queuing photos for processing."""
import os
from pathlib import Path
from typing import List, Tuple, Set
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Photo, ProcessingState
from app.metadata_extractor import extract_metadata


class FolderScanner:
    """Scans folders recursively and queues photos for processing."""
    
    SUPPORTED_FORMATS = {
        ".jpg", ".jpeg", ".jfif",   # JPEG variants
        ".png",                      # PNG
        ".gif",                      # GIF
        ".bmp",                      # Bitmap
        ".webp",                     # WebP
        ".heic", ".heif",            # Apple HEIC/HEIF
        ".tiff", ".tif",             # TIFF
        ".avif",                     # AV1 Image
        ".ico",                      # Icon
        ".dng",                      # Adobe RAW
        ".cr2", ".nef", ".arw",      # Canon/Nikon/Sony RAW
        ".orf", ".rw2", ".pef",      # Olympus/Panasonic/Pentax RAW
    }
    
    def __init__(self):
        """Initialize folder scanner."""
        pass
    
    def scan_folder(self, folder_path: str, session: Session) -> Tuple[List[int], int]:
        """Recursively scan folder and queue photos with incremental change detection.
        
        Detects new files, changed files (via hash comparison), and deleted files.
        Only new or changed photos are queued for reprocessing.
        
        Args:
            folder_path: Root folder path to scan
            session: SQLAlchemy session for database operations
        
        Returns:
            Tuple of (list of photo IDs to process, total count of new/changed photos)
        """
        photo_ids = []
        total_count = 0
        scanned_paths: Set[str] = set()  # Track files found on disk
        
        if not os.path.isdir(folder_path):
            raise ValueError(f"Folder not found: {folder_path}")
        
        # Recursively walk through folder
        for root, dirs, files in os.walk(folder_path):
            for filename in files:
                file_path = os.path.join(root, filename)
                file_ext = Path(filename).suffix.lower()
                
                # Check if file is a supported image format
                if file_ext not in self.SUPPORTED_FORMATS:
                    continue
                
                scanned_paths.add(file_path)
                
                try:
                    # Get file size and MIME type
                    file_size = os.path.getsize(file_path)
                    mime_type = self._get_mime_type(file_ext)
                    
                    # Compute file hash for change detection
                    file_hash = None
                    try:
                        metadata = extract_metadata(file_path)
                        file_hash = metadata.file_hash
                    except Exception as e:
                        print(f"Warning: Could not compute hash for {file_path}: {e}")
                    
                    # Check if photo already exists in database
                    existing = session.query(Photo).filter(
                        Photo.file_path == file_path
                    ).first()
                    
                    if existing:
                        # File exists in DB; check if it changed
                        if file_hash and existing.file_hash and file_hash != existing.file_hash:
                            # File was modified; update hash and mark for reprocessing
                            existing.file_hash = file_hash
                            existing.file_size = file_size
                            session.add(existing)
                            session.flush()
                            photo_ids.append(existing.id)
                            total_count += 1
                        elif not existing.file_hash and file_hash:
                            # Hash was missing; store it now
                            existing.file_hash = file_hash
                            session.add(existing)
                            session.flush()
                        continue
                    
                    # Create new photo record
                    photo = Photo(
                        filename=filename,
                        file_path=file_path,
                        file_size=file_size,
                        mime_type=mime_type,
                        file_hash=file_hash,
                        uploaded_at=datetime.utcnow()
                    )
                    session.add(photo)
                    session.flush()  # Get the ID without committing
                    
                    # Create processing state record
                    processing_state = ProcessingState(
                        photo_id=photo.id,
                        status="pending",
                        extraction_status="pending",
                        embedding_status="pending"
                    )
                    session.add(processing_state)
                    session.flush()
                    
                    photo_ids.append(photo.id)
                    total_count += 1
                except Exception as e:
                    print(f"Error processing file {file_path}: {e}")
                    continue
        
        # Detect and remove deleted photos
        deleted_count = self._cleanup_deleted_photos(session, scanned_paths)
        if deleted_count > 0:
            print(f"Removed {deleted_count} deleted photos from database")
        
        session.commit()
        return photo_ids, total_count
    
    def _cleanup_deleted_photos(self, session: Session, scanned_paths: Set[str]) -> int:
        """Remove photos from database that no longer exist on disk.
        
        Args:
            session: SQLAlchemy session for database operations
            scanned_paths: Set of file paths found during folder scan
        
        Returns:
            Count of deleted photo records
        """
        all_photos = session.query(Photo).all()
        deleted_count = 0
        
        for photo in all_photos:
            if photo.file_path not in scanned_paths:
                # Photo no longer exists on disk; remove it
                session.delete(photo)
                deleted_count += 1
        
        return deleted_count
    
    def _get_mime_type(self, file_ext: str) -> str:
        """Get MIME type for file extension.
        
        Args:
            file_ext: File extension (e.g., '.jpg')
        
        Returns:
            MIME type string
        """
        mime_types = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".jfif": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".heic": "image/heic", ".heif": "image/heif",
            ".tiff": "image/tiff", ".tif": "image/tiff",
            ".avif": "image/avif",
            ".ico": "image/x-icon",
            ".dng": "image/x-adobe-dng",
            ".cr2": "image/x-canon-cr2", ".nef": "image/x-nikon-nef",
            ".arw": "image/x-sony-arw", ".orf": "image/x-olympus-orf",
            ".rw2": "image/x-panasonic-rw2", ".pef": "image/x-pentax-pef",
        }
        return mime_types.get(file_ext, "image/unknown")

