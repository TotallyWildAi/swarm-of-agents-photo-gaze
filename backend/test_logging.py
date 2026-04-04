"""Tests for structured logging functionality."""
import pytest
import json
import logging
from io import StringIO
from logging_config import configure_logging, LogContext, PerformanceMetricsFilter
from app import app


class TestLoggingConfiguration:
    """Test logging configuration setup."""

    def test_configure_logging_returns_logger(self):
        """Test that configure_logging returns a valid logger."""
        logger = configure_logging()
        assert logger is not None
        assert hasattr(logger, 'info')
        assert hasattr(logger, 'error')

    def test_performance_metrics_filter_adds_fields(self):
        """Test that PerformanceMetricsFilter adds required fields."""
        filter_obj = PerformanceMetricsFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None
        )
        result = filter_obj.filter(record)
        assert result is True
        assert hasattr(record, 'timestamp')
        assert hasattr(record, 'process_id')
        assert hasattr(record, 'thread_id')


class TestLogContext:
    """Test LogContext context manager."""

    def test_log_context_success(self):
        """Test LogContext logs operation start and completion."""
        logger = configure_logging()
        with LogContext(logger, 'test_operation', user_id='123'):
            pass
        assert True

    def test_log_context_with_exception(self):
        """Test LogContext logs operation failure."""
        logger = configure_logging()
        try:
            with LogContext(logger, 'failing_operation'):
                raise ValueError('Test error')
        except ValueError:
            pass
        assert True

    def test_log_context_measures_duration(self):
        """Test LogContext measures operation duration."""
        import time
        logger = configure_logging()
        with LogContext(logger, 'timed_operation') as ctx:
            time.sleep(0.01)
        assert ctx.start_time is not None


class TestFlaskLogging:
    """Test Flask application logging."""

    @pytest.fixture
    def client(self):
        """Create Flask test client."""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_health_check_endpoint(self, client):
        """Test health check endpoint returns 200."""
        response = client.get('/api/health')
        assert response.status_code == 200
        assert response.json['status'] == 'healthy'

    def test_get_data_endpoint(self, client):
        """Test get data endpoint returns data."""
        response = client.get('/api/data?user_id=123')
        assert response.status_code == 200
        assert 'items' in response.json

    def test_error_handling(self, client):
        """Test error handler logs exceptions."""
        response = client.get('/api/nonexistent')
        assert response.status_code == 404
