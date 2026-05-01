"""Tests for the /trash and /trash/recover endpoints.

Covers:
  - Listing trash items from one or many manifests, including pruning
    of entries whose trash file is missing on disk.
  - Recovering files: success, original-already-exists, missing trash
    file, no-original-recorded, mixed successes + failures.
  - Manifest cleanup: kept entries persisted, fully-emptied manifest
    files removed.
  - Path-traversal defense: requests for paths outside TRASH_DIR rejected.
"""
import json
import os
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.main as app_main


# --------------------------- fixtures ---------------------------


@pytest.fixture
def trash_root(monkeypatch):
    """Fresh, isolated trash directory + a separate "originals" tree the
    recover endpoint will move files back into."""
    base = tempfile.mkdtemp()
    trash = os.path.join(base, ".photo-gaze-trash")
    originals = os.path.join(base, "originals")
    os.makedirs(trash)
    os.makedirs(originals)
    monkeypatch.setattr(app_main, "TRASH_DIR", trash)
    yield {"base": base, "trash": trash, "originals": originals}
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def client(monkeypatch):
    """Bare-bones job_queue_manager stub. /trash/recover now opens a
    session and reads `.qdrant_client`, but for v1 (file-only) manifest
    entries it never actually queries either — the snapshot-restore
    helper short-circuits when the entry has no "photo" key. So a
    no-op session + qdrant stub is enough for these tests."""
    class _Stub:
        qdrant_client = MagicMock()
        def SessionLocal(self):
            return MagicMock()
    monkeypatch.setattr(app_main, "job_queue_manager", _Stub())
    return TestClient(app_main.app)


def _seed_trash_entry(trash_dir, ts, photo_id, original_path, content=b"jpeg"):
    """Drop a fake trashed photo + manifest record. Returns its trash_path."""
    basename = os.path.basename(original_path)
    trash_path = os.path.join(trash_dir, f"{ts}_{photo_id}_{basename}")
    with open(trash_path, "wb") as f:
        f.write(content)

    manifest_path = os.path.join(trash_dir, f"{ts}_manifest.json")
    existing = []
    if os.path.isfile(manifest_path):
        with open(manifest_path) as f:
            existing = json.load(f)
    existing.append({
        "photo_id": photo_id,
        "original": original_path,
        "trash": trash_path,
    })
    with open(manifest_path, "w") as f:
        json.dump(existing, f, indent=2)
    return trash_path, manifest_path


# --------------------------- /trash listing ---------------------------


class TestListTrash:
    def test_empty_trash_returns_empty_list(self, client, trash_root):
        r = client.get("/trash")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["trash_dir"] == trash_root["trash"]

    def test_lists_all_entries_across_manifests(self, client, trash_root):
        orig_a = os.path.join(trash_root["originals"], "subA", "a.jpg")
        orig_b = os.path.join(trash_root["originals"], "subB", "b.jpg")
        orig_c = os.path.join(trash_root["originals"], "subA", "c.jpg")
        os.makedirs(os.path.dirname(orig_a))
        os.makedirs(os.path.dirname(orig_b))
        # Two separate trashing batches — distinct timestamps -> separate
        # manifests; the listing must merge both.
        _seed_trash_entry(trash_root["trash"], "20260101_100000", 1, orig_a)
        _seed_trash_entry(trash_root["trash"], "20260101_100000", 2, orig_b)
        _seed_trash_entry(trash_root["trash"], "20260202_120000", 3, orig_c)

        r = client.get("/trash")
        items = r.json()["items"]
        assert len(items) == 3
        filenames = sorted(i["filename"] for i in items)
        assert filenames == ["a.jpg", "b.jpg", "c.jpg"]
        # trashed_at extracted from the manifest filename
        ts_set = {i["trashed_at"] for i in items}
        assert ts_set == {"20260101_100000", "20260202_120000"}

    def test_skips_entries_whose_trash_file_is_gone(self, client, trash_root):
        """Entries whose trash file vanished (e.g. user emptied Finder's
        Trash manually) must NOT show up in /trash — they can't be
        recovered, so listing them would only confuse the user."""
        orig = os.path.join(trash_root["originals"], "x.jpg")
        trash_path, manifest_path = _seed_trash_entry(
            trash_root["trash"], "20260101_100000", 1, orig
        )
        os.remove(trash_path)  # simulate manual removal

        items = client.get("/trash").json()["items"]
        assert items == []

    def test_corrupt_manifest_does_not_500(self, client, trash_root):
        """A truncated/invalid manifest must not bring the endpoint down —
        we just skip it silently."""
        with open(os.path.join(trash_root["trash"], "bad_manifest.json"), "w") as f:
            f.write("{not json")
        r = client.get("/trash")
        assert r.status_code == 200
        assert r.json()["items"] == []


# --------------------------- /trash/recover ---------------------------


class TestRecover:
    def test_recovers_single_file_and_drops_manifest_entry(self, client, trash_root):
        orig = os.path.join(trash_root["originals"], "sub", "photo.jpg")
        trash_path, manifest_path = _seed_trash_entry(
            trash_root["trash"], "20260101_100000", 1, orig
        )

        r = client.post("/trash/recover", json={"trash_paths": [trash_path]})
        assert r.status_code == 200
        body = r.json()
        assert body["recovered"] == 1
        assert body["items"][0]["restored_to"] == orig
        assert body["errors"] is None

        # File is back at original path with original content
        assert os.path.isfile(orig)
        with open(orig, "rb") as f:
            assert f.read() == b"jpeg"
        # Trash file is gone
        assert not os.path.exists(trash_path)
        # Manifest is gone (it had only one entry)
        assert not os.path.exists(manifest_path)

    def test_partial_recovery_keeps_remaining_entries_in_manifest(self, client, trash_root):
        """A manifest with three entries; recover one. The other two
        must remain in the manifest, and the manifest must persist."""
        orig_a = os.path.join(trash_root["originals"], "a.jpg")
        orig_b = os.path.join(trash_root["originals"], "b.jpg")
        orig_c = os.path.join(trash_root["originals"], "c.jpg")
        ta, mpath = _seed_trash_entry(trash_root["trash"], "20260101_100000", 1, orig_a)
        tb, _   = _seed_trash_entry(trash_root["trash"], "20260101_100000", 2, orig_b)
        tc, _   = _seed_trash_entry(trash_root["trash"], "20260101_100000", 3, orig_c)

        r = client.post("/trash/recover", json={"trash_paths": [tb]})
        assert r.json()["recovered"] == 1
        assert os.path.isfile(orig_b)
        # Other two stay trashed
        assert os.path.isfile(ta)
        assert os.path.isfile(tc)
        # Manifest still exists with 2 entries (1 and 3)
        with open(mpath) as f:
            kept = json.load(f)
        kept_pids = sorted(e["photo_id"] for e in kept)
        assert kept_pids == [1, 3]

    def test_recreates_missing_parent_directory(self, client, trash_root):
        """If the user removed the parent folder of the original file
        between dedupe and recover, recovery must mkdir -p and put the
        file back rather than failing."""
        deep = os.path.join(trash_root["originals"], "deeply", "nested", "gone")
        orig = os.path.join(deep, "photo.jpg")
        trash_path, _ = _seed_trash_entry(
            trash_root["trash"], "20260101_100000", 1, orig
        )
        # Note: 'deeply/nested/gone' does NOT exist on disk yet.
        assert not os.path.exists(deep)

        r = client.post("/trash/recover", json={"trash_paths": [trash_path]})
        assert r.json()["recovered"] == 1
        assert os.path.isfile(orig)

    def test_refuses_to_overwrite_existing_file_at_original_path(
        self, client, trash_root
    ):
        """A non-trash file already lives where the recovered one would
        go — must not overwrite. User-data preservation is paramount."""
        orig = os.path.join(trash_root["originals"], "photo.jpg")
        trash_path, mpath = _seed_trash_entry(
            trash_root["trash"], "20260101_100000", 1, orig
        )
        os.makedirs(os.path.dirname(orig), exist_ok=True)
        with open(orig, "wb") as f:
            f.write(b"existing")

        r = client.post("/trash/recover", json={"trash_paths": [trash_path]})
        body = r.json()
        assert body["recovered"] == 0
        assert body["errors"] and "already exists" in body["errors"][0]["error"]
        # Existing file untouched, trash file untouched, manifest unchanged
        assert open(orig, "rb").read() == b"existing"
        assert os.path.isfile(trash_path)
        assert os.path.isfile(mpath)

    def test_rejects_path_outside_trash_dir(self, client, trash_root, tmp_path):
        """Path-traversal defense: caller can't ask us to "recover" a
        random file from elsewhere on disk."""
        rogue = tmp_path / "rogue.jpg"
        rogue.write_bytes(b"x")

        r = client.post("/trash/recover", json={"trash_paths": [str(rogue)]})
        assert r.status_code == 200
        body = r.json()
        assert body["recovered"] == 0
        assert body["errors"]
        assert any("not inside trash" in e["error"] for e in body["errors"])
        # The rogue file is NOT moved
        assert rogue.exists()

    def test_rejects_path_traversal_with_dotdot(self, client, trash_root, tmp_path):
        """A trash-rooted path with .. that escapes still gets caught
        because we resolve realpath before the prefix check."""
        outside = tmp_path / "outside.jpg"
        outside.write_bytes(b"x")
        # build a "trash" path that resolves outside
        rel = os.path.join(trash_root["trash"], "..", "..", os.path.basename(str(tmp_path)),
                            "outside.jpg")
        r = client.post("/trash/recover", json={"trash_paths": [rel]})
        body = r.json()
        assert body["recovered"] == 0
        assert any("not inside trash" in e["error"] for e in body["errors"])
        assert outside.exists()

    def test_missing_trash_file_drops_entry_with_error(self, client, trash_root):
        """If the trash file was manually deleted but the manifest still
        references it, the request reports an error AND prunes the dead
        entry from the manifest so the user doesn't see it again."""
        orig = os.path.join(trash_root["originals"], "x.jpg")
        trash_path, mpath = _seed_trash_entry(
            trash_root["trash"], "20260101_100000", 1, orig
        )
        os.remove(trash_path)

        r = client.post("/trash/recover", json={"trash_paths": [trash_path]})
        body = r.json()
        assert body["recovered"] == 0
        assert any("file missing" in e["error"] for e in body["errors"])
        # Manifest now empty -> deleted entirely
        assert not os.path.exists(mpath)

    def test_requires_trash_paths_in_body(self, client, trash_root):
        r = client.post("/trash/recover", json={})
        assert r.status_code == 400
        assert "trash_paths" in r.json()["error"]

    def test_mixed_recover_and_failure_in_one_request(self, client, trash_root):
        """One trash file recovers cleanly; another collides with an
        existing file at its original path. Endpoint reports both
        outcomes in a single response."""
        ok_orig = os.path.join(trash_root["originals"], "ok.jpg")
        bad_orig = os.path.join(trash_root["originals"], "bad.jpg")
        ok_trash, _   = _seed_trash_entry(trash_root["trash"], "20260101_100000", 1, ok_orig)
        bad_trash, _  = _seed_trash_entry(trash_root["trash"], "20260101_100000", 2, bad_orig)
        # Pre-create the conflicting file so recovery of bad_trash fails
        os.makedirs(os.path.dirname(bad_orig), exist_ok=True)
        with open(bad_orig, "wb") as f:
            f.write(b"existing")

        r = client.post("/trash/recover",
                        json={"trash_paths": [ok_trash, bad_trash]})
        body = r.json()
        assert body["recovered"] == 1
        assert os.path.isfile(ok_orig)
        assert os.path.isfile(bad_trash)  # not moved
        assert any("already exists" in e["error"] for e in body["errors"])
