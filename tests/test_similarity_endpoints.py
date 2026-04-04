"""Tests for similarity group API endpoints."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app, similarity_group_service, thumbnail_generator


SAMPLE_GROUPS = [
    {
        "group_id": "g1",
        "similarity_score": 0.95,
        "quality_score": 0.8,
        "members": [
            {"photo_id": 1, "file_path": "/photos/a.jpg", "file_hash": "aaa", "filename": "a.jpg"},
            {"photo_id": 2, "file_path": "/photos/b.jpg", "file_hash": "bbb", "filename": "b.jpg"},
        ],
    },
    {
        "group_id": "g2",
        "similarity_score": 0.7,
        "quality_score": 0.9,
        "members": [
            {"photo_id": 3, "file_path": "/photos/c.jpg", "file_hash": "ccc", "filename": "c.jpg"},
        ],
    },
    {
        "group_id": "g3",
        "similarity_score": 0.5,
        "quality_score": 0.6,
        "members": [],
    },
]


@pytest.fixture(autouse=True)
def setup_groups():
    """Populate and then clean up the global similarity_group_service for each test."""
    similarity_group_service.clear()
    for g in SAMPLE_GROUPS:
        similarity_group_service.add_group(g)
    yield
    similarity_group_service.clear()


@pytest.fixture
def client():
    return TestClient(app)


class TestListSimilarityGroups:
    """Tests for GET /similarity-groups endpoint."""

    def test_list_returns_all_groups(self, client):
        response = client.get("/similarity-groups")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["groups"]) == 3

    def test_pagination_skip(self, client):
        response = client.get("/similarity-groups?skip=1&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["skip"] == 1
        assert len(data["groups"]) == 2

    def test_pagination_limit(self, client):
        response = client.get("/similarity-groups?skip=0&limit=1")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["limit"] == 1
        assert len(data["groups"]) == 1

    def test_filter_min_similarity(self, client):
        response = client.get("/similarity-groups?min_similarity=0.8")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["groups"][0]["group_id"] == "g1"

    def test_filter_min_quality(self, client):
        response = client.get("/similarity-groups?min_quality=0.85")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["groups"][0]["group_id"] == "g2"

    def test_filter_combined(self, client):
        """Both filters applied together."""
        response = client.get("/similarity-groups?min_similarity=0.6&min_quality=0.7")
        assert response.status_code == 200
        data = response.json()
        # g1 (sim=0.95, qual=0.8) and g2 (sim=0.7, qual=0.9) pass; g3 fails both
        assert data["total"] == 2

    def test_sort_by_similarity(self, client):
        response = client.get("/similarity-groups?sort_by=similarity")
        assert response.status_code == 200
        groups = response.json()["groups"]
        scores = [g["similarity_score"] for g in groups]
        assert scores == sorted(scores, reverse=True)

    def test_sort_by_quality(self, client):
        response = client.get("/similarity-groups?sort_by=quality")
        assert response.status_code == 200
        groups = response.json()["groups"]
        scores = [g["quality_score"] for g in groups]
        assert scores == sorted(scores, reverse=True)

    def test_invalid_sort_by_returns_400(self, client):
        response = client.get("/similarity-groups?sort_by=invalid")
        assert response.status_code == 400
        assert "Invalid sort_by" in response.json()["detail"]

    def test_empty_result_with_high_filter(self, client):
        response = client.get("/similarity-groups?min_similarity=0.99")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["groups"] == []

    def test_pagination_beyond_results(self, client):
        response = client.get("/similarity-groups?skip=100")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["groups"] == []


class TestGetSimilarityGroupDetail:
    """Tests for GET /similarity-groups/{group_id} endpoint."""

    def test_get_group_detail(self, client):
        """Group detail returns correct structure."""
        with patch.object(thumbnail_generator, 'get_thumbnail', return_value='/cache/thumb.jpg'):
            response = client.get("/similarity-groups/g1")
        assert response.status_code == 200
        data = response.json()
        assert data["group_id"] == "g1"
        assert data["similarity_score"] == 0.95
        assert data["quality_score"] == 0.8
        assert len(data["members"]) == 2

    def test_group_detail_includes_thumbnails(self, client):
        """Each member should have a thumbnail field."""
        with patch.object(thumbnail_generator, 'get_thumbnail', return_value='/cache/thumb.jpg'):
            response = client.get("/similarity-groups/g1")
        data = response.json()
        for member in data["members"]:
            assert "thumbnail" in member
            assert member["thumbnail"] == "/cache/thumb.jpg"

    def test_group_detail_thumbnail_error_returns_none(self, client):
        """If thumbnail generation fails, thumbnail should be None."""
        with patch.object(thumbnail_generator, 'get_thumbnail', side_effect=Exception('fail')):
            response = client.get("/similarity-groups/g1")
        data = response.json()
        for member in data["members"]:
            assert member["thumbnail"] is None

    def test_group_not_found_returns_404(self, client):
        response = client.get("/similarity-groups/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_group_with_no_members(self, client):
        """Group g3 has empty members list."""
        response = client.get("/similarity-groups/g3")
        assert response.status_code == 200
        data = response.json()
        assert data["members"] == []

    def test_member_without_file_path_gets_null_thumbnail(self, client):
        """Members missing file_path or file_hash get thumbnail=None."""
        similarity_group_service.add_group({
            "group_id": "g_no_path",
            "similarity_score": 0.5,
            "quality_score": 0.5,
            "members": [{"photo_id": 99, "file_path": "", "file_hash": "", "filename": "x.jpg"}],
        })
        response = client.get("/similarity-groups/g_no_path")
        assert response.status_code == 200
        assert response.json()["members"][0]["thumbnail"] is None
