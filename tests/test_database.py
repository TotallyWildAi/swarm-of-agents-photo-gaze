"""Integration tests for database schema and migrations."""
import pytest
import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from app.models import Base, Photo, Embedding, ProcessingState, UserPreferences


class TestDatabaseSchema:
    """Test database schema creation and structure."""

    @pytest.fixture
    def db_engine(self):
        """Create a test database engine."""
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/app_db"
        )
        engine = create_engine(database_url, echo=False)
        yield engine
        engine.dispose()

    @pytest.fixture
    def db_session(self, db_engine):
        """Create a test database session."""
        Session = sessionmaker(bind=db_engine)
        session = Session()
        yield session
        session.close()

    @pytest.mark.integration
    def test_user_preferences_table_exists(self, db_engine):
        """Verify user_preferences table exists with correct columns."""
        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        assert "user_preferences" in tables

        columns = {col["name"] for col in inspector.get_columns("user_preferences")}
        expected_columns = {
            "id", "username", "email", "preferred_embedding_model",
            "enable_auto_processing", "created_at", "updated_at"
        }
        assert expected_columns.issubset(columns)

    @pytest.mark.integration
    def test_photos_table_exists(self, db_engine):
        """Verify photos table exists with correct columns and foreign key."""
        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        assert "photos" in tables

        columns = {col["name"] for col in inspector.get_columns("photos")}
        expected_columns = {
            "id", "filename", "file_path", "file_size", "mime_type",
            "uploaded_at", "user_id"
        }
        assert expected_columns.issubset(columns)

    @pytest.mark.integration
    def test_embeddings_table_exists(self, db_engine):
        """Verify embeddings table exists with correct columns and foreign key."""
        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        assert "embeddings" in tables

        columns = {col["name"] for col in inspector.get_columns("embeddings")}
        expected_columns = {
            "id", "photo_id", "embedding_model", "vector_dimension",
            "qdrant_point_id", "created_at"
        }
        assert expected_columns.issubset(columns)

    @pytest.mark.integration
    def test_processing_state_table_exists(self, db_engine):
        """Verify processing_state table exists with correct columns and foreign key."""
        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        assert "processing_state" in tables

        columns = {col["name"] for col in inspector.get_columns("processing_state")}
        expected_columns = {
            "id", "photo_id", "status", "extraction_status", "embedding_status",
            "error_message", "started_at", "completed_at", "updated_at"
        }
        assert expected_columns.issubset(columns)

    @pytest.mark.integration
    def test_photos_table_indexes(self, db_engine):
        """Verify photos table has required indexes for query performance."""
        inspector = inspect(db_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("photos")}
        expected_indexes = {"idx_photos_user_id", "idx_photos_uploaded_at", "idx_photos_filename"}
        assert expected_indexes.issubset(indexes)

    @pytest.mark.integration
    def test_embeddings_table_indexes(self, db_engine):
        """Verify embeddings table has required indexes for query performance."""
        inspector = inspect(db_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("embeddings")}
        expected_indexes = {"idx_embeddings_photo_id", "idx_embeddings_model", "idx_embeddings_qdrant_point_id"}
        assert expected_indexes.issubset(indexes)

    @pytest.mark.integration
    def test_processing_state_table_indexes(self, db_engine):
        """Verify processing_state table has required indexes for query performance."""
        inspector = inspect(db_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("processing_state")}
        expected_indexes = {"idx_processing_state_photo_id", "idx_processing_state_status", "idx_processing_state_updated_at"}
        assert expected_indexes.issubset(indexes)

    @pytest.mark.integration
    def test_user_preferences_table_indexes(self, db_engine):
        """Verify user_preferences table has required indexes for query performance."""
        inspector = inspect(db_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("user_preferences")}
        expected_indexes = {"idx_user_preferences_username", "idx_user_preferences_email"}
        assert expected_indexes.issubset(indexes)

    @pytest.mark.integration
    def test_photos_user_id_foreign_key(self, db_engine):
        """Verify photos table has foreign key constraint to user_preferences."""
        inspector = inspect(db_engine)
        fks = inspector.get_foreign_keys("photos")
        fk_columns = {fk["constrained_columns"][0] for fk in fks if "user_id" in fk["constrained_columns"]}
        assert "user_id" in fk_columns

    @pytest.mark.integration
    def test_embeddings_photo_id_foreign_key(self, db_engine):
        """Verify embeddings table has foreign key constraint to photos."""
        inspector = inspect(db_engine)
        fks = inspector.get_foreign_keys("embeddings")
        fk_columns = {fk["constrained_columns"][0] for fk in fks if "photo_id" in fk["constrained_columns"]}
        assert "photo_id" in fk_columns

    @pytest.mark.integration
    def test_processing_state_photo_id_foreign_key(self, db_engine):
        """Verify processing_state table has foreign key constraint to photos."""
        inspector = inspect(db_engine)
        fks = inspector.get_foreign_keys("processing_state")
        fk_columns = {fk["constrained_columns"][0] for fk in fks if "photo_id" in fk["constrained_columns"]}
        assert "photo_id" in fk_columns

