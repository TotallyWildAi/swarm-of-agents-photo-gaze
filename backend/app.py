"""Flask application with structured logging."""
from flask import Flask, request, jsonify
from logging_config import configure_logging, LogContext
import structlog
import time


app = Flask(__name__)
logger = configure_logging()


@app.before_request
def log_request_start():
    """Log incoming request details."""
    request.start_time = time.time()
    logger.info(
        'request_received',
        method=request.method,
        path=request.path,
        remote_addr=request.remote_addr
    )


@app.after_request
def log_request_end(response):
    """Log request completion with performance metrics."""
    duration = time.time() - request.start_time
    logger.info(
        'request_completed',
        method=request.method,
        path=request.path,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2)
    )
    return response


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint with logging."""
    with LogContext(logger, 'health_check'):
        return jsonify({'status': 'healthy'}), 200


@app.route('/api/data', methods=['GET'])
def get_data():
    """Get data endpoint with structured logging."""
    with LogContext(logger, 'get_data', user_id=request.args.get('user_id')):
        data = {'items': [1, 2, 3]}
        return jsonify(data), 200


@app.errorhandler(Exception)
def handle_error(error):
    """Global error handler with logging."""
    logger.error(
        'unhandled_exception',
        error=str(error),
        error_type=type(error).__name__
    )
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
