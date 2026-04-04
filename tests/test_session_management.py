"""Integration tests for session management and preferences persistence."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, UserPreferences
from app.database import DATABASE_URL


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


def test_create_user_preferences(test_db):
    """Test creating user preferences with threshold setting."""
    user = UserPreferences(
        username='testuser',
        email='test@example.com',
        preferred_embedding_model='clip-vit-base-patch32',
        enable_auto_processing=True,
        threshold_setting=0.75
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)
    
    assert user.id is not None
    assert user.username == 'testuser'
    assert user.threshold_setting == 0.75


def test_retrieve_user_preferences(test_db):
    """Test retrieving user preferences from database."""
    user = UserPreferences(
        username='testuser',
        email='test@example.com',
        threshold_setting=0.5
    )
    test_db.add(user)
    test_db.commit()
    
    retrieved = test_db.query(UserPreferences).filter(
        UserPreferences.username == 'testuser'
    ).first()
    
    assert retrieved is not None
    assert retrieved.threshold_setting == 0.5


def test_update_threshold_setting(test_db):
    """Test updating threshold setting persists across sessions."""
    user = UserPreferences(
        username='testuser',
        email='test@example.com',
        threshold_setting=0.5
    )
    test_db.add(user)
    test_db.commit()
    user_id = user.id
    
    # Update threshold
    user.threshold_setting = 0.8
    test_db.commit()
    
    # Retrieve in new session to verify persistence
    test_db.expunge_all()
    retrieved = test_db.query(UserPreferences).filter(
        UserPreferences.id == user_id
    ).first()
    
    assert retrieved.threshold_setting == 0.8


def test_multiple_users_isolated(test_db):
    """Test that multiple users have isolated preferences."""
    user1 = UserPreferences(
        username='user1',
        email='user1@example.com',
        threshold_setting=0.3
    )
    user2 = UserPreferences(
        username='user2',
        email='user2@example.com',
        threshold_setting=0.7
    )
    test_db.add(user1)
    test_db.add(user2)
    test_db.commit()
    
    retrieved1 = test_db.query(UserPreferences).filter(
        UserPreferences.username == 'user1'
    ).first()
    retrieved2 = test_db.query(UserPreferences).filter(
        UserPreferences.username == 'user2'
    ).first()
    
    assert retrieved1.threshold_setting == 0.3
    assert retrieved2.threshold_setting == 0.7
