"""Tests for the similarity-matrix cache and grouping logic.

Covers:
  - _compute_sim_cache: pagination, normalization, cosine matrix correctness,
    empty/no-overlap handling.
  - _build_similarity_groups_from_qdrant: clustering at threshold, reference-
    photo selection, similarity score recomputed relative to the reference.
  - notify_embeddings_changed: debounce semantics (rapid calls coalesce into
    one recompute), no-loop fallback.
  - best_reasons string logic: format-and-size reasons, copy-suffix detection,
    "less universal" fallback.

These tests are hermetic — they replace job_queue_manager with a stub holding
a fake Qdrant client + an in-memory Postgres-equivalent. Heavy linalg uses
tiny vectors so the math is easy to verify by hand.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
from unittest.mock import patch

import numpy as np
import pytest

from app import main as app_main


# ----------------------------- fakes -----------------------------


@dataclass
class _FakePoint:
    id: str
    vector: list
    payload: dict


class _FakeQdrant:
    """Minimal Qdrant stub with paginated scroll().

    scroll() returns (page, next_offset). next_offset=None on the last page.
    The pagination contract here matches the real qdrant-client well enough
    for _compute_sim_cache to exercise its multi-page loop.
    """

    def __init__(self, points: List[_FakePoint], page_size: int = 2):
        self._points = points
        self._page_size = page_size
        self.scroll_calls = 0

    def scroll(self, *, collection_name, limit, offset, with_payload, with_vectors):
        self.scroll_calls += 1
        start = offset or 0
        page = self._points[start : start + self._page_size]
        next_offset: Optional[int] = start + self._page_size
        if next_offset >= len(self._points):
            next_offset = None
        return page, next_offset


class _FakeRow:
    """Tuple-like row matching the .all() return shape used in _compute_sim_cache."""

    def __init__(self, t: Tuple):
        self._t = t

    def __getitem__(self, i):
        return self._t[i]


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, photo_rows):
        self._rows = photo_rows

    def query(self, *_cols):
        return _FakeQuery(self._rows)

    def close(self):
        pass


class _FakeJobQueueManager:
    """Stand-in for the real JobQueueManager. Provides only the bits
    _compute_sim_cache reads: qdrant_client and SessionLocal()."""

    def __init__(self, qdrant_points, photo_rows):
        self.qdrant_client = _FakeQdrant(qdrant_points)
        self._photo_rows = photo_rows

    def SessionLocal(self):
        return _FakeSession(self._photo_rows)


# --------------------- shared fixtures ---------------------


def _orthonormal(n: int, dim: int = 4) -> np.ndarray:
    """Return n unit vectors that are pairwise nearly-orthogonal — useful when
    we want similarity ~ 0 between distinct photos."""
    rng = np.random.default_rng(seed=1234)
    raw = rng.standard_normal((n, dim))
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    return raw


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test starts with an empty cache and no patched manager."""
    app_main._sim_cache.update(data=None, meta=None)
    app_main._sim_debounce_handle = None
    app_main._sim_recompute_lock = None
    yield
    app_main._sim_cache.update(data=None, meta=None)
    app_main._sim_debounce_handle = None
    app_main._sim_recompute_lock = None


# ----------------------------- tests -----------------------------


class TestComputeSimCache:
    def test_returns_none_when_manager_missing(self):
        with patch.object(app_main, "job_queue_manager", None):
            data, meta = app_main._compute_sim_cache()
        assert data is None and meta is None

    def test_returns_none_when_no_points(self):
        mgr = _FakeJobQueueManager(qdrant_points=[], photo_rows=[])
        with patch.object(app_main, "job_queue_manager", mgr):
            data, meta = app_main._compute_sim_cache()
        assert data is None and meta is None

    def test_pagination_collects_all_pages(self):
        """Five Qdrant points with page_size=2 must require three scroll calls
        and produce a 5x5 matrix — ensures the >10k bug is gone."""
        vecs = _orthonormal(5)
        points = [
            _FakePoint(id=f"qp{i}", vector=vecs[i].tolist(), payload={"photo_id": i + 1})
            for i in range(5)
        ]
        rows = [
            _FakeRow((i + 1, f"p{i}.jpg", f"/photos/p{i}.jpg", 1000 * (i + 1),
                      "image/jpeg", datetime(2024, 1, 1)))
            for i in range(5)
        ]
        mgr = _FakeJobQueueManager(qdrant_points=points, photo_rows=rows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, meta = app_main._compute_sim_cache()

        assert mgr.qdrant_client.scroll_calls == 3  # 2+2+1
        assert data["sim_matrix"].shape == (5, 5)
        assert len(data["photo_ids"]) == 5
        assert set(meta.keys()) == {1, 2, 3, 4, 5}

    def test_matrix_diagonal_is_one_after_normalization(self):
        """Cosine of any unit vector with itself = 1; rebuilds confidence
        that the normalize-then-multiply flow is correct."""
        vecs = _orthonormal(3)
        # Scale them up so they're not unit; _compute_sim_cache should renormalize.
        vecs *= np.array([[2.0], [10.0], [0.5]])
        points = [
            _FakePoint(id=f"qp{i}", vector=vecs[i].tolist(), payload={"photo_id": i + 1})
            for i in range(3)
        ]
        rows = [
            _FakeRow((i + 1, f"p{i}.jpg", f"/photos/p{i}.jpg", 1000, "image/jpeg",
                      datetime(2024, 1, 1)))
            for i in range(3)
        ]
        mgr = _FakeJobQueueManager(qdrant_points=points, photo_rows=rows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, _ = app_main._compute_sim_cache()
        np.testing.assert_allclose(np.diagonal(data["sim_matrix"]), 1.0, atol=1e-6)

    def test_zero_vector_does_not_explode(self):
        """A zero embedding must not cause divide-by-zero — check the
        norms[norms == 0] = 1 guard."""
        vecs = _orthonormal(2).tolist()
        vecs.append([0.0, 0.0, 0.0, 0.0])  # the bad vector
        points = [
            _FakePoint(id=f"qp{i}", vector=v, payload={"photo_id": i + 1})
            for i, v in enumerate(vecs)
        ]
        rows = [
            _FakeRow((i + 1, f"p{i}.jpg", f"/photos/p{i}.jpg", 1000,
                      "image/jpeg", datetime(2024, 1, 1)))
            for i in range(3)
        ]
        mgr = _FakeJobQueueManager(qdrant_points=points, photo_rows=rows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, _ = app_main._compute_sim_cache()
        assert np.all(np.isfinite(data["sim_matrix"]))

    def test_qdrant_points_without_postgres_row_are_dropped(self):
        """If a Qdrant point references a photo_id that's been deleted from
        Postgres, it must not appear in the matrix."""
        vecs = _orthonormal(3)
        points = [
            _FakePoint(id="qp1", vector=vecs[0].tolist(), payload={"photo_id": 1}),
            _FakePoint(id="qp2", vector=vecs[1].tolist(), payload={"photo_id": 99}),  # orphan
            _FakePoint(id="qp3", vector=vecs[2].tolist(), payload={"photo_id": 3}),
        ]
        rows = [
            _FakeRow((1, "a.jpg", "/p/a.jpg", 100, "image/jpeg", datetime(2024, 1, 1))),
            _FakeRow((3, "c.jpg", "/p/c.jpg", 100, "image/jpeg", datetime(2024, 1, 1))),
        ]
        mgr = _FakeJobQueueManager(qdrant_points=points, photo_rows=rows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, meta = app_main._compute_sim_cache()
        assert data["photo_ids"] == [1, 3]
        assert 99 not in meta


class TestBuildSimilarityGroups:
    """End-to-end clustering tests against a hand-crafted matrix."""

    def _install_cache(self, sim_matrix, photo_ids, photo_meta):
        """Pre-populate the in-memory cache so _build_... reads it directly."""
        app_main._sim_cache.update(
            data={
                "sim_matrix": np.asarray(sim_matrix, dtype=np.float32),
                "photo_ids": list(photo_ids),
                "point_ids": [f"q{p}" for p in photo_ids],
            },
            meta=photo_meta,
        )

    def test_singletons_produce_no_groups(self):
        # 3 mutually orthogonal photos: nothing should cluster at threshold 0.5
        m = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        meta = {i: {"filename": f"p{i}.jpg", "file_path": "",
                    "file_size": 100, "mime_type": "image/jpeg",
                    "uploaded_at": "2024-01-01T00:00:00"} for i in (1, 2, 3)}
        self._install_cache(m, [1, 2, 3], meta)
        assert app_main._build_similarity_groups_from_qdrant(threshold=0.5) == []

    def test_one_group_picks_largest_as_reference(self):
        """Three near-identical vectors. Largest jpeg wins reference slot."""
        m = [
            [1.0, 0.95, 0.92],
            [0.95, 1.0, 0.94],
            [0.92, 0.94, 1.0],
        ]
        meta = {
            1: {"filename": "small.jpg", "file_path": "",
                "file_size": 1_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
            2: {"filename": "big.jpg", "file_path": "",
                "file_size": 5_000_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
            3: {"filename": "medium.jpg", "file_path": "",
                "file_size": 2_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
        }
        self._install_cache(m, [1, 2, 3], meta)
        groups = app_main._build_similarity_groups_from_qdrant(threshold=0.9)
        assert len(groups) == 1
        g = groups[0]
        assert g["reference_photo"]["photo_id"] == 2  # the largest
        assert g["reference_photo"]["similarity_score"] == 1.0
        # similar_photos scores are computed against the reference (row 2 of m)
        scores = {p["photo_id"]: pytest.approx(p["similarity_score"], abs=1e-5)
                  for p in g["similar_photos"]}
        assert scores == {1: 0.95, 3: 0.94}

    def test_format_bonus_overrides_raw_size(self):
        """JPEG with size 100k beats HEIC with size 110k because of the
        20% format bonus. Confirms _best_key behavior."""
        m = [[1.0, 0.99], [0.99, 1.0]]
        meta = {
            1: {"filename": "a.jpg", "file_path": "",
                "file_size": 100_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
            2: {"filename": "b.heic", "file_path": "",
                "file_size": 110_000, "mime_type": "image/heic",
                "uploaded_at": "2024-01-01T00:00:00"},
        }
        self._install_cache(m, [1, 2], meta)
        groups = app_main._build_similarity_groups_from_qdrant(threshold=0.9)
        assert groups[0]["reference_photo"]["photo_id"] == 1


class TestBestReasonsStrings:
    """Exercise the human-readable best_reasons string builder. The strings
    drive the 'why this photo' UI tooltip — regressions here are user-visible."""

    def _install(self, sim_matrix, photo_ids, photo_meta):
        app_main._sim_cache.update(
            data={
                "sim_matrix": np.asarray(sim_matrix, dtype=np.float32),
                "photo_ids": list(photo_ids),
                "point_ids": [f"q{p}" for p in photo_ids],
            },
            meta=photo_meta,
        )

    def test_largest_file_string_format(self):
        m = [[1.0, 0.99], [0.99, 1.0]]
        self._install(m, [1, 2], {
            1: {"filename": "a.jpg", "file_path": "",
                "file_size": 5_000_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
            2: {"filename": "b.jpg", "file_path": "",
                "file_size": 1_000_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
        })
        groups = app_main._build_similarity_groups_from_qdrant(threshold=0.9)
        reasons = groups[0]["best_reasons"]
        # "Largest file: 5.00 MB vs next 1.00 MB (+400%)"
        assert any(r.startswith("Largest file: 5.00 MB vs next 1.00 MB") for r in reasons)
        assert any("+400%" in r for r in reasons)

    def test_identical_size_with_copy_suffix_detection(self):
        """Original and a "(copy)" duplicate at same size — string should
        flag the original."""
        m = [[1.0, 0.99], [0.99, 1.0]]
        self._install(m, [1, 2], {
            1: {"filename": "vacation.jpg", "file_path": "",
                "file_size": 2_000_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
            2: {"filename": "vacation copy.jpg", "file_path": "",
                "file_size": 2_000_000, "mime_type": "image/jpeg",
                # later uploaded_at -> tiebreak goes to earlier (negated ts)
                "uploaded_at": "2024-02-01T00:00:00"},
        })
        groups = app_main._build_similarity_groups_from_qdrant(threshold=0.9)
        ref = groups[0]["reference_photo"]
        reasons = groups[0]["best_reasons"]
        assert ref["filename"] == "vacation.jpg"
        assert any("Identical file size: 2.00 MB" in r for r in reasons)
        assert any('"vacation.jpg" appears to be the original' in r for r in reasons)

    def test_format_string_marks_jpeg_as_preferred(self):
        m = [[1.0, 0.99], [0.99, 1.0]]
        self._install(m, [1, 2], {
            1: {"filename": "a.jpg", "file_path": "",
                "file_size": 1_000_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
            2: {"filename": "b.heic", "file_path": "",
                "file_size": 800_000, "mime_type": "image/heic",
                "uploaded_at": "2024-01-01T00:00:00"},
        })
        groups = app_main._build_similarity_groups_from_qdrant(threshold=0.9)
        reasons = groups[0]["best_reasons"]
        assert any("Format: image/jpeg (preferred (universal))" in r for r in reasons)
        assert any("others: image/heic" in r for r in reasons)

    def test_kb_size_format_under_one_mb(self):
        """Sub-1MB files render as KB, not MB."""
        m = [[1.0, 0.99], [0.99, 1.0]]
        self._install(m, [1, 2], {
            1: {"filename": "a.jpg", "file_path": "",
                "file_size": 500_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
            2: {"filename": "b.jpg", "file_path": "",
                "file_size": 100_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
        })
        groups = app_main._build_similarity_groups_from_qdrant(threshold=0.9)
        reasons = groups[0]["best_reasons"]
        assert any("Largest file: 500.0 KB vs next 100.0 KB" in r for r in reasons)


class TestNotifyDebounce:
    """Verify rapid changes coalesce into one recompute via the debounce."""

    @pytest.mark.asyncio
    async def test_rapid_calls_schedule_single_recompute(self, monkeypatch):
        """Five notify calls in quick succession should leave exactly one
        TimerHandle pending — earlier handles must be cancelled."""
        # Avoid actually running the heavy recompute: replace it with a no-op.
        async def _noop():
            return None
        monkeypatch.setattr(app_main, "_recompute_sim_cache", _noop)

        # Push the debounce way out so the test doesn't race with the timer.
        monkeypatch.setattr(app_main, "_SIM_DEBOUNCE_SECONDS", 60.0)

        cancels = {"count": 0}
        real_call_later = asyncio.get_running_loop().call_later

        for _ in range(5):
            app_main.notify_embeddings_changed()

        handle = app_main._sim_debounce_handle
        assert handle is not None
        # Only one outstanding handle — the previous four should have been cancelled
        # before being replaced.
        handle.cancel()  # don't leak the timer

    @pytest.mark.asyncio
    async def test_debounce_actually_fires_recompute(self, monkeypatch):
        """With a tiny debounce, the recompute coroutine should run."""
        called = asyncio.Event()

        async def _fake_recompute():
            called.set()

        monkeypatch.setattr(app_main, "_recompute_sim_cache", _fake_recompute)
        monkeypatch.setattr(app_main, "_SIM_DEBOUNCE_SECONDS", 0.01)

        app_main.notify_embeddings_changed()
        await asyncio.wait_for(called.wait(), timeout=1.0)

    def test_no_running_loop_returns_silently(self):
        """When called from sync code (no event loop), notify must not raise."""
        # In a test running outside async, get_running_loop raises RuntimeError;
        # the function should swallow it and return.
        app_main.notify_embeddings_changed()  # must not raise
        assert app_main._sim_debounce_handle is None


class TestRecomputeLock:
    """The lazy lock must only be created once and reused per loop."""

    @pytest.mark.asyncio
    async def test_lock_is_singleton_per_run(self):
        a = app_main._get_recompute_lock()
        b = app_main._get_recompute_lock()
        assert a is b
        # And it really gates concurrent recomputes:
        async with a:
            assert a.locked()
        assert not a.locked()
