"""Tests for session management API endpoints."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.models import Base, UserPreferences
from app.database import DATABASE_URL, SessionLocal


@pytest.fixture
def client():
    """Create test client for FastAPI app."""
    return TestClient(app)


@pytest.fixture
def test_db():
    """Create test database session."""
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_create_preferences_endpoint(client, test_db):
    """Test POST /preferences endpoint creates user preferences."""
    response = client.post('/preferences', json={
        'username': 'testuser',
        'email': 'test@example.com',
        'preferred_embedding_model': 'clip-vit-base-patch32',
        'enable_auto_processing': True
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data['username'] == 'testuser'
    assert data['threshold_setting'] == 0.5  # default


def test_get_preferences_endpoint(client, test_db):
    """Test GET /preferences/{username} endpoint retrieves preferences."""
    user = UserPreferences(
        username='testuser',
        email='test@example.com',
        threshold_setting=0.6
    )
    test_db.add(user)
    test_db.commit()
    
    response = client.get('/preferences/testuser')
    
    assert response.status_code == 200
    data = response.json()
    assert data['username'] == 'testuser'
    assert data['threshold_setting'] == 0.6


def test_update_threshold_endpoint(client, test_db):
    """Test POST /threshold/{username} endpoint updates threshold."""
    user = UserPreferences(
        username='testuser',
        email='test@example.com',
        threshold_setting=0.5
    )
    test_db.add(user)
    test_db.commit()
    
    response = client.post('/threshold/testuser', json={
        'threshold_setting': 0.8
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data['threshold_setting'] == 0.8


def test_get_threshold_endpoint(client, test_db):
    """Test GET /threshold/{username} endpoint retrieves threshold."""
    user = UserPreferences(
        username='testuser',
        email='test@example.com',
        threshold_setting=0.7
    )
    test_db.add(user)
    test_db.commit()
    
    response = client.get('/threshold/testuser')
    
    assert response.status_code == 200
    data = response.json()
    assert data['threshold_setting'] == 0.7


def test_get_nonexistent_user(client):
    """Test GET /preferences for nonexistent user returns 404."""
    response = client.get('/preferences/nonexistent')
    assert response.status_code == 404
