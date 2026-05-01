"""Verify the folder scanner never descends into the trash directory or
other system metadata directories. Regression coverage for the rule:

    A photo that was deduped and sent to ${TRASH_DIR} must not be
    re-ingested on the next scan.
"""
import os
import tempfile
import shutil
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Photo
from app.folder_scanner import FolderScanner, _is_excluded, _trash_dir_abs


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def temp_root():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_jpeg(path, color="red"):
    Image.new("RGB", (32, 32), color=color).save(path, "JPEG")


# --------------------- _is_excluded unit tests ---------------------


class TestIsExcludedPredicate:
    def test_app_trash_dir_name_excluded(self):
        assert _is_excluded("/whatever/.photo-gaze-trash", ".photo-gaze-trash", "/x")

    def test_macos_user_trash_excluded(self):
        assert _is_excluded("/Users/me/.Trash", ".Trash", "/x")

    def test_macos_volume_trash_excluded(self):
        assert _is_excluded("/Volumes/Disk/.Trashes", ".Trashes", "/x")

    def test_hidden_dir_excluded(self):
        assert _is_excluded("/Users/me/.cache", ".cache", "/x")

    def test_visible_normal_dir_not_excluded(self):
        assert not _is_excluded("/Users/me/Photos", "Photos", "/x")

    def test_absolute_path_match_to_custom_trash(self, tmp_path):
        # User configured TRASH_DIR to a non-hidden path inside their photos.
        # _is_excluded must still skip it.
        custom = tmp_path / "MyTrash"
        custom.mkdir()
        trash_abs = os.path.realpath(str(custom))
        assert _is_excluded(str(custom), "MyTrash", trash_abs)

    def test_visible_dir_with_unrelated_name_not_excluded(self, tmp_path):
        d = tmp_path / "Holidays2024"
        d.mkdir()
        assert not _is_excluded(str(d), "Holidays2024", "/elsewhere/.photo-gaze-trash")


# --------------------- end-to-end scanner tests ---------------------


class TestScannerSkipsTrash:
    """Build a tree that mirrors the real-world layout: photos at top,
    trash dir + system dirs underneath, then assert nothing in the trash
    is queued for ingestion."""

    def _build_tree(self, root):
        """Layout:
            root/keep1.jpg                      ← must be ingested
            root/keep2.jpg                      ← must be ingested
            root/.photo-gaze-trash/old.jpg      ← must NOT be ingested
            root/.Trash/system_old.jpg          ← must NOT be ingested
            root/.fseventsd/...                 ← must NOT be ingested
            root/sub/keep3.jpg                  ← must be ingested
            root/sub/.photo-gaze-trash/x.jpg    ← must NOT be ingested
            root/Vacation 2024/keep4.jpg        ← must be ingested (similar name)
        """
        _make_jpeg(os.path.join(root, "keep1.jpg"), "red")
        _make_jpeg(os.path.join(root, "keep2.jpg"), "blue")

        trash = os.path.join(root, ".photo-gaze-trash")
        os.makedirs(trash)
        _make_jpeg(os.path.join(trash, "old.jpg"), "green")

        macos_trash = os.path.join(root, ".Trash")
        os.makedirs(macos_trash)
        _make_jpeg(os.path.join(macos_trash, "system_old.jpg"), "yellow")

        fsevents = os.path.join(root, ".fseventsd")
        os.makedirs(fsevents)
        _make_jpeg(os.path.join(fsevents, "weird.jpg"), "magenta")

        sub = os.path.join(root, "sub")
        os.makedirs(sub)
        _make_jpeg(os.path.join(sub, "keep3.jpg"), "cyan")

        nested_trash = os.path.join(sub, ".photo-gaze-trash")
        os.makedirs(nested_trash)
        _make_jpeg(os.path.join(nested_trash, "x.jpg"), "white")

        vacation = os.path.join(root, "Vacation 2024")
        os.makedirs(vacation)
        _make_jpeg(os.path.join(vacation, "keep4.jpg"), "orange")

    @pytest.mark.integration
    def test_trash_files_never_queued(self, temp_root, db_session, monkeypatch):
        # Override TRASH_DIR so _trash_dir_abs() resolves to our temp tree's
        # trash. _is_excluded already excludes ".photo-gaze-trash" by name,
        # so this also pins the absolute-path branch of the predicate.
        monkeypatch.setenv("TRASH_DIR", os.path.join(temp_root, ".photo-gaze-trash"))
        self._build_tree(temp_root)

        scanner = FolderScanner()
        photo_ids, count = scanner.scan_folder(temp_root, db_session)

        # 4 keep* photos must be ingested; 4 trash/system photos must not.
        photos = db_session.query(Photo).all()
        names = sorted(p.filename for p in photos)
        assert names == ["keep1.jpg", "keep2.jpg", "keep3.jpg", "keep4.jpg"]
        assert count == 4
        # Defense: not a single trashed file path made it in
        for p in photos:
            assert ".photo-gaze-trash" not in p.file_path
            assert ".Trash" not in p.file_path
            assert ".fseventsd" not in p.file_path

    @pytest.mark.integration
    def test_custom_visible_trash_dir_excluded_by_abs_path(
        self, temp_root, db_session, monkeypatch
    ):
        """User configures TRASH_DIR to a non-hidden path inside their
        photo folder. The scanner must still skip it via the abs-path
        match (the dotfile rule alone wouldn't catch this)."""
        custom_trash = os.path.join(temp_root, "Garbage")
        os.makedirs(custom_trash)
        _make_jpeg(os.path.join(custom_trash, "trashed.jpg"), "purple")
        _make_jpeg(os.path.join(temp_root, "keep.jpg"), "red")

        monkeypatch.setenv("TRASH_DIR", custom_trash)

        scanner = FolderScanner()
        scanner.scan_folder(temp_root, db_session)
        photos = db_session.query(Photo).all()
        names = sorted(p.filename for p in photos)
        assert names == ["keep.jpg"]


# --------------------- /folders POST guard ---------------------


class TestAddFolderRejectsTrash:
    """The add_folder endpoint refuses to register the trash dir or any
    path beneath it — saves the user from a no-op + confused state where
    every scan immediately re-ingests just-deleted photos."""

    def test_register_trash_dir_itself_rejected(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient
        import app.main as app_main

        trash = tmp_path / ".photo-gaze-trash"
        trash.mkdir()
        monkeypatch.setattr(app_main, "TRASH_DIR", str(trash))

        # job_queue_manager must be set for the endpoint to proceed past
        # the 503 short-circuit. A bare object is enough — we only get to
        # the trash check before any DB session is opened.
        class _Stub:
            def SessionLocal(self):
                from unittest.mock import MagicMock
                return MagicMock()
        monkeypatch.setattr(app_main, "job_queue_manager", _Stub())

        client = TestClient(app_main.app)
        r = client.post("/folders", json={"path": str(trash)})
        assert r.status_code == 400
        assert "trash" in r.json()["error"].lower()

    def test_register_path_inside_trash_rejected(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient
        import app.main as app_main

        trash = tmp_path / ".photo-gaze-trash"
        sub = trash / "subfolder"
        sub.mkdir(parents=True)
        monkeypatch.setattr(app_main, "TRASH_DIR", str(trash))

        class _Stub:
            def SessionLocal(self):
                from unittest.mock import MagicMock
                return MagicMock()
        monkeypatch.setattr(app_main, "job_queue_manager", _Stub())

        client = TestClient(app_main.app)
        r = client.post("/folders", json={"path": str(sub)})
        assert r.status_code == 400
