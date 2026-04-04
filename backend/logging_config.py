"""Structured logging configuration for backend services."""
import structlog
import logging
import json
from pythonjsonlogger import jsonlogger
from datetime import datetime
import time


class PerformanceMetricsFilter(logging.Filter):
    """Add performance metrics to log records."""

    def filter(self, record):
        record.timestamp = datetime.utcnow().isoformat()
        record.process_id = record.process
        record.thread_id = record.thread
        return True


def configure_logging(log_level=logging.INFO):
    """Configure structured logging with JSON output and performance metrics."""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt='iso'),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    json_handler = logging.StreamHandler()
    json_formatter = jsonlogger.JsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s %(process_id)s %(thread_id)s'
    )
    json_handler.setFormatter(json_formatter)
    json_handler.addFilter(PerformanceMetricsFilter())
    root_logger.addHandler(json_handler)

    return structlog.get_logger()


class LogContext:
    """Context manager for tracking request/operation performance."""

    def __init__(self, logger, operation_name, **context):
        self.logger = logger
        self.operation_name = operation_name
        self.context = context
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        self.logger.info(
            'operation_started',
            operation=self.operation_name,
            **self.context
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        if exc_type is None:
            self.logger.info(
                'operation_completed',
                operation=self.operation_name,
                duration_ms=round(duration * 1000, 2),
                **self.context
            )
        else:
            self.logger.error(
                'operation_failed',
                operation=self.operation_name,
                duration_ms=round(duration * 1000, 2),
                error=str(exc_val),
                **self.context
            )
        return False
