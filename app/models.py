"""SQLAlchemy ORM models for photo metadata, embeddings, processing state, and user preferences."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, Index, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class FolderPath(Base):
    """User-registered photo folders that can be scanned on demand."""
    __tablename__ = "folder_paths"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, nullable=False, unique=True, index=True)
    is_accessible = Column(Boolean, nullable=False, default=False)
    supported_formats_found = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Photo(Base):
    """Photo metadata table storing information about uploaded photos."""
    __tablename__ = "photos"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False, unique=True)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(50), nullable=False)
    file_hash = Column(String(64), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_id = Column(Integer, ForeignKey("user_preferences.id"), nullable=True)

    # Relationships
    embeddings = relationship("Embedding", back_populates="photo", cascade="all, delete-orphan")
    processing_state = relationship("ProcessingState", back_populates="photo", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_photos_user_id", "user_id"),
        Index("idx_photos_uploaded_at", "uploaded_at"),
        Index("idx_photos_filename", "filename"),
        Index("idx_photos_file_hash", "file_hash"),
    )


class Embedding(Base):
    """Vector embeddings table storing feature vectors for photos."""
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True, index=True)
    photo_id = Column(Integer, ForeignKey("photos.id"), nullable=False)
    embedding_model = Column(String(100), nullable=False)
    vector_dimension = Column(Integer, nullable=False)
    qdrant_point_id = Column(String(255), nullable=True, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    photo = relationship("Photo", back_populates="embeddings")

    __table_args__ = (
        Index("idx_embeddings_photo_id", "photo_id"),
        Index("idx_embeddings_model", "embedding_model"),
        Index("idx_embeddings_qdrant_point_id", "qdrant_point_id"),
    )


class ProcessingState(Base):
    """Processing state table tracking the status of photo processing pipeline."""
    __tablename__ = "processing_state"

    id = Column(Integer, primary_key=True, index=True)
    photo_id = Column(Integer, ForeignKey("photos.id"), nullable=False, unique=True)
    status = Column(String(50), nullable=False, default="pending")
    extraction_status = Column(String(50), nullable=False, default="pending")
    embedding_status = Column(String(50), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    photo = relationship("Photo", back_populates="processing_state")

    __table_args__ = (
        Index("idx_processing_state_photo_id", "photo_id"),
        Index("idx_processing_state_status", "status"),
        Index("idx_processing_state_updated_at", "updated_at"),
    )


class UserPreferences(Base):
    """User preferences table storing user-specific settings and metadata."""
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=False, unique=True)
    email = Column(String(255), nullable=False, unique=True)
    preferred_embedding_model = Column(String(100), nullable=False, default="clip-vit-base-patch32")
    enable_auto_processing = Column(Boolean, nullable=False, default=True)
    threshold_setting = Column(Float, nullable=False, default=0.5)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_user_preferences_username", "username"),
        Index("idx_user_preferences_email", "email"),
    )


class JobQueue(Base):
    """Job queue table tracking async photo processing jobs and checkpoints."""
    __tablename__ = "job_queue"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(255), nullable=False, unique=True, index=True)
    status = Column(String(50), nullable=False, default="pending")  # pending, processing, completed, failed
    total_photos = Column(Integer, nullable=False)
    processed_photos = Column(Integer, nullable=False, default=0)
    checkpoint_count = Column(Integer, nullable=False, default=0)  # Number of 5-photo checkpoints completed
    last_checkpoint_at = Column(DateTime, nullable=True)  # Timestamp of last checkpoint
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_job_queue_job_id", "job_id"),
        Index("idx_job_queue_status", "status"),
        Index("idx_job_queue_created_at", "created_at"),
    )

