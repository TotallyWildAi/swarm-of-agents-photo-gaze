"""Thorough tests for the auto-deduplicate sweep.

Covers the planner (_plan_auto_dedupe) under every interesting cluster
shape:
  - all members in keep folder      → keep best, delete rest within
  - some members in keep folder     → keep best from that subset, delete
                                       outsiders + extra in-folder copies
  - no members in keep folder       → cluster skipped (no destructive
                                       choice without an explicit anchor)
  - prefix collision                → /a/bc must NOT match folder /a/b
  - symlink keep folder             → resolved via realpath, members
                                       reachable through either form
  - threshold 1.0 vs 0.95           → wider threshold pulls more clusters
                                       in
  - empty registry                  → 0 work, no errors

And the endpoint:
  - dry_run returns plan, touches nothing
  - missing/invalid folder_path → 400
  - folder inside TRASH_DIR     → 400
  - threshold out of range      → 400
"""
import os
import tempfile
import shutil
from datetime import datetime
from unittest.mock import patch, MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.main as app_main


# --------------------- shared cache helper ---------------------


def _install_cache(sim_matrix, photo_ids, photo_meta, cache_threshold: float = 0.7):
    """Same approach as tests/test_similarity_matrix.py: lift a dense
    similarity matrix to vectors via eigendecomposition so the
    auto-dedupe planner reads consistent data through the production
    code path."""
    sim_matrix = np.asarray(sim_matrix, dtype=np.float64)
    n = sim_matrix.shape[0]
    if n == 0:
        vectors = np.zeros((0, 0), dtype=np.float32)
    else:
        sim_matrix = (sim_matrix + sim_matrix.T) / 2.0
        evals, evecs = np.linalg.eigh(sim_matrix)
        evals = np.clip(evals, 0.0, None)
        vectors = (evecs * np.sqrt(evals)).astype(np.float32)
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


@pytest.fixture(autouse=True)
def _reset_cache():
    app_main._sim_cache.update(data=None, meta=None)
    yield
    app_main._sim_cache.update(data=None, meta=None)


def _meta(file_path, file_size=1_000_000, mime="image/jpeg",
          uploaded="2024-01-01T00:00:00", filename=None):
    return {
        "filename": filename or os.path.basename(file_path),
        "file_path": file_path,
        "file_size": file_size,
        "mime_type": mime,
        "uploaded_at": uploaded,
    }


# --------------------- planner tests ---------------------


class TestPlanner:
    def test_no_members_in_keep_folder_skips_group(self):
        """A pure-duplicate cluster with no anchor in the keep folder
        must NOT be acted on — we never make a destructive choice
        without an explicit user-chosen home for the survivor."""
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/A/x.jpg"),
            2: _meta("/photos/B/x.jpg"),
        })
        plan = app_main._plan_auto_dedupe(threshold=1.0, keep_folder="/photos/keep")
        assert plan["groups_processed"] == 0
        assert plan["groups_skipped"] == 1
        assert plan["to_delete"] == []
        assert plan["kept"] == []

    def test_one_member_in_keep_folder_deletes_others(self):
        """Cluster spans two folders; only one photo is in the keep
        folder. That one survives; the outsider is deleted."""
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/keep/x.jpg"),
            2: _meta("/photos/elsewhere/x.jpg"),
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert plan["kept"] == [1]
        assert plan["to_delete"] == [2]
        assert plan["groups_processed"] == 1
        assert plan["groups_skipped"] == 0

    def test_multiple_in_keep_folder_keeps_best_and_deletes_in_folder_extras(self):
        """Three duplicates, two in keep folder + one outside. The best
        of the two in-folder copies is the keeper; both the in-folder
        runner-up AND the outsider are deleted."""
        m = [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]
        _install_cache(m, [1, 2, 3], {
            # in keep folder, smaller — runner-up
            1: _meta("/photos/keep/small.jpg", file_size=1_000_000),
            # in keep folder, biggest — keeper
            2: _meta("/photos/keep/big.jpg", file_size=5_000_000),
            # outside keep folder, also big
            3: _meta("/photos/elsewhere/big.jpg", file_size=5_000_000),
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert plan["kept"] == [2]
        assert sorted(plan["to_delete"]) == [1, 3]

    def test_all_members_in_keep_folder(self):
        """Three duplicates all inside the keep folder — keep the best,
        delete the other two."""
        m = [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]
        _install_cache(m, [1, 2, 3], {
            1: _meta("/photos/keep/a.jpg", file_size=1_000),
            2: _meta("/photos/keep/b.jpg", file_size=10_000_000),  # biggest
            3: _meta("/photos/keep/c.jpg", file_size=5_000),
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert plan["kept"] == [2]
        assert sorted(plan["to_delete"]) == [1, 3]

    def test_prefix_collision_does_not_match(self):
        """A photo at /a/bc/x.jpg is NOT inside folder /a/b — verifies
        the trailing-separator guard."""
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/keepers/x.jpg"),       # not in /photos/keep
            2: _meta("/photos/elsewhere/x.jpg"),     # also not in /photos/keep
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        # No anchor → group skipped, nothing deleted.
        assert plan["to_delete"] == []
        assert plan["groups_skipped"] == 1

    def test_keep_folder_resolved_via_symlink(self, tmp_path):
        """A symlink keep folder must map to the same membership as the
        real path (realpath() is applied to both sides)."""
        real = tmp_path / "real_keep"
        real.mkdir()
        link = tmp_path / "link_keep"
        link.symlink_to(real)
        photo_path = str(real / "x.jpg")
        (real / "x.jpg").write_bytes(b"x")  # exists for realpath
        # Cluster: this photo + an outsider
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta(photo_path),
            2: _meta("/photos/elsewhere/x.jpg"),
        })
        plan = app_main._plan_auto_dedupe(1.0, str(link))
        assert plan["kept"] == [1]
        assert plan["to_delete"] == [2]

    def test_singleton_groups_ignored(self):
        """A "group" with just one photo (e.g. its only neighbour was
        already pulled into another cluster) must not cause a delete."""
        # Diagonal-only matrix: nothing clusters; planner sees no groups.
        m = [[1.0, 0.0], [0.0, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/keep/a.jpg"),
            2: _meta("/photos/keep/b.jpg"),
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert plan["to_delete"] == []
        assert plan["groups_processed"] == 0

    def test_threshold_one_excludes_near_duplicates_below_one(self):
        """At threshold=1.0, a cluster with sim 0.9 must NOT be touched.
        Pure-only mode is the user's request when they slide to 1.0."""
        m = [[1.0, 0.9], [0.9, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/keep/a.jpg"),
            2: _meta("/photos/elsewhere/a.jpg"),
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert plan["to_delete"] == []

    def test_threshold_below_one_picks_up_near_duplicates(self):
        """Same data as above but at 0.85 — the cluster IS acted on."""
        m = [[1.0, 0.9], [0.9, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/keep/a.jpg"),
            2: _meta("/photos/elsewhere/a.jpg"),
        })
        plan = app_main._plan_auto_dedupe(0.85, "/photos/keep")
        assert plan["kept"] == [1]
        assert plan["to_delete"] == [2]

    def test_empty_index_is_a_clean_noop(self):
        """No vectors in cache → no work, no error."""
        plan = app_main._plan_auto_dedupe(1.0, "/anywhere")
        assert plan == {
            "groups_processed": 0,
            "groups_skipped": 0,
            "to_delete": [],
            "kept": [],
            "groups": [],
        }

    def test_member_with_missing_file_path_is_treated_as_outside(self):
        """If a member has no file_path (data corruption or partial
        ingestion), it counts as outside the keep folder — never the
        keeper, eligible for deletion if another anchor exists."""
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/keep/x.jpg"),
            2: {"filename": "ghost.jpg", "file_path": None,
                "file_size": 100, "mime_type": "image/jpeg",
                "uploaded_at": "2024-01-01T00:00:00"},
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert plan["kept"] == [1]
        assert plan["to_delete"] == [2]

    def test_pure_duplicates_with_float32_noise_still_clustered(self):
        """REGRESSION: in production, two identical photos give vectors
        whose cosine is 1.0 in theory but ~0.9999998 in float32 after
        normalize-then-dot. A user setting the slider to 1.0 expects
        "pure duplicates" to be acted on — they MUST NOT be silently
        excluded by float-precision noise.

        We pin this by installing an adjacency entry just below 1.0
        and asserting threshold=1.0 still pulls it in.
        """
        import numpy as np
        # Two unit vectors. Doesn't matter for the planner — adjacency
        # carries the score it filters on.
        vectors = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
        app_main._sim_cache.update(
            data={
                "vectors": vectors,
                "photo_ids": [1, 2],
                "point_ids": ["q1", "q2"],
                # Score 0.9999998 — exactly the float32 noise floor that
                # production sees for "should-be-1.0" pairs.
                "adjacency": [[(1, 0.9999998)], [(0, 0.9999998)]],
                "cache_threshold": 0.7,
            },
            meta={
                1: _meta("/photos/keep/x.jpg"),
                2: _meta("/photos/elsewhere/x.jpg"),
            },
        )
        plan = app_main._plan_auto_dedupe(threshold=1.0,
                                          keep_folder="/photos/keep")
        assert plan["kept"] == [1], (
            "pure duplicates lost to float32 noise at threshold=1.0"
        )
        assert plan["to_delete"] == [2]

    def test_keeper_chosen_by_best_key_format_bonus(self):
        """Two duplicates inside keep folder: smaller JPEG vs larger HEIC.
        JPEG wins on the format bonus (size * 1.2 vs size * 1.0). Here
        size_jpeg * 1.2 = 1.2M > size_heic * 1.0 = 1.1M."""
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/keep/a.jpg",  file_size=1_000_000, mime="image/jpeg"),
            2: _meta("/photos/keep/b.heic", file_size=1_100_000, mime="image/heic"),
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert plan["kept"] == [1]
        assert plan["to_delete"] == [2]


# --------------------- endpoint tests ---------------------


class TestEndpoint:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        # Stub job_queue_manager so the 503 short-circuit doesn't fire.
        # We DON'T exercise the execute path here (covered separately by
        # an integration test below); these tests validate the input
        # handling and dry-run output.
        class _Stub:
            def SessionLocal(self):
                return MagicMock()
        monkeypatch.setattr(app_main, "job_queue_manager", _Stub())
        # Isolate the trash dir so the trash-prefix guard tests work.
        monkeypatch.setattr(app_main, "TRASH_DIR", str(tmp_path / "trash"))
        return TestClient(app_main.app)

    def test_missing_folder_path_returns_400(self, client):
        r = client.post("/auto-deduplicate", json={})
        assert r.status_code == 400
        assert "folder_path" in r.json()["error"]

    def test_nonexistent_folder_returns_400(self, client):
        r = client.post("/auto-deduplicate",
                        json={"folder_path": "/this/does/not/exist"})
        assert r.status_code == 400

    def test_folder_inside_trash_dir_rejected(self, client, tmp_path):
        trash = tmp_path / "trash"
        sub = trash / "sub"
        sub.mkdir(parents=True)
        r = client.post("/auto-deduplicate",
                        json={"folder_path": str(sub)})
        assert r.status_code == 400
        assert "trash" in r.json()["error"].lower()

    def test_threshold_out_of_range_rejected(self, client, tmp_path):
        d = tmp_path / "ok"
        d.mkdir()
        for bad in (0.0, -0.1, 1.5):
            r = client.post("/auto-deduplicate",
                            json={"folder_path": str(d), "threshold": bad})
            assert r.status_code == 400, f"threshold={bad}"

    def test_dry_run_returns_plan_and_touches_nothing(self, client, tmp_path,
                                                      monkeypatch):
        """dry_run=true must NOT call _execute_dedupe even when the plan
        contains photos to delete. We assert by patching the executor
        and confirming it's untouched."""
        keep = tmp_path / "keep"
        keep.mkdir()
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [10, 20], {
            10: _meta(str(keep / "a.jpg")),
            20: _meta("/elsewhere/a.jpg"),
        })

        called = {"n": 0}
        async def _fail_if_called(*a, **kw):
            called["n"] += 1
            return {}
        monkeypatch.setattr(app_main, "_execute_dedupe", _fail_if_called)

        r = client.post("/auto-deduplicate", json={
            "folder_path": str(keep),
            "threshold": 1.0,
            "dry_run": True,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["dry_run"] is True
        assert body["kept"] == [10]
        assert body["to_delete"] == [20]
        assert body["groups_processed"] == 1
        assert called["n"] == 0  # executor not called

    def test_execute_with_empty_plan_still_returns_executed_response_shape(
        self, client, tmp_path,
    ):
        """REGRESSION: when dry_run=False but the plan happens to be empty
        (no clusters anchor in keep_folder, or threshold is too tight for
        anything), the response must STILL include `deleted` and
        `moved_to_trash` keys. The frontend's "done" view reads
        result.deleted; rendering an undefined here was a UI footgun."""
        keep = tmp_path / "keep"
        keep.mkdir()
        # No cluster anchored in keep — everything's elsewhere
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/elsewhere/a.jpg"),
            2: _meta("/photos/other/a.jpg"),
        })
        r = client.post("/auto-deduplicate", json={
            "folder_path": str(keep),
            "threshold": 1.0,
            "dry_run": False,
        })
        body = r.json()
        assert body["dry_run"] is False
        assert "deleted" in body and body["deleted"] == 0
        assert "moved_to_trash" in body and body["moved_to_trash"] == 0
        assert body["kept"] == []

    def test_no_clusters_to_act_on_returns_zero_counts(self, client, tmp_path):
        """If the planner finds nothing (e.g. nothing clusters at the
        given threshold), the endpoint succeeds with an empty plan and
        no execute call. We pre-install a cache where nothing pairs up."""
        keep = tmp_path / "keep"
        keep.mkdir()
        m = [[1.0, 0.0], [0.0, 1.0]]  # two unrelated photos
        _install_cache(m, [1, 2], {
            1: _meta(str(keep / "a.jpg")),
            2: _meta(str(keep / "b.jpg")),
        })
        r = client.post("/auto-deduplicate", json={
            "folder_path": str(keep),
            "threshold": 1.0,
        })
        body = r.json()
        assert body["to_delete"] == []
        assert body["groups_processed"] == 0


class TestAdditionalAuditCases:
    """Audit-driven coverage for behaviors that surfaced during the
    pure-duplicate / response-shape investigation."""

    def test_threshold_just_above_pure_dupe_floor_acts(self):
        """A pair scoring 0.9999 must cluster at threshold=1.0 (the
        relaxation accepts up to _PURE_DUPE_EPSILON below 1.0). Any
        narrower margin is impossible to distinguish from float noise."""
        import numpy as np
        app_main._sim_cache.update(
            data={
                "vectors": np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32),
                "photo_ids": [1, 2],
                "point_ids": ["q1", "q2"],
                "adjacency": [[(1, 0.9999)], [(0, 0.9999)]],
                "cache_threshold": 0.7,
            },
            meta={
                1: _meta("/photos/keep/a.jpg"),
                2: _meta("/photos/elsewhere/a.jpg"),
            },
        )
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert plan["kept"] == [1]

    def test_threshold_at_pure_dupe_floor_minus_more_does_not_act(self):
        """A pair scoring 0.998 (well below noise) at threshold=1.0
        is NOT considered a pure duplicate. Confirms the relaxation
        is bounded by _PURE_DUPE_EPSILON, not arbitrary."""
        import numpy as np
        app_main._sim_cache.update(
            data={
                "vectors": np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32),
                "photo_ids": [1, 2],
                "point_ids": ["q1", "q2"],
                "adjacency": [[(1, 0.998)], [(0, 0.998)]],
                "cache_threshold": 0.7,
            },
            meta={
                1: _meta("/photos/keep/a.jpg"),
                2: _meta("/photos/elsewhere/a.jpg"),
            },
        )
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert plan["to_delete"] == []
        assert plan["groups_processed"] == 0

    def test_threshold_above_one_returns_empty(self):
        """User input >1.0 (out of range) yields no clusters. Defends
        against off-by-one slider bugs even with the float relaxation."""
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/keep/a.jpg"),
            2: _meta("/photos/elsewhere/a.jpg"),
        })
        plan = app_main._plan_auto_dedupe(1.0001, "/photos/keep")
        assert plan["to_delete"] == []
        assert plan["groups_processed"] == 0

    def test_planner_return_shape_is_stable_when_no_clusters(self):
        """Empty cache must produce a fixed shape — frontend code
        accesses every field unconditionally."""
        plan = app_main._plan_auto_dedupe(1.0, "/anywhere")
        assert set(plan.keys()) == {
            "groups_processed", "groups_skipped",
            "to_delete", "kept", "groups",
        }
        assert plan["groups"] == []

    def test_keep_path_with_trailing_separator_matches(self):
        """A user passing "/photos/keep/" (with trailing /) must match
        the same photos as "/photos/keep" — they're the same folder."""
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [1, 2], {
            1: _meta("/photos/keep/a.jpg"),
            2: _meta("/photos/elsewhere/a.jpg"),
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep/")
        assert plan["kept"] == [1]
        assert plan["to_delete"] == [2]

    def test_to_delete_has_no_duplicates_across_groups(self):
        """A photo can belong to at most one cluster (greedy clustering
        marks visited). Confirm the plan never schedules the same id
        for deletion twice."""
        # 3-clique among photos 1,2,3 + isolated cluster 4 only similar to 5.
        m = [
            [1.0, 1.0, 1.0, 0.0, 0.0],
            [1.0, 1.0, 1.0, 0.0, 0.0],
            [1.0, 1.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0, 1.0],
            [0.0, 0.0, 0.0, 1.0, 1.0],
        ]
        _install_cache(m, [1, 2, 3, 4, 5], {
            1: _meta("/photos/keep/a.jpg", file_size=10_000_000),
            2: _meta("/photos/keep/b.jpg", file_size=1_000_000),
            3: _meta("/photos/elsewhere/c.jpg", file_size=1_000_000),
            4: _meta("/photos/keep/d.jpg"),
            5: _meta("/photos/elsewhere/e.jpg"),
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert sorted(plan["to_delete"]) == sorted(set(plan["to_delete"])), \
            "duplicate ids in to_delete"

    def test_keeper_and_deletes_are_disjoint(self):
        """No id should appear in both kept and to_delete."""
        m = [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]
        _install_cache(m, [1, 2, 3], {
            1: _meta("/photos/keep/a.jpg", file_size=5_000_000),
            2: _meta("/photos/keep/b.jpg", file_size=1_000_000),
            3: _meta("/photos/elsewhere/c.jpg", file_size=1_000_000),
        })
        plan = app_main._plan_auto_dedupe(1.0, "/photos/keep")
        assert set(plan["kept"]).isdisjoint(set(plan["to_delete"]))


class TestEndToEndCleanup:
    """Integration test that goes through _execute_dedupe with a real
    SQLite DB and a recording Qdrant stub. Asserts the contract from
    the user:

        "When photos are deleted - their data and embeddings are also
         deleted from the database etc."

    Specifically: after a non-dry-run sweep, the deleted photo's
    Photo / Embedding / ProcessingState rows are gone from Postgres
    AND its Qdrant point ID was passed to qdrant_client.delete().
    The keeper photo's rows must remain intact.
    """

    def test_auto_dedupe_purges_db_and_qdrant_for_deleted_photos(
        self, monkeypatch, tmp_path,
    ):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import Base, Photo, Embedding, ProcessingState

        # File-backed SQLite — :memory: is per-connection, so the
        # endpoint's SessionLocal() call would land in a different DB.
        db_path = tmp_path / "test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        keep_dir = tmp_path / "keep"
        keep_dir.mkdir()
        outside_dir = tmp_path / "elsewhere"
        outside_dir.mkdir()
        keeper_path = keep_dir / "x.jpg"
        outsider_path = outside_dir / "x.jpg"
        keeper_path.write_bytes(b"keeper-bytes")
        outsider_path.write_bytes(b"outsider-bytes")

        # photo_id -> (Photo, Embedding(point_id), ProcessingState)
        keeper = Photo(filename="x.jpg", file_path=str(keeper_path),
                       file_size=os.path.getsize(keeper_path),
                       mime_type="image/jpeg", uploaded_at=datetime(2024, 1, 1))
        outsider = Photo(filename="x.jpg", file_path=str(outsider_path),
                          file_size=os.path.getsize(outsider_path),
                          mime_type="image/jpeg", uploaded_at=datetime(2024, 1, 1))
        session.add_all([keeper, outsider])
        session.commit()
        session.add_all([
            Embedding(photo_id=keeper.id, embedding_model="x",
                       vector_dimension=4, qdrant_point_id="qkeep"),
            Embedding(photo_id=outsider.id, embedding_model="x",
                       vector_dimension=4, qdrant_point_id="qout"),
            ProcessingState(photo_id=keeper.id,
                             status="completed",
                             extraction_status="completed",
                             embedding_status="completed"),
            ProcessingState(photo_id=outsider.id,
                             status="completed",
                             extraction_status="completed",
                             embedding_status="completed"),
        ])
        session.commit()
        keeper_id, outsider_id = keeper.id, outsider.id
        session.close()

        # Pre-install the similarity cache: pure duplicates.
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [keeper_id, outsider_id], {
            keeper_id: _meta(str(keeper_path)),
            outsider_id: _meta(str(outsider_path)),
        })

        # Wire job_queue_manager + a recording Qdrant stub.
        deleted_qdrant_points = []

        class _RecordingQdrant:
            def delete(self, *, collection_name, points_selector):
                deleted_qdrant_points.extend(list(points_selector))
            # search_batch / scroll won't be called: cache is pre-installed
            # and the index recompute below is stubbed out.

        class _Mgr:
            qdrant_client = _RecordingQdrant()
            def SessionLocal(self):
                return SessionLocal()

        monkeypatch.setattr(app_main, "job_queue_manager", _Mgr())
        monkeypatch.setattr(app_main, "TRASH_DIR", str(tmp_path / "trash"))

        # Stub the index recompute (it would otherwise re-scroll Qdrant).
        async def _noop_recompute():
            return None
        monkeypatch.setattr(app_main, "_recompute_sim_cache", _noop_recompute)

        client = TestClient(app_main.app)
        r = client.post("/auto-deduplicate", json={
            "folder_path": str(keep_dir),
            "threshold": 1.0,
            "dry_run": False,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kept"] == [keeper_id]
        assert body["deleted"] == 1
        assert body["moved_to_trash"] == 1

        # Postgres: keeper's rows still present, outsider's rows gone.
        verify = SessionLocal()
        try:
            assert verify.query(Photo).filter(Photo.id == keeper_id).count() == 1
            assert verify.query(Photo).filter(Photo.id == outsider_id).count() == 0
            assert verify.query(Embedding).filter(
                Embedding.photo_id == outsider_id).count() == 0
            assert verify.query(ProcessingState).filter(
                ProcessingState.photo_id == outsider_id).count() == 0
            # Keeper embedding/state untouched
            assert verify.query(Embedding).filter(
                Embedding.photo_id == keeper_id).count() == 1
            assert verify.query(ProcessingState).filter(
                ProcessingState.photo_id == keeper_id).count() == 1
        finally:
            verify.close()

        # Qdrant: the outsider's point id was passed to delete; the
        # keeper's point id must NOT have been.
        assert "qout" in deleted_qdrant_points
        assert "qkeep" not in deleted_qdrant_points

        # Filesystem: outsider's file moved to trash, keeper's file untouched.
        assert keeper_path.is_file()
        assert keeper_path.read_bytes() == b"keeper-bytes"
        assert not outsider_path.exists()
        # The trash dir now contains a manifest + the moved file
        trash_dir = tmp_path / "trash"
        assert trash_dir.is_dir()
        files = list(trash_dir.iterdir())
        assert any(f.name.endswith("_manifest.json") for f in files)
        assert any(f.read_bytes() == b"outsider-bytes"
                   for f in files if not f.name.endswith(".json"))


class TestExecutionWiring:
    """One end-to-end check that a non-dry-run call actually invokes
    _execute_dedupe with the planned photo IDs."""

    def test_execute_path_passes_to_delete_to_executor(self, monkeypatch, tmp_path):
        keep = tmp_path / "keep"
        keep.mkdir()
        m = [[1.0, 1.0], [1.0, 1.0]]
        _install_cache(m, [42, 99], {
            42: _meta(str(keep / "a.jpg")),
            99: _meta("/elsewhere/a.jpg"),
        })

        captured = {}
        async def _fake_execute(session, photo_ids):
            captured["photo_ids"] = list(photo_ids)
            return {"deleted": len(photo_ids), "moved_to_trash": len(photo_ids),
                    "trash_dir": "/trash", "errors": None}
        monkeypatch.setattr(app_main, "_execute_dedupe", _fake_execute)

        class _Stub:
            def SessionLocal(self):
                return MagicMock()
        monkeypatch.setattr(app_main, "job_queue_manager", _Stub())

        client = TestClient(app_main.app)
        r = client.post("/auto-deduplicate", json={
            "folder_path": str(keep),
            "threshold": 1.0,
            "dry_run": False,
        })
        assert r.status_code == 200
        body = r.json()
        assert captured["photo_ids"] == [99]
        assert body["deleted"] == 1
        assert body["kept"] == [42]
