"""Performance tests for /similarity-groups (the threshold-slider hot path).

The slider issues a fresh /similarity-groups request every time the
user changes the threshold. Earlier versions called PIL Image.open
(EXIF parse, ~5ms cold per file) for every cluster member, plus an
os.path.isfile stat per member — a 1000-photo / 100-cluster build
took ~60ms on cold cache and the slider felt laggy on bigger
collections.

The hot path now does NO disk I/O: it copies pre-cached photo_meta
into per-member dicts, runs np.dot for ref-vs-member rescoring, and
emits the response. width / height / created_date are returned as
None and lazy-loaded by the lightbox via /photos/{id}/image-info.

Hard budget asserted below:
    2_000 photos / 200 clusters → < 100 ms per call (cold and warm)
This is well under the 300 ms frontend debounce, so a slider drag
never queues up a backlog of in-flight requests.
"""
import os
import tempfile
import time

import numpy as np
import pytest
from PIL import Image

import app.main as app_main


def _build_cache(n_photos: int, cluster_size: int, with_real_files: bool):
    """Install a synthetic similarity cache with `n_photos / cluster_size`
    clusters, each of size `cluster_size`. When with_real_files=True we
    write actual JPEGs to a temp dir — the OLD hot path would parse
    these via PIL on every request; the NEW one doesn't touch disk."""
    n_clusters = n_photos // cluster_size
    vectors = np.zeros((n_photos, 4), dtype=np.float32)
    for c in range(n_clusters):
        for k in range(cluster_size):
            v = np.zeros(4, dtype=np.float32)
            v[c % 4] = 1.0
            vectors[c * cluster_size + k] = v

    adjacency: list = [[] for _ in range(n_photos)]
    for c in range(n_clusters):
        start = c * cluster_size
        for i in range(cluster_size):
            for j in range(cluster_size):
                if i != j:
                    adjacency[start + i].append((start + j, 1.0))

    photo_ids = list(range(1, n_photos + 1))

    if with_real_files:
        tmpdir = tempfile.mkdtemp()
        # Cheap small JPEGs — content doesn't matter, only that PIL can
        # open them. The OLD code path would parse EXIF for each on
        # every request.
        paths = []
        for pid in photo_ids:
            p = os.path.join(tmpdir, f"p{pid}.jpg")
            Image.new("RGB", (32, 32), color="red").save(p, "JPEG")
            paths.append(p)
    else:
        tmpdir = None
        paths = [f"/tmp/missing/p{pid}.jpg" for pid in photo_ids]

    photo_meta = {
        pid: {
            "filename": f"p{pid}.jpg",
            "file_path": paths[idx],
            "file_size": 1_000_000,
            "mime_type": "image/jpeg",
            "uploaded_at": "2024-01-01T00:00:00",
        }
        for idx, pid in enumerate(photo_ids)
    }

    app_main._sim_cache.update(
        data={
            "vectors": vectors,
            "photo_ids": photo_ids,
            "point_ids": [f"q{pid}" for pid in photo_ids],
            "adjacency": adjacency,
            "cache_threshold": 0.7,
        },
        meta=photo_meta,
    )
    return tmpdir


def _safe_clear_image_cache():
    """The autouse fixture may run after monkeypatch swaps
    `_read_image_info` for an instrumented wrapper that lacks
    `cache_clear`. Defensive: only call if the attribute exists."""
    fn = getattr(app_main, "_read_image_info", None)
    if fn is not None and hasattr(fn, "cache_clear"):
        fn.cache_clear()


@pytest.fixture(autouse=True)
def _reset_cache():
    app_main._sim_cache.update(data=None, meta=None)
    _safe_clear_image_cache()
    yield
    app_main._sim_cache.update(data=None, meta=None)
    _safe_clear_image_cache()


# ----------------------------- perf budgets -----------------------------


# Generous absolute budget — chosen well under the 300ms frontend debounce
# so even on a slow CI runner we stay below the user-perceptible threshold.
PERF_BUDGET_MS = 100.0


class TestThresholdSliderHotPath:
    def test_2000_photos_200_clusters_under_budget_with_real_files(self):
        """The user's reported regression: with real files on disk and a
        cold _read_image_info cache, the OLD path took ~60ms for 1000
        photos and scaled linearly. We now budget < 100ms for 2x that
        volume regardless of cache warmth, since we no longer touch
        disk."""
        tmpdir = _build_cache(n_photos=2000, cluster_size=10,
                              with_real_files=True)
        try:
            t0 = time.perf_counter()
            groups = app_main._build_similarity_groups_from_qdrant(0.85)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert len(groups) == 200
            assert elapsed_ms < PERF_BUDGET_MS, (
                f"slider hot path too slow: {elapsed_ms:.0f}ms — was the "
                f"per-member _read_image_info / os.path.isfile re-introduced?"
            )
        finally:
            if tmpdir:
                import shutil; shutil.rmtree(tmpdir, ignore_errors=True)

    def test_repeated_calls_dont_get_slower(self):
        """Two back-to-back calls (the slider drag pattern) should each
        complete within budget. A regression that caches per-call would
        slow only the first; one that recomputes per-call would slow all."""
        _build_cache(n_photos=1000, cluster_size=10, with_real_files=False)
        timings = []
        for _ in range(5):
            t0 = time.perf_counter()
            app_main._build_similarity_groups_from_qdrant(0.85)
            timings.append((time.perf_counter() - t0) * 1000)
        # Worst single call < budget
        assert max(timings) < PERF_BUDGET_MS, (
            f"hot path regressed: timings={['%.1f' % t for t in timings]}ms"
        )

    def test_hot_path_does_not_call_read_image_info(self, monkeypatch):
        """REGRESSION-FENCE: PIL EXIF parse must not happen during the
        slider's request. Even if the LRU is cold, we skip it entirely
        and let the lightbox load image-info on demand."""
        _build_cache(n_photos=200, cluster_size=10, with_real_files=False)
        called = {"n": 0}
        original = app_main._read_image_info

        def _instrumented(*args, **kw):
            called["n"] += 1
            return original(*args, **kw)
        monkeypatch.setattr(app_main, "_read_image_info", _instrumented)

        app_main._build_similarity_groups_from_qdrant(0.85)
        assert called["n"] == 0, (
            f"_read_image_info called {called['n']} times during the "
            f"hot path; this is the per-photo file I/O regression "
            f"that made the slider laggy"
        )


class TestThresholdSliderResponseShape:
    """Even though we no longer load image-info eagerly, the response
    shape must remain stable — frontend code may read width / height /
    created_date as `null` (which it already handles)."""

    def test_member_dict_keys_unchanged_with_image_info_null(self):
        _build_cache(n_photos=20, cluster_size=10, with_real_files=False)
        groups = app_main._build_similarity_groups_from_qdrant(0.85)
        assert groups
        ref = groups[0]["reference_photo"]
        # Required identity / display fields
        for k in ("photo_id", "filename", "path", "similarity_score",
                  "file_size", "file_path", "mime_type", "uploaded_at"):
            assert k in ref, f"missing required field: {k}"
        # Lazy-loaded fields are present but null — frontend renders
        # nothing for these and the lightbox fills them in via
        # /photos/{id}/image-info.
        assert ref["width"] is None
        assert ref["height"] is None
        assert ref["created_date"] is None


class TestPhotoImageInfoEndpoint:
    """The /photos/{id}/image-info endpoint that backs the lightbox's
    lazy load. The slider's hot path skips this; opening the lightbox
    pays the PIL parse once per photo, and it's LRU-cached after."""

    def test_returns_dimensions_for_valid_photo(self, tmp_path, monkeypatch):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import Base, Photo
        from datetime import datetime
        from fastapi.testclient import TestClient

        engine = create_engine(f"sqlite:///{tmp_path}/x.db")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        # Real JPEG of known dimensions.
        photo_path = tmp_path / "img.jpg"
        Image.new("RGB", (640, 480), color="blue").save(photo_path, "JPEG")
        sess = Session()
        try:
            p = Photo(filename="img.jpg", file_path=str(photo_path),
                      file_size=os.path.getsize(photo_path),
                      mime_type="image/jpeg",
                      uploaded_at=datetime(2024, 1, 1))
            sess.add(p); sess.commit()
            pid = p.id
        finally:
            sess.close()

        class _Mgr:
            def SessionLocal(self):
                return Session()
        monkeypatch.setattr(app_main, "job_queue_manager", _Mgr())

        client = TestClient(app_main.app)
        r = client.get(f"/photos/{pid}/image-info")
        assert r.status_code == 200
        body = r.json()
        assert body["photo_id"] == pid
        assert body["width"] == 640
        assert body["height"] == 480
        assert body["created_date"] is not None  # set from mtime fallback

    def test_returns_404_for_missing_photo(self, tmp_path, monkeypatch):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import Base
        from fastapi.testclient import TestClient

        engine = create_engine(f"sqlite:///{tmp_path}/x.db")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        class _Mgr:
            def SessionLocal(self):
                return Session()
        monkeypatch.setattr(app_main, "job_queue_manager", _Mgr())

        client = TestClient(app_main.app)
        r = client.get("/photos/9999/image-info")
        assert r.status_code == 404

    def test_returns_nulls_when_file_not_on_disk(self, tmp_path, monkeypatch):
        """Photo row exists but the file was deleted by the user. The
        endpoint succeeds with null fields (graceful degradation —
        the lightbox just hides those rows)."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import Base, Photo
        from datetime import datetime
        from fastapi.testclient import TestClient

        engine = create_engine(f"sqlite:///{tmp_path}/x.db")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        sess = Session()
        try:
            p = Photo(filename="ghost.jpg", file_path=str(tmp_path / "ghost.jpg"),
                      file_size=0, mime_type="image/jpeg",
                      uploaded_at=datetime(2024, 1, 1))
            sess.add(p); sess.commit()
            pid = p.id
        finally:
            sess.close()

        class _Mgr:
            def SessionLocal(self):
                return Session()
        monkeypatch.setattr(app_main, "job_queue_manager", _Mgr())

        client = TestClient(app_main.app)
        r = client.get(f"/photos/{pid}/image-info")
        assert r.status_code == 200
        body = r.json()
        assert body["width"] is None
        assert body["height"] is None
        assert body["created_date"] is None
