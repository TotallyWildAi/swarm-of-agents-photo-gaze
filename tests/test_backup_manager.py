"""Unit tests for backup and disaster recovery functionality."""
import pytest
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from app.backup_manager import BackupManager


class TestBackupManager:
    """Test backup creation, recovery, and data integrity verification."""
    
    @pytest.fixture
    def backup_manager(self):
        """Create BackupManager with temporary backup directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BackupManager(backup_dir=tmpdir, backup_interval_hours=1)
            yield manager
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_backup_creates_directory(self, backup_manager):
        """Verify backup creation initializes backup directory structure."""
        with patch.object(backup_manager, '_backup_postgresql', new_callable=AsyncMock):
            with patch.object(backup_manager, '_backup_qdrant', new_callable=AsyncMock):
                backup_id = await backup_manager.create_backup()
                
                backup_path = backup_manager.backup_dir / backup_id
                assert backup_path.exists()
                assert (backup_path / "metadata.json").exists()
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_backup_metadata_contains_timestamp(self, backup_manager):
        """Verify backup metadata includes timestamp and status."""
        with patch.object(backup_manager, '_backup_postgresql', new_callable=AsyncMock):
            with patch.object(backup_manager, '_backup_qdrant', new_callable=AsyncMock):
                backup_id = await backup_manager.create_backup()
                
                metadata_file = backup_manager.backup_dir / backup_id / "metadata.json"
                with open(metadata_file, "r") as f:
                    metadata = json.load(f)
                
                assert metadata["backup_id"] == backup_id
                assert metadata["status"] == "completed"
                assert "timestamp" in metadata
                assert metadata["postgresql"] == "success"
                assert metadata["qdrant"] == "success"
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_backup_postgresql_creates_dump_file(self, backup_manager):
        """Verify PostgreSQL backup creates SQL dump file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir)
            
            # Mock subprocess for pg_dump
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                
                await backup_manager._backup_postgresql(backup_path)
                
                # Verify pg_dump was called
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                assert "pg_dump" in call_args
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_backup_qdrant_saves_points_json(self, backup_manager):
        """Verify Qdrant backup saves points to JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir)
            
            # Mock Qdrant client
            mock_client = MagicMock()
            mock_client.get_collection.return_value = MagicMock()
            mock_client.scroll.return_value = ([], None)  # No points
            
            with patch('app.backup_manager.QdrantClient', return_value=mock_client):
                await backup_manager._backup_qdrant(backup_path)
                
                # Verify JSON file was created
                qdrant_file = backup_path / "qdrant_points.json"
                assert qdrant_file.exists()
                
                with open(qdrant_file, "r") as f:
                    points = json.load(f)
                assert isinstance(points, list)
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_restore_backup_returns_false_for_missing_backup(self, backup_manager):
        """Verify restore returns False when backup doesn't exist."""
        result = await backup_manager.restore_backup("nonexistent_backup")
        assert result is False
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_restore_postgresql_from_backup(self, backup_manager):
        """Verify PostgreSQL restore executes psql command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir)
            backup_path.mkdir(exist_ok=True)
            
            # Create dummy dump file
            dump_file = backup_path / "database.sql"
            dump_file.write_text("SELECT 1;")
            
            # Mock subprocess for psql
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                
                await backup_manager._restore_postgresql(backup_path)
                
                # Verify psql was called
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                assert "psql" in call_args
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_restore_qdrant_from_backup(self, backup_manager):
        """Verify Qdrant restore recreates collection and restores points."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir)
            backup_path.mkdir(exist_ok=True)
            
            # Create dummy Qdrant backup file
            points_data = [
                {"id": 1, "vector": [0.1] * 1024, "payload": {"photo_id": 1}},
                {"id": 2, "vector": [0.2] * 1024, "payload": {"photo_id": 2}}
            ]
            qdrant_file = backup_path / "qdrant_points.json"
            with open(qdrant_file, "w") as f:
                json.dump(points_data, f)
            
            # Mock Qdrant client
            mock_client = MagicMock()
            
            with patch('app.backup_manager.QdrantClient', return_value=mock_client):
                await backup_manager._restore_qdrant(backup_path)
                
                # Verify collection was deleted and recreated
                mock_client.delete_collection.assert_called_once()
                mock_client.create_collection.assert_called_once()
                # Verify upsert was called for points
                mock_client.upsert.assert_called()
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_backup_status_lists_backups(self, backup_manager):
        """Verify backup status returns list of available backups."""
        with patch.object(backup_manager, '_backup_postgresql', new_callable=AsyncMock):
            with patch.object(backup_manager, '_backup_qdrant', new_callable=AsyncMock):
                # Create multiple backups
                backup_id_1 = await backup_manager.create_backup()
                await asyncio.sleep(0.1)
                backup_id_2 = await backup_manager.create_backup()
                
                status = await backup_manager.get_backup_status()
                
                assert status["total_backups"] == 2
                assert len(status["backups"]) == 2
                assert status["backup_interval_hours"] == 1
    
    @pytest.mark.unit
    def test_verify_backup_integrity_valid_backup(self, backup_manager):
        """Verify backup integrity check passes for valid backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "test_backup"
            backup_path.mkdir(parents=True)
            
            # Create valid metadata
            metadata = {
                "backup_id": "test_backup",
                "status": "completed",
                "timestamp": "2024-01-01T00:00:00"
            }
            metadata_file = backup_path / "metadata.json"
            with open(metadata_file, "w") as f:
                json.dump(metadata, f)
            
            # Patch backup_dir to use test directory
            backup_manager.backup_dir = Path(tmpdir)
            
            result = backup_manager.verify_backup_integrity("test_backup")
            assert result is True
    
    @pytest.mark.unit
    def test_verify_backup_integrity_missing_backup(self, backup_manager):
        """Verify backup integrity check fails for missing backup."""
        result = backup_manager.verify_backup_integrity("nonexistent")
        assert result is False
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_schedule_automated_backups_creates_task(self, backup_manager):
        """Verify automated backup scheduling creates background task."""
        with patch.object(backup_manager, 'create_backup', new_callable=AsyncMock):
            await backup_manager.schedule_automated_backups()
            
            assert backup_manager.backup_task is not None
            assert not backup_manager.backup_task.done()
            
            # Clean up task
            backup_manager.backup_task.cancel()
            try:
                await backup_manager.backup_task
            except asyncio.CancelledError:
                pass
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_backup_recovery_cycle_preserves_data(self, backup_manager):
        """Verify complete backup and recovery cycle preserves data integrity.
        
        This test verifies:
        1. create_backup() successfully backs up PostgreSQL and Qdrant data
        2. Backup metadata includes collection info (vector size, distance metric)
        3. restore_backup() correctly restores data with original collection parameters
        """
        # Create test Qdrant points
        test_points = [
            {"id": 1, "vector": [0.1] * 512, "payload": {"photo_id": 1}},
            {"id": 2, "vector": [0.2] * 512, "payload": {"photo_id": 2}}
        ]
        
        # Mock Qdrant collection info with specific vector size
        mock_collection_info = MagicMock()
        mock_collection_info.config.params.vectors.size = 512
        mock_collection_info.config.params.distance = "Distance.COSINE"
        
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_collection_info
        mock_client.scroll.return_value = (test_points, None)
        
        # Step 1: Create backup
        with patch('app.backup_manager.QdrantClient', return_value=mock_client):
            with patch.object(backup_manager, '_backup_postgresql', new_callable=AsyncMock):
                backup_id = await backup_manager.create_backup()
        
        # Verify backup created with metadata containing collection info
        backup_dir = backup_manager.backup_dir / backup_id
        assert backup_dir.exists()
        assert (backup_dir / "metadata.json").exists()
        assert (backup_dir / "qdrant_points.json").exists()
        
        with open(backup_dir / "metadata.json", "r") as f:
            metadata = json.load(f)
        assert metadata["status"] == "completed"
        assert "qdrant_collection_metadata" in metadata
        assert metadata["qdrant_collection_metadata"]["vector_size"] == 512
        
        # Step 2: Restore from backup
        mock_client.reset_mock()
        mock_client.delete_collection = MagicMock()
        mock_client.create_collection = MagicMock()
        mock_client.upsert = MagicMock()
        
        with patch('app.backup_manager.QdrantClient', return_value=mock_client):
            with patch.object(backup_manager, '_restore_postgresql', new_callable=AsyncMock):
                result = await backup_manager.restore_backup(backup_id)
        
        # Verify restore succeeded and used correct vector size
        assert result is True
        mock_client.delete_collection.assert_called_once()
        mock_client.create_collection.assert_called_once()
        
        # Verify collection was recreated with 512 dimensions (from metadata), not hardcoded 1024
        call_kwargs = mock_client.create_collection.call_args[1]
        assert call_kwargs["vectors_config"].size == 512
        
        # Verify points were restored
        mock_client.upsert.assert_called()
