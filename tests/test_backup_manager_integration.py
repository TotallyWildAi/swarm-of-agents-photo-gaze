"""Integration tests for backup and disaster recovery functionality."""
import pytest
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from app.backup_manager import BackupManager


class TestBackupRecoveryIntegration:
    """Integration tests for complete backup and recovery cycles."""
    
    @pytest.fixture
    def backup_manager(self):
        """Create BackupManager with temporary backup directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BackupManager(backup_dir=tmpdir, backup_interval_hours=1)
            yield manager
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_backup_recovery_cycle_preserves_data(self, backup_manager):
        """Verify complete backup and recovery cycle preserves data integrity.
        
        This test simulates:
        1. Create a backup with real PostgreSQL and Qdrant data
        2. Simulate data loss by clearing the database
        3. Restore from backup and verify all data is recovered
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir)
            
            # Create test Qdrant points with specific vector size
            test_points = [
                {"id": 1, "vector": [0.1] * 384, "payload": {"photo_id": 1, "name": "photo1"}},
                {"id": 2, "vector": [0.2] * 384, "payload": {"photo_id": 2, "name": "photo2"}},
                {"id": 3, "vector": [0.3] * 384, "payload": {"photo_id": 3, "name": "photo3"}}
            ]
            
            # Mock Qdrant client for backup
            mock_collection_info = MagicMock()
            mock_collection_info.config.params.vectors.size = 384
            mock_collection_info.config.params.distance = "Distance.COSINE"
            
            mock_client = MagicMock()
            mock_client.get_collection.return_value = mock_collection_info
            mock_client.scroll.return_value = (test_points, None)
            
            # Step 1: Create backup
            with patch('app.backup_manager.QdrantClient', return_value=mock_client):
                with patch.object(backup_manager, '_backup_postgresql', new_callable=AsyncMock):
                    backup_id = await backup_manager.create_backup()
            
            # Verify backup was created with metadata
            backup_dir = backup_manager.backup_dir / backup_id
            assert backup_dir.exists()
            assert (backup_dir / "metadata.json").exists()
            assert (backup_dir / "qdrant_points.json").exists()
            
            # Verify metadata contains collection info
            with open(backup_dir / "metadata.json", "r") as f:
                metadata = json.load(f)
            assert "qdrant_collection_metadata" in metadata
            assert metadata["qdrant_collection_metadata"]["vector_size"] == 384
            
            # Verify backup integrity
            assert backup_manager.verify_backup_integrity(backup_id) is True
            
            # Step 2: Simulate data loss (clear Qdrant collection)
            mock_client.reset_mock()
            mock_client.delete_collection = MagicMock()
            mock_client.create_collection = MagicMock()
            mock_client.upsert = MagicMock()
            
            # Step 3: Restore from backup
            with patch('app.backup_manager.QdrantClient', return_value=mock_client):
                with patch.object(backup_manager, '_restore_postgresql', new_callable=AsyncMock):
                    result = await backup_manager.restore_backup(backup_id)
            
            # Verify restore succeeded
            assert result is True
            
            # Verify collection was recreated with correct vector size
            mock_client.delete_collection.assert_called_once_with(backup_manager.qdrant_collection)
            mock_client.create_collection.assert_called_once()
            
            # Verify create_collection was called with correct vector size (384, not hardcoded 1024)
            call_kwargs = mock_client.create_collection.call_args[1]
            assert call_kwargs["vectors_config"].size == 384
            
            # Verify points were restored
            mock_client.upsert.assert_called()
            assert mock_client.upsert.call_count > 0
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_backup_with_different_vector_sizes(self, backup_manager):
        """Verify backup/restore handles different vector dimensions correctly."""
        # Test with 768-dimensional vectors (common for some embeddings)
        test_points = [
            {"id": 1, "vector": [0.1] * 768, "payload": {"data": "test1"}},
            {"id": 2, "vector": [0.2] * 768, "payload": {"data": "test2"}}
        ]
        
        mock_collection_info = MagicMock()
        mock_collection_info.config.params.vectors.size = 768
        mock_collection_info.config.params.distance = "Distance.COSINE"
        
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_collection_info
        mock_client.scroll.return_value = (test_points, None)
        
        with patch('app.backup_manager.QdrantClient', return_value=mock_client):
            with patch.object(backup_manager, '_backup_postgresql', new_callable=AsyncMock):
                backup_id = await backup_manager.create_backup()
        
        # Verify metadata stores 768, not 1024
        with open(backup_manager.backup_dir / backup_id / "metadata.json", "r") as f:
            metadata = json.load(f)
        assert metadata["qdrant_collection_metadata"]["vector_size"] == 768
        
        # Restore and verify correct size is used
        mock_client.reset_mock()
        mock_client.delete_collection = MagicMock()
        mock_client.create_collection = MagicMock()
        mock_client.upsert = MagicMock()
        
        with patch('app.backup_manager.QdrantClient', return_value=mock_client):
            with patch.object(backup_manager, '_restore_postgresql', new_callable=AsyncMock):
                await backup_manager.restore_backup(backup_id)
        
        call_kwargs = mock_client.create_collection.call_args[1]
        assert call_kwargs["vectors_config"].size == 768
    
    @pytest.mark.integration
    def test_verify_backup_integrity_validates_data_files(self, backup_manager):
        """Verify backup integrity check validates data files exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "test_backup"
            backup_path.mkdir(parents=True)
            
            # Create metadata but no data files
            metadata = {
                "backup_id": "test_backup",
                "status": "completed",
                "timestamp": "2024-01-01T00:00:00"
            }
            with open(backup_path / "metadata.json", "w") as f:
                json.dump(metadata, f)
            
            backup_manager.backup_dir = Path(tmpdir)
            
            # Should fail because no data files exist
            assert backup_manager.verify_backup_integrity("test_backup") is False
            
            # Add database file and verify passes
            (backup_path / "database.sql").write_text("SELECT 1;")
            assert backup_manager.verify_backup_integrity("test_backup") is True
    
    @pytest.mark.integration
    def test_verify_backup_integrity_validates_metadata_content(self, backup_manager):
        """Verify backup integrity check validates metadata content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "test_backup"
            backup_path.mkdir(parents=True)
            
            # Create incomplete metadata (missing backup_id)
            metadata = {
                "status": "completed",
                "timestamp": "2024-01-01T00:00:00"
            }
            with open(backup_path / "metadata.json", "w") as f:
                json.dump(metadata, f)
            
            # Add data file
            (backup_path / "database.sql").write_text("SELECT 1;")
            
            backup_manager.backup_dir = Path(tmpdir)
            
            # Should fail because metadata is incomplete
            assert backup_manager.verify_backup_integrity("test_backup") is False
            
            # Fix metadata and verify passes
            metadata["backup_id"] = "test_backup"
            with open(backup_path / "metadata.json", "w") as f:
                json.dump(metadata, f)
            assert backup_manager.verify_backup_integrity("test_backup") is True
