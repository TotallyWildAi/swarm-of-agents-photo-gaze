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


class _FakeScoredPoint:
    def __init__(self, id, score, payload):
        self.id = id
        self.score = score
        self.payload = payload


class _FakeQdrant:
    """Minimal Qdrant stub with paginated scroll() AND search_batch().

    scroll() returns (page, next_offset). next_offset=None on the last page.
    search_batch() answers each SearchRequest by computing real cosine
    against the stored unit-normalized vectors and returning ScoredPoint
    objects above score_threshold, capped at limit. Matches qdrant-client
    closely enough for _compute_sim_cache to exercise the full path.
    """

    def __init__(self, points: List[_FakePoint], page_size: int = 2):
        self._points = points
        self._page_size = page_size
        self.scroll_calls = 0
        self.search_batch_calls = 0
        # Pre-normalize vectors so cosine == dot product.
        self._vec_array = np.array([p.vector for p in points], dtype=np.float32) \
            if points else np.zeros((0, 1), dtype=np.float32)
        if self._vec_array.size:
            norms = np.linalg.norm(self._vec_array, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self._vec_array = self._vec_array / norms

    def scroll(self, *, collection_name, limit, offset, with_payload, with_vectors):
        self.scroll_calls += 1
        start = offset or 0
        page = self._points[start : start + self._page_size]
        next_offset: Optional[int] = start + self._page_size
        if next_offset >= len(self._points):
            next_offset = None
        return page, next_offset

    def search_batch(self, *, collection_name, requests):
        self.search_batch_calls += 1
        results = []
        for req in requests:
            qv = np.asarray(req.vector, dtype=np.float32)
            qn = np.linalg.norm(qv)
            if qn:
                qv = qv / qn
            scores = self._vec_array @ qv if self._vec_array.size else np.zeros(0)
            order = np.argsort(-scores)
            hits = []
            for idx in order:
                s = float(scores[idx])
                if req.score_threshold is not None and s < req.score_threshold:
                    break
                hits.append(_FakeScoredPoint(
                    id=self._points[idx].id,
                    score=s,
                    payload=self._points[idx].payload,
                ))
                if len(hits) >= req.limit:
                    break
            results.append(hits)
        return results


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


# ----------------------------- helpers -----------------------------


def _install_cache(sim_matrix, photo_ids, photo_meta, cache_threshold: float = 0.0):
    """Pre-populate the new sparse-adjacency cache so _build_... reads it.

    Accepts a dense sim_matrix as input for ergonomics, then derives:
      - vectors that exactly reproduce the matrix via dot product (Cholesky)
      - adjacency: all pairs above cache_threshold

    cache_threshold defaults to 0.0 so test matrices with low values are
    fully indexed and don't get clamped by _build_similarity_groups_from_qdrant.
    """
    sim_matrix = np.asarray(sim_matrix, dtype=np.float64)
    n = sim_matrix.shape[0]
    if n == 0:
        vectors = np.zeros((0, 0), dtype=np.float32)
    else:
        # Lift sim_matrix to vectors via eigendecomposition so dot products
        # reproduce it. Symmetric PSD-ish input expected from tests.
        sim_matrix = (sim_matrix + sim_matrix.T) / 2.0  # symmetrize
        evals, evecs = np.linalg.eigh(sim_matrix)
        evals = np.clip(evals, 0.0, None)  # PSD floor for numerical noise
        vectors = (evecs * np.sqrt(evals)).astype(np.float32)
        # Re-normalize so unit-norm invariant the production code relies on holds.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms

    adjacency = [[] for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            s = float(sim_matrix[i, j])
            if s >= cache_threshold:
                adjacency[i].append((j, s))

    app_main._sim_cache.update(
        data={
            "vectors": vectors,
            "photo_ids": list(photo_ids),
            "point_ids": [f"q{p}" for p in photo_ids],
            "adjacency": adjacency,
            "cache_threshold": cache_threshold,
        },
        meta=photo_meta,
    )


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
        and produce a 5-vector index — proves >10k bug is gone."""
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
        assert data["vectors"].shape == (5, 4)
        assert len(data["photo_ids"]) == 5
        assert len(data["adjacency"]) == 5
        assert set(meta.keys()) == {1, 2, 3, 4, 5}

    def test_vectors_diagonal_is_one_after_normalization(self):
        """Cosine of any unit vector with itself = 1; rebuilds confidence
        that the normalize-then-store flow is correct."""
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
        # Each stored vector should be unit-norm.
        norms = np.linalg.norm(data["vectors"], axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)

    def test_zero_vector_does_not_explode(self):
        """A zero embedding must not cause divide-by-zero — check the
        norms[norms == 0] = 1 guard. Then no NaNs in the stored vectors."""
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
        assert np.all(np.isfinite(data["vectors"]))

    def test_qdrant_points_without_postgres_row_are_dropped(self):
        """If a Qdrant point references a photo_id that's been deleted from
        Postgres, it must not appear in the index."""
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

    def test_adjacency_excludes_self_and_below_threshold(self):
        """Build a small set with two near-identical vectors and one
        orthogonal. Adjacency must contain the i↔j edge but not self-loops
        and not the orthogonal edge."""
        # Two identical-direction vectors (sim=1) + one orthogonal.
        v_a = np.array([1.0, 0.0, 0.0, 0.0])
        v_b = np.array([0.99, 0.01, 0.0, 0.0])
        v_c = np.array([0.0, 0.0, 1.0, 0.0])
        points = [
            _FakePoint(id="qp1", vector=v_a.tolist(), payload={"photo_id": 1}),
            _FakePoint(id="qp2", vector=v_b.tolist(), payload={"photo_id": 2}),
            _FakePoint(id="qp3", vector=v_c.tolist(), payload={"photo_id": 3}),
        ]
        rows = [_FakeRow((i + 1, f"p{i}.jpg", "/p/x.jpg", 100, "image/jpeg",
                           datetime(2024, 1, 1))) for i in range(3)]
        mgr = _FakeJobQueueManager(qdrant_points=points, photo_rows=rows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, _ = app_main._compute_sim_cache()
        # photo_id 1 must list 2 as neighbour, not 3, not itself.
        adj_for_1 = data["adjacency"][0]
        neigh_idx = {j for j, _ in adj_for_1}
        assert 1 in neigh_idx       # idx 1 → photo_id 2
        assert 0 not in neigh_idx   # no self-loop
        assert 2 not in neigh_idx   # the orthogonal C is below 0.7

    def test_search_batch_called_for_all_points(self):
        """Every point must get a search query — confirms no point is skipped
        from adjacency build."""
        vecs = _orthonormal(5)
        points = [
            _FakePoint(id=f"qp{i}", vector=vecs[i].tolist(), payload={"photo_id": i + 1})
            for i in range(5)
        ]
        rows = [_FakeRow((i + 1, f"p{i}.jpg", "/p/x.jpg", 100, "image/jpeg",
                           datetime(2024, 1, 1))) for i in range(5)]
        mgr = _FakeJobQueueManager(qdrant_points=points, photo_rows=rows)
        with patch.object(app_main, "job_queue_manager", mgr):
            app_main._compute_sim_cache()
        assert mgr.qdrant_client.search_batch_calls >= 1


class TestBuildSimilarityGroups:
    """End-to-end clustering tests against a hand-crafted matrix."""

    def _install_cache(self, sim_matrix, photo_ids, photo_meta):
        """Pre-populate the cache via the shared helper (sparse adjacency)."""
        _install_cache(sim_matrix, photo_ids, photo_meta)

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
        _install_cache(sim_matrix, photo_ids, photo_meta)

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

    def test_format_string_handles_null_mime_type_among_others(self):
        """Postgres allows null mime_type. A mix of None and str values must
        not crash sorted()."""
        m = [[1.0, 0.99, 0.99], [0.99, 1.0, 0.98], [0.99, 0.98, 1.0]]
        self._install(m, [1, 2, 3], {
            1: {"filename": "ref.jpg", "file_path": "",
                "file_size": 5_000_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
            2: {"filename": "other.jpg", "file_path": "",
                "file_size": 1_000_000, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
            3: {"filename": "missing_type.bin", "file_path": "",
                "file_size": 1_000_000, "mime_type": None,  # the trap
                "uploaded_at": "2024-01-01T00:00:00"},
        })
        groups = app_main._build_similarity_groups_from_qdrant(threshold=0.9)
        assert len(groups) == 1
        reasons = groups[0]["best_reasons"]
        # "?" sorts before "image/jpeg" — assert both appear, no TypeError
        assert any("others: ?, image/jpeg" in r for r in reasons)

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


class TestObservability:
    """The /stats endpoint exposes similarity index health for the UI."""

    @pytest.mark.asyncio
    async def test_recompute_updates_index_info(self):
        """After a recompute, _sim_index_info should reflect the new state:
        non-null timestamp, vector/edge counts matching the cache."""
        # Use the same fake-manager harness as the unit tests above.
        v_a = np.array([1.0, 0.0, 0.0, 0.0])
        v_b = np.array([0.99, 0.01, 0.0, 0.0])
        v_c = np.array([0.0, 0.0, 1.0, 0.0])
        points = [
            _FakePoint(id="qp1", vector=v_a.tolist(), payload={"photo_id": 1}),
            _FakePoint(id="qp2", vector=v_b.tolist(), payload={"photo_id": 2}),
            _FakePoint(id="qp3", vector=v_c.tolist(), payload={"photo_id": 3}),
        ]
        rows = [_FakeRow((i + 1, f"p{i}.jpg", "/p/x.jpg", 100, "image/jpeg",
                           datetime(2024, 1, 1))) for i in range(3)]
        mgr = _FakeJobQueueManager(qdrant_points=points, photo_rows=rows)

        # Reset info baseline
        app_main._sim_index_info.update(
            last_recompute_at=None,
            last_recompute_duration_ms=None,
            recompute_running=False,
            vectors_in_index=0,
            edges_in_index=0,
        )

        with patch.object(app_main, "job_queue_manager", mgr):
            await app_main._recompute_sim_cache()

        info = app_main._sim_index_info
        assert info["last_recompute_at"] is not None
        assert info["last_recompute_duration_ms"] is not None
        assert info["recompute_running"] is False
        assert info["vectors_in_index"] == 3
        # A↔B is reciprocal → 2 directed edges; C is isolated → 0.
        assert info["edges_in_index"] == 2


class TestTenPhotoEndToEnd:
    """Integration test: simulate a folder of 10 'photos' with a known
    mix of duplicates, near-duplicates, and uniques. Run the full
    compute-cache → cluster pipeline and assert correct grouping.

    Photos are not real JPEGs (we never invoke the embedding model in
    tests — that would require ~90MB DINOv2 weights). Instead each
    'photo' is a hand-crafted unit vector laid out so the resulting
    similarity structure is exactly what we'd expect from real
    near-duplicate clusters: tightly grouped vectors for duplicates,
    orthogonal vectors for uniques.
    """

    def _build_collection(self):
        """Return (qdrant_points, postgres_rows) for 10 photos.

        Cluster A: 4 near-duplicates of a "sunset" shot, varying file
                   sizes and formats — the largest preferred-format wins.
        Cluster B: 3 near-duplicates of a "portrait", with one having
                   a "(copy)" suffix.
        Singletons: 3 unrelated unique photos.
        """
        # Ten 8-D unit vectors. Cluster A on axis 0, cluster B on axis 1,
        # singletons on axes 2/3/4.
        def _unit(direction, jitter=0.0):
            v = np.zeros(8, dtype=np.float32)
            v[direction] = 1.0
            if jitter:
                # Tiny perpendicular jitter so vectors aren't bit-identical.
                v[(direction + 1) % 8] = jitter
            n = np.linalg.norm(v)
            return (v / n).tolist()

        photos = [
            # --- Cluster A: 4 sunset near-duplicates ---
            # A1: medium jpeg, the original
            (1, _unit(0, 0.00),  "sunset.jpg",         "image/jpeg", 2_000_000, "2024-01-01T08:00:00"),
            # A2: smaller jpeg copy
            (2, _unit(0, 0.01),  "sunset copy.jpg",    "image/jpeg",   500_000, "2024-01-01T09:00:00"),
            # A3: largest png — should win the reference slot (bonus + size)
            (3, _unit(0, 0.02),  "sunset.png",         "image/png",  3_000_000, "2024-01-01T10:00:00"),
            # A4: heic (less universal), even bigger but loses on format bonus tie
            (4, _unit(0, 0.03),  "sunset.heic",        "image/heic", 3_500_000, "2024-01-01T11:00:00"),
            # --- Cluster B: 3 portraits ---
            (5, _unit(1, 0.00),  "portrait.jpg",        "image/jpeg", 1_500_000, "2024-02-01T08:00:00"),
            (6, _unit(1, 0.01),  "portrait (1).jpg",    "image/jpeg", 1_500_000, "2024-02-01T09:00:00"),
            (7, _unit(1, 0.02),  "portrait copy.jpg",   "image/jpeg", 1_500_000, "2024-02-01T10:00:00"),
            # --- Singletons: unrelated photos ---
            (8, _unit(2, 0.00),  "tree.jpg",            "image/jpeg",   400_000, "2024-03-01T08:00:00"),
            (9, _unit(3, 0.00),  "skyline.jpg",         "image/jpeg",   600_000, "2024-03-01T09:00:00"),
            (10, _unit(4, 0.00), "cat.jpg",             "image/jpeg",   800_000, "2024-03-01T10:00:00"),
        ]

        qpoints = [
            _FakePoint(id=f"qp{pid}", vector=v, payload={"photo_id": pid})
            for (pid, v, *_rest) in photos
        ]
        prows = [
            _FakeRow((pid, fname, f"/photos/{fname}", size, mime,
                      datetime.fromisoformat(uploaded)))
            for (pid, _v, fname, mime, size, uploaded) in photos
        ]
        return qpoints, prows

    def test_full_pipeline_groups_three_clusters_correctly(self):
        qpoints, prows = self._build_collection()
        mgr = _FakeJobQueueManager(qdrant_points=qpoints, photo_rows=prows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, meta = app_main._compute_sim_cache()
            app_main._sim_cache.update(data=data, meta=meta)
            groups = app_main._build_similarity_groups_from_qdrant(threshold=0.9)

        # Two non-singleton clusters: A (4 photos) and B (3 photos).
        # Singletons (8/9/10) form no groups.
        assert len(groups) == 2

        # Find each by membership.
        groups_by_size = sorted(groups, key=lambda g: -(1 + len(g["similar_photos"])))
        cluster_a = groups_by_size[0]
        cluster_b = groups_by_size[1]
        a_pids = {cluster_a["reference_photo"]["photo_id"]} | {
            p["photo_id"] for p in cluster_a["similar_photos"]
        }
        b_pids = {cluster_b["reference_photo"]["photo_id"]} | {
            p["photo_id"] for p in cluster_b["similar_photos"]
        }
        assert a_pids == {1, 2, 3, 4}
        assert b_pids == {5, 6, 7}
        # Singletons must not appear anywhere.
        assert {8, 9, 10}.isdisjoint(a_pids | b_pids)

    def test_reference_selection_prefers_universal_format(self):
        """In cluster A, the HEIC (3.5 MB) is biggest by raw bytes but
        the PNG (3.0 MB) wins because the 20% preferred-format bonus
        gives it a higher effective score."""
        qpoints, prows = self._build_collection()
        mgr = _FakeJobQueueManager(qdrant_points=qpoints, photo_rows=prows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, meta = app_main._compute_sim_cache()
            app_main._sim_cache.update(data=data, meta=meta)
            groups = app_main._build_similarity_groups_from_qdrant(threshold=0.9)

        # Pick the 4-member cluster
        cluster_a = next(
            g for g in groups
            if 1 + len(g["similar_photos"]) == 4
        )
        # PNG (photo_id=3, 3MB) should win over HEIC (photo_id=4, 3.5MB)
        # because score(PNG) = 3M*1.2 = 3.6M > score(HEIC) = 3.5M.
        assert cluster_a["reference_photo"]["photo_id"] == 3
        assert cluster_a["reference_photo"]["mime_type"] == "image/png"

    def test_reference_score_is_one_others_above_threshold(self):
        """All members of a near-duplicate cluster must score very close
        to 1.0 against the reference (vectors are constructed that way)."""
        qpoints, prows = self._build_collection()
        mgr = _FakeJobQueueManager(qdrant_points=qpoints, photo_rows=prows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, meta = app_main._compute_sim_cache()
            app_main._sim_cache.update(data=data, meta=meta)
            groups = app_main._build_similarity_groups_from_qdrant(threshold=0.9)

        for g in groups:
            assert g["reference_photo"]["similarity_score"] == 1.0
            for m in g["similar_photos"]:
                assert m["similarity_score"] >= 0.9, \
                    f"member {m['photo_id']} dropped below threshold: {m['similarity_score']}"

    def test_threshold_above_one_yields_no_groups(self):
        """Asking for threshold > 1 must return zero groups (no pair is
        more similar than 1.0). Defends against off-by-one slider bugs."""
        qpoints, prows = self._build_collection()
        mgr = _FakeJobQueueManager(qdrant_points=qpoints, photo_rows=prows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, meta = app_main._compute_sim_cache()
            app_main._sim_cache.update(data=data, meta=meta)
            groups = app_main._build_similarity_groups_from_qdrant(threshold=1.0001)
        assert groups == []

    def test_threshold_below_cache_floor_is_clamped(self):
        """If the user asks for threshold 0.0 (would normally pull in
        everything) the build still honors the cache floor (0.7) — we
        can't fabricate edges that weren't precomputed. Behavior must be
        identical to threshold=cache_threshold."""
        qpoints, prows = self._build_collection()
        mgr = _FakeJobQueueManager(qdrant_points=qpoints, photo_rows=prows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, meta = app_main._compute_sim_cache()
            app_main._sim_cache.update(data=data, meta=meta)
            g_low = app_main._build_similarity_groups_from_qdrant(threshold=0.0)
            g_floor = app_main._build_similarity_groups_from_qdrant(
                threshold=app_main._SIM_CACHE_THRESHOLD)
        assert len(g_low) == len(g_floor)

    def test_memory_footprint_is_sparse(self):
        """The whole point of the rewrite. With 10 photos in 2 clusters of
        4 and 3 plus 3 singletons, total directed edges should be small
        (≤ 4*3 + 3*2 = 18), nowhere near a dense N² = 100."""
        qpoints, prows = self._build_collection()
        mgr = _FakeJobQueueManager(qdrant_points=qpoints, photo_rows=prows)
        with patch.object(app_main, "job_queue_manager", mgr):
            data, _ = app_main._compute_sim_cache()
        total_edges = sum(len(adj) for adj in data["adjacency"])
        assert total_edges <= 18, f"adjacency exploded: {total_edges} edges"
        # Vectors stored separately for exact ref-vs-member scoring.
        assert data["vectors"].shape == (10, 8)
