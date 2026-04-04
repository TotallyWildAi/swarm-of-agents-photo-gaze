"""Folder scanner for recursively discovering and queuing photos for processing."""
import os
from pathlib import Path
from typing import List, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Photo, ProcessingState


class FolderScanner:
    """Scans folders recursively and queues photos for processing."""
    
    SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    
    def __init__(self):
        """Initialize folder scanner."""
        pass
    
    def scan_folder(self, folder_path: str, session: Session) -> Tuple[List[int], int]:
        """Recursively scan folder and queue all photos.
        
        Args:
            folder_path: Root folder path to scan
            session: SQLAlchemy session for database operations
        
        Returns:
            Tuple of (list of photo IDs, total count)
        """
        photo_ids = []
        total_count = 0
        
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
                
                try:
                    # Get file size and MIME type
                    file_size = os.path.getsize(file_path)
                    mime_type = self._get_mime_type(file_ext)
                    
                    # Check if photo already exists in database
                    existing = session.query(Photo).filter(
                        Photo.file_path == file_path
                    ).first()
                    
                    if existing:
                        photo_ids.append(existing.id)
                        continue
                    
                    # Create new photo record
                    photo = Photo(
                        filename=filename,
                        file_path=file_path,
                        file_size=file_size,
                        mime_type=mime_type,
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
        
        session.commit()
        return photo_ids, total_count
    
    def _get_mime_type(self, file_ext: str) -> str:
        """Get MIME type for file extension.
        
        Args:
            file_ext: File extension (e.g., '.jpg')
        
        Returns:
            MIME type string
        """
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }
        return mime_types.get(file_ext, "image/unknown")

