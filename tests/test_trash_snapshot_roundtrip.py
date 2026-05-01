"""Tests for the v2 trash-manifest schema and snapshot-based recovery.

Round-trip contract: when a photo is dedupe'd and then recovered, the
Postgres row + ProcessingState row + Embedding row + Qdrant point all
reappear with the SAME data — no DINOv2 inference, no metadata
extraction. Recovery is purely "move file + replay snapshot".

Edge cases:
  - v1 (legacy) entries still recover the file; DB/Qdrant are left to
    the next folder rescan (back-compat).
  - Vector retrieve fails at delete time → snapshot has vector=None.
    Recovery still rewrites Photo + ProcessingState; Qdrant skip is
    safe (next scan rebuilds the embedding).
  - Photo row already exists at the same file_path (re-imported) →
    DB writes are skipped to preserve current state.
  - Snapshot missing entirely → file-only behavior matches v1.
  - Photo with NO embedding row at delete time → snapshot omits the
    embedding section; recovery rebuilds Photo + ProcessingState only.
"""
import json
import os
import shutil
import tempfile
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as app_main
from app.models import Base, Photo, Embedding, ProcessingState


# --------------------- shared harness ---------------------


class _RecordingQdrant:
    """Tracks the calls dedupe + recover make. Vector responses are
    deterministic so the round-trip test can assert exact equality."""

    def __init__(self, vectors_by_point_id=None):
        self._vectors = vectors_by_point_id or {}
        self.deleted_points = []
        self.upserted_points = []  # list of (id, vector, payload)

    def retrieve(self, *, collection_name, ids, with_vectors=False, **_):
        recs = []
        for pid in ids:
            v = self._vectors.get(pid)
            recs.append(MagicMock(id=pid, vector=v, payload={}))
        return recs

    def delete(self, *, collection_name, points_selector):
        self.deleted_points.extend(list(points_selector))

    def upsert(self, *, collection_name, points):
        for p in points:
            self.upserted_points.append({
                "id": p.id, "vector": list(p.vector), "payload": dict(p.payload),
            })


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """File-backed SQLite + recording Qdrant + isolated trash dir.

    Returns: a dict with `engine`, `SessionLocal`, `qdrant`, `client`,
    `keep_dir`, `original_path` for tests to use."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    keep_dir = tmp_path / "keep"
    keep_dir.mkdir()
    original_path = keep_dir / "x.jpg"
    original_path.write_bytes(b"keeper-bytes")

    trash_dir = tmp_path / "trash"
    monkeypatch.setattr(app_main, "TRASH_DIR", str(trash_dir))

    qdrant = _RecordingQdrant()

    class _Mgr:
        def __init__(self):
            self.qdrant_client = qdrant
        def SessionLocal(self):
            return SessionLocal()

    monkeypatch.setattr(app_main, "job_queue_manager", _Mgr())

    # Stub the index recompute (would scroll Qdrant on the real path).
    async def _noop():
        return None
    monkeypatch.setattr(app_main, "_recompute_sim_cache", _noop)

    return {
        "SessionLocal": SessionLocal,
        "qdrant": qdrant,
        "client": TestClient(app_main.app),
        "keep_dir": keep_dir,
        "trash_dir": trash_dir,
        "original_path": original_path,
    }


def _seed_photo(session, file_path, qdrant_point_id="qpt", file_hash="abc123",
                file_size=12, mime_type="image/jpeg",
                uploaded_at=None, status="completed"):
    """Insert a Photo + ProcessingState + Embedding triple. Returns
    the new photo_id."""
    p = Photo(
        filename=os.path.basename(file_path),
        file_path=str(file_path),
        file_size=file_size,
        mime_type=mime_type,
        file_hash=file_hash,
        uploaded_at=uploaded_at or datetime(2024, 1, 1, 8, 0, 0),
    )
    session.add(p)
    session.commit()
    session.add(ProcessingState(
        photo_id=p.id,
        status=status,
        extraction_status="completed",
        embedding_status="completed",
        completed_at=datetime(2024, 1, 1, 8, 5, 0),
    ))
    session.add(Embedding(
        photo_id=p.id,
        embedding_model="dinov2_vits14",
        vector_dimension=4,
        qdrant_point_id=qdrant_point_id,
    ))
    session.commit()
    return p.id


def _read_only_manifest(trash_dir):
    """Return the single manifest's entries (asserting exactly one)."""
    files = [f for f in trash_dir.iterdir() if f.name.endswith("_manifest.json")]
    assert len(files) == 1, f"expected exactly one manifest, got {files}"
    return json.loads(files[0].read_text())


# --------------------- tests ---------------------


class TestSnapshotCapture:
    def test_dedupe_writes_v2_manifest_with_full_snapshot(self, harness):
        """After /deduplicate, the manifest entry must include schema
        version 2 + photo + processing_state + embedding (with vector)."""
        VECTOR = [0.1, 0.2, 0.3, 0.4]
        sess = harness["SessionLocal"]()
        try:
            pid = _seed_photo(sess, harness["original_path"],
                              qdrant_point_id="qpt-1")
        finally:
            sess.close()
        harness["qdrant"]._vectors["qpt-1"] = VECTOR

        r = harness["client"].post("/deduplicate", json={"photo_ids": [pid]})
        assert r.status_code == 200
        body = r.json()
        assert body["moved_to_trash"] == 1

        entries = _read_only_manifest(harness["trash_dir"])
        assert len(entries) == 1
        e = entries[0]
        assert e["schema_version"] == 2
        assert e["photo_id"] == pid
        assert e["original"] == str(harness["original_path"])
        assert e["trashed_at"]  # ISO string
        # Photo snapshot
        assert e["photo"]["filename"] == "x.jpg"
        assert e["photo"]["file_hash"] == "abc123"
        assert e["photo"]["file_size"] == 12
        assert e["photo"]["mime_type"] == "image/jpeg"
        # ProcessingState snapshot
        assert e["processing_state"]["status"] == "completed"
        # Embedding snapshot WITH the actual vector
        assert e["embedding"]["embedding_model"] == "dinov2_vits14"
        assert e["embedding"]["vector_dimension"] == 4
        assert e["embedding"]["vector"] == pytest.approx(VECTOR)

    def test_snapshot_omits_vector_when_qdrant_retrieve_fails(self, harness):
        """If the vector can't be pulled at delete time (Qdrant down,
        point already gone, etc.), the snapshot still gets written —
        with vector=None. Recovery later falls back to file-only DB
        rebuild."""
        sess = harness["SessionLocal"]()
        try:
            pid = _seed_photo(sess, harness["original_path"],
                              qdrant_point_id="qpt-missing")
        finally:
            sess.close()

        # Make retrieve raise
        def _boom(*a, **kw):
            raise RuntimeError("qdrant down")
        harness["qdrant"].retrieve = _boom

        r = harness["client"].post("/deduplicate", json={"photo_ids": [pid]})
        assert r.status_code == 200

        entries = _read_only_manifest(harness["trash_dir"])
        assert entries[0]["embedding"]["vector"] is None

    def test_snapshot_omits_embedding_section_for_unprocessed_photo(self, harness):
        """A photo that was trashed BEFORE its embedding finished should
        produce a v2 entry with no `embedding` key."""
        sess = harness["SessionLocal"]()
        try:
            # Insert Photo + ProcessingState only — no Embedding row.
            p = Photo(filename="x.jpg",
                      file_path=str(harness["original_path"]),
                      file_size=12, mime_type="image/jpeg",
                      uploaded_at=datetime(2024, 1, 1))
            sess.add(p); sess.commit()
            sess.add(ProcessingState(photo_id=p.id, status="pending",
                                      extraction_status="pending",
                                      embedding_status="pending"))
            sess.commit()
            pid = p.id
        finally:
            sess.close()

        r = harness["client"].post("/deduplicate", json={"photo_ids": [pid]})
        assert r.status_code == 200

        entries = _read_only_manifest(harness["trash_dir"])
        assert "embedding" not in entries[0]
        assert entries[0]["photo"]["filename"] == "x.jpg"
        assert entries[0]["processing_state"]["status"] == "pending"


class TestExecuteDedupeFailureSafety:
    """Failure-mode safety: if the file move into trash fails, the
    photo's DB rows MUST stay intact and no manifest entry must be
    written. Otherwise we'd silently destroy the user's only record
    of the photo (file still on disk, but DB and Qdrant entries gone
    and no trash entry to recover from).
    """

    def test_move_failure_leaves_db_rows_intact_and_no_manifest_entry(
        self, harness, monkeypatch,
    ):
        """REGRESSION: when shutil.move raises (permission denied,
        cross-device on a read-only fs, antivirus lock, …) the photo's
        Photo + Embedding + ProcessingState rows must NOT be deleted —
        the file is still on disk at the original path and we can
        retry. The manifest must not list the photo either."""
        VECTOR = [0.1, 0.2, 0.3, 0.4]
        sess = harness["SessionLocal"]()
        try:
            pid = _seed_photo(sess, harness["original_path"],
                              qdrant_point_id="qpt-fail")
        finally:
            sess.close()
        harness["qdrant"]._vectors["qpt-fail"] = VECTOR

        # Sabotage the move.
        import shutil as _shutil
        def _boom(src, dst):
            raise PermissionError("simulated antivirus lock")
        monkeypatch.setattr(_shutil, "move", _boom)

        r = harness["client"].post("/deduplicate", json={"photo_ids": [pid]})
        assert r.status_code == 200
        body = r.json()
        assert body["moved_to_trash"] == 0, "no file successfully moved"
        # The endpoint response includes the per-photo error
        assert body.get("errors"), "must report move failure"

        # File is still at original location
        assert harness["original_path"].is_file()
        assert harness["original_path"].read_bytes() == b"keeper-bytes"

        # DB rows are still intact — the photo can be retried
        check = harness["SessionLocal"]()
        try:
            assert check.query(Photo).count() == 1, (
                "DB rows were purged for a photo whose file move failed; "
                "this destroys the user's only record of the photo"
            )
            assert check.query(Embedding).count() == 1
            assert check.query(ProcessingState).count() == 1
        finally:
            check.close()

        # No trash manifest was written for this photo
        manifests = [f for f in harness["trash_dir"].iterdir()
                     if f.name.endswith("_manifest.json")]
        for m in manifests:
            entries = json.loads(m.read_text())
            for e in entries:
                assert e.get("photo_id") != pid, (
                    "photo with failed move appeared in manifest"
                )

    def test_partial_failure_only_purges_successfully_trashed_photos(
        self, harness, monkeypatch,
    ):
        """Two photos in one /deduplicate call: one moves OK, one's
        move raises. Only the successful one's DB rows must be purged;
        the failed one stays in the DB."""
        # Set up two photos.
        ok_path = harness["keep_dir"] / "ok.jpg"
        bad_path = harness["keep_dir"] / "bad.jpg"
        ok_path.write_bytes(b"ok")
        bad_path.write_bytes(b"bad")

        sess = harness["SessionLocal"]()
        try:
            ok_id = _seed_photo(sess, ok_path, qdrant_point_id="qok")
            bad_id = _seed_photo(sess, bad_path, qdrant_point_id="qbad")
        finally:
            sess.close()
        harness["qdrant"]._vectors["qok"] = [0.1, 0.2, 0.3, 0.4]
        harness["qdrant"]._vectors["qbad"] = [0.4, 0.3, 0.2, 0.1]

        # Sabotage the move ONLY for bad.jpg
        import shutil as _shutil
        real_move = _shutil.move
        def _selective(src, dst):
            if "bad.jpg" in src:
                raise PermissionError("simulated lock")
            return real_move(src, dst)
        monkeypatch.setattr(_shutil, "move", _selective)

        r = harness["client"].post("/deduplicate",
                                    json={"photo_ids": [ok_id, bad_id]})
        body = r.json()
        assert body["moved_to_trash"] == 1
        assert body.get("errors")  # bad photo errored

        # bad.jpg is still on disk and in DB
        assert bad_path.is_file()
        check = harness["SessionLocal"]()
        try:
            assert check.query(Photo).filter(Photo.id == bad_id).count() == 1, (
                "failed-move photo's DB rows were purged"
            )
            assert check.query(Embedding).filter(
                Embedding.photo_id == bad_id).count() == 1
            # ok.jpg's rows are gone
            assert check.query(Photo).filter(Photo.id == ok_id).count() == 0
        finally:
            check.close()


class TestRecoveryFromSnapshot:
    def test_full_round_trip_recreates_all_rows_and_qdrant_point(self, harness):
        """Dedupe → recover. Postgres + Qdrant end up populated as if
        the photo had never been deleted, WITHOUT re-running DINOv2."""
        VECTOR = [0.5, 0.4, 0.3, 0.2]
        sess = harness["SessionLocal"]()
        try:
            pid = _seed_photo(sess, harness["original_path"],
                              qdrant_point_id="qpt-roundtrip",
                              file_hash="hash-RT", file_size=99,
                              mime_type="image/png")
        finally:
            sess.close()
        harness["qdrant"]._vectors["qpt-roundtrip"] = VECTOR

        # Trash it.
        r = harness["client"].post("/deduplicate", json={"photo_ids": [pid]})
        assert r.status_code == 200
        assert "qpt-roundtrip" in harness["qdrant"].deleted_points

        # Verify file is in trash, original is gone, DB rows are gone.
        assert not harness["original_path"].exists()
        check = harness["SessionLocal"]()
        try:
            assert check.query(Photo).count() == 0
            assert check.query(Embedding).count() == 0
            assert check.query(ProcessingState).count() == 0
        finally:
            check.close()

        entries = _read_only_manifest(harness["trash_dir"])
        trash_path = entries[0]["trash"]

        # Recover. No re-embedding — the snapshot's vector is reused.
        r = harness["client"].post("/trash/recover",
                                    json={"trash_paths": [trash_path]})
        assert r.status_code == 200
        body = r.json()
        assert body["recovered"] == 1
        item = body["items"][0]
        assert item["db_restored"] is True
        assert item["qdrant_upserted"] is True

        # File is back at its original location, with original bytes.
        assert harness["original_path"].is_file()
        assert harness["original_path"].read_bytes() == b"keeper-bytes"

        # Postgres rows reappear with same values (new auto-increment id).
        check = harness["SessionLocal"]()
        try:
            ps = check.query(Photo).all()
            assert len(ps) == 1
            recovered = ps[0]
            assert recovered.file_path == str(harness["original_path"])
            assert recovered.filename == "x.jpg"
            assert recovered.file_hash == "hash-RT"
            assert recovered.file_size == 99
            assert recovered.mime_type == "image/png"

            ems = check.query(Embedding).all()
            assert len(ems) == 1
            assert ems[0].photo_id == recovered.id
            assert ems[0].embedding_model == "dinov2_vits14"
            assert ems[0].vector_dimension == 4

            states = check.query(ProcessingState).all()
            assert len(states) == 1
            assert states[0].photo_id == recovered.id
            assert states[0].status == "completed"
        finally:
            check.close()

        # Qdrant: a NEW point id was upserted with the SAME vector and a
        # payload pointing at the new photo_id.
        assert len(harness["qdrant"].upserted_points) == 1
        upserted = harness["qdrant"].upserted_points[0]
        assert upserted["vector"] == pytest.approx(VECTOR)
        assert upserted["payload"]["photo_id"] == recovered.id
        # The new point id is distinct from the deleted one.
        assert upserted["id"] != "qpt-roundtrip"

        # Manifest is gone (only one entry, all consumed).
        manifests = [f for f in harness["trash_dir"].iterdir()
                     if f.name.endswith("_manifest.json")]
        assert manifests == []

    def test_recover_when_photo_already_in_db_skips_db_writes(self, harness):
        """Re-import scenario: while the photo was in trash, the user
        re-added it via a folder scan. The recover path must not double-
        insert; it should report db_restored=False with the reason."""
        sess = harness["SessionLocal"]()
        try:
            pid = _seed_photo(sess, harness["original_path"],
                              qdrant_point_id="qpt-collide")
        finally:
            sess.close()
        harness["qdrant"]._vectors["qpt-collide"] = [0.1, 0.2, 0.3, 0.4]

        harness["client"].post("/deduplicate", json={"photo_ids": [pid]})
        entries = _read_only_manifest(harness["trash_dir"])
        trash_path = entries[0]["trash"]

        # Simulate re-import: insert a new Photo row at the same path
        # while the file is still in the trash.
        sess = harness["SessionLocal"]()
        try:
            sess.add(Photo(filename="x.jpg",
                           file_path=str(harness["original_path"]),
                           file_size=99, mime_type="image/jpeg",
                           uploaded_at=datetime(2025, 1, 1)))
            sess.commit()
            new_id = sess.query(Photo.id).first()[0]
        finally:
            sess.close()

        # We must also remove the file at original_path so the recover
        # endpoint reaches the DB-restore step (it refuses if a file is
        # already at the destination — which is a DIFFERENT, separate
        # safety check). Here we're testing the DB-collision branch.
        # In practice, the OS file collision would block first; this
        # test isolates the DB-side check.
        # … so put the file BACK in trash (it's there) and clear the
        # original-path file so the move can succeed.
        # The dedupe flow already moved the original to trash, so
        # original_path doesn't exist on disk. Good.
        assert not harness["original_path"].exists()

        r = harness["client"].post("/trash/recover",
                                    json={"trash_paths": [trash_path]})
        body = r.json()
        assert body["recovered"] == 1
        item = body["items"][0]
        assert item["db_restored"] is False
        assert item["reason"] == "photo_row_already_exists"
        assert item["existing_photo_id"] == new_id

        # File is back; Qdrant did NOT get a duplicate upsert.
        assert harness["original_path"].is_file()
        assert harness["qdrant"].upserted_points == []

        # Only the pre-existing Photo row exists (no row added by recover).
        check = harness["SessionLocal"]()
        try:
            assert check.query(Photo).count() == 1
        finally:
            check.close()

    def test_recover_with_v1_legacy_entry_recovers_file_only(self, harness):
        """A v1 manifest entry (no schema_version, no photo/embedding
        keys) should still recover the file. DB stays empty — the next
        rescan rebuilds it. This is the back-compat contract."""
        # Hand-craft a legacy entry (no dedupe call → no v2 snapshot).
        harness["trash_dir"].mkdir(exist_ok=True)
        legacy_trash_file = harness["trash_dir"] / "legacy.jpg"
        legacy_trash_file.write_bytes(b"legacy-bytes")
        manifest_path = harness["trash_dir"] / "20260101_100000_manifest.json"
        manifest_path.write_text(json.dumps([{
            "photo_id": 99,
            "original": str(harness["keep_dir"] / "legacy.jpg"),
            "trash": str(legacy_trash_file),
        }]))

        r = harness["client"].post("/trash/recover",
                                    json={"trash_paths": [str(legacy_trash_file)]})
        body = r.json()
        assert body["recovered"] == 1
        item = body["items"][0]
        assert item["db_restored"] is False
        assert item["reason"] == "legacy_v1_entry"

        recovered_path = harness["keep_dir"] / "legacy.jpg"
        assert recovered_path.is_file()
        assert recovered_path.read_bytes() == b"legacy-bytes"
        # No DB or Qdrant writes
        check = harness["SessionLocal"]()
        try:
            assert check.query(Photo).count() == 0
        finally:
            check.close()
        assert harness["qdrant"].upserted_points == []

    def test_recover_with_missing_vector_falls_back_to_db_only(self, harness):
        """If the snapshot has no vector (Qdrant retrieve failed at
        dedupe time), recovery still rebuilds Photo + ProcessingState
        + Embedding rows but skips the Qdrant upsert. The next
        embedding job (or a manual re-process) will refill it."""
        sess = harness["SessionLocal"]()
        try:
            pid = _seed_photo(sess, harness["original_path"],
                              qdrant_point_id="qpt-novec")
        finally:
            sess.close()
        # Don't register a vector → retrieve returns vector=None.

        harness["client"].post("/deduplicate", json={"photo_ids": [pid]})
        entries = _read_only_manifest(harness["trash_dir"])
        # Confirm snapshot lacks the vector.
        assert entries[0]["embedding"]["vector"] is None

        trash_path = entries[0]["trash"]
        r = harness["client"].post("/trash/recover",
                                    json={"trash_paths": [trash_path]})
        body = r.json()
        assert body["recovered"] == 1
        item = body["items"][0]
        assert item["db_restored"] is True
        assert item["qdrant_upserted"] is False

        # DB rows are back.
        check = harness["SessionLocal"]()
        try:
            assert check.query(Photo).count() == 1
            emb = check.query(Embedding).first()
            # Embedding row created with qdrant_point_id=None, since
            # the upsert didn't happen.
            assert emb.qdrant_point_id is None
        finally:
            check.close()

    def test_recover_handles_qdrant_upsert_failure_without_rolling_back_db(
        self, harness,
    ):
        """If Qdrant is down at recover time, we still want the Photo
        row back (file moved + metadata in DB). The user can re-trigger
        the embedding later."""
        VECTOR = [0.1, 0.2, 0.3, 0.4]
        sess = harness["SessionLocal"]()
        try:
            pid = _seed_photo(sess, harness["original_path"],
                              qdrant_point_id="qpt-bad-recover")
        finally:
            sess.close()
        harness["qdrant"]._vectors["qpt-bad-recover"] = VECTOR

        harness["client"].post("/deduplicate", json={"photo_ids": [pid]})
        entries = _read_only_manifest(harness["trash_dir"])
        trash_path = entries[0]["trash"]

        # Make the next upsert blow up.
        def _boom(*a, **kw):
            raise RuntimeError("qdrant down at recover time")
        harness["qdrant"].upsert = _boom

        r = harness["client"].post("/trash/recover",
                                    json={"trash_paths": [trash_path]})
        body = r.json()
        assert body["recovered"] == 1
        item = body["items"][0]
        assert item["db_restored"] is True
        assert item["qdrant_upserted"] is False

        check = harness["SessionLocal"]()
        try:
            assert check.query(Photo).count() == 1
            emb = check.query(Embedding).first()
            assert emb.qdrant_point_id is None  # upsert failed; not stored
        finally:
            check.close()

    def test_recover_round_trip_preserves_vector_byte_for_byte(self, harness):
        """The 384-element vectors that DINOv2 produces in production
        must round-trip exactly through JSON. We use 4 elements with
        recognizable float patterns; assert equality with the original
        list."""
        VECTOR = [0.123456789, -0.987654321, 1e-10, 1.0]
        sess = harness["SessionLocal"]()
        try:
            pid = _seed_photo(sess, harness["original_path"],
                              qdrant_point_id="qpt-precise")
        finally:
            sess.close()
        harness["qdrant"]._vectors["qpt-precise"] = VECTOR

        harness["client"].post("/deduplicate", json={"photo_ids": [pid]})
        entries = _read_only_manifest(harness["trash_dir"])
        # Vector from manifest matches input within float64 precision
        assert entries[0]["embedding"]["vector"] == pytest.approx(VECTOR,
                                                                  abs=1e-12)

        trash_path = entries[0]["trash"]
        harness["client"].post("/trash/recover",
                                json={"trash_paths": [trash_path]})

        # And the upsert at recover time used the same numbers.
        upserted = harness["qdrant"].upserted_points[0]
        assert upserted["vector"] == pytest.approx(VECTOR, abs=1e-12)
