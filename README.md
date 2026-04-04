# Structured Logging Implementation

This project implements comprehensive structured logging across Python backend and Node.js frontend services with log aggregation and monitoring capabilities.

## Features

### Backend (Python/Flask)
- **Structured Logging**: JSON-formatted logs using `structlog` and `python-json-logger`
- **Performance Metrics**: Automatic duration tracking for operations and requests
- **Log Levels**: DEBUG, INFO, WARNING, ERROR with appropriate context
- **Request Tracking**: Automatic logging of HTTP requests with status codes and response times
- **Error Handling**: Global exception handler with detailed error logging

### Frontend (Node.js/Express)
- **Winston Logger**: Structured logging with JSON output
- **Multiple Transports**: Console output with colorized formatting
- **Performance Context**: Utility class for tracking operation duration and status
- **Request Middleware**: Automatic logging of all HTTP requests and responses
- **Error Tracking**: Comprehensive error logging with stack traces

## Project Structure

```
.
├── backend/
│   ├── requirements.txt          # Python dependencies
│   ├── logging_config.py         # Logging configuration and utilities
│   ├── app.py                    # Flask application with logging
│   └── test_logging.py           # Tests for logging functionality
├── frontend/
│   ├── package.json              # Node.js dependencies
│   └── src/
│       ├── logger.js             # Logger configuration and utilities
│       ├── index.js              # Express application with logging
│       ├── logger.test.js        # Tests for logger
│       └── index.test.js         # Tests for Express app
└── README.md                     # This file
```

## Setup and Installation

### Backend Setup

```bash
cd backend
pip install -r requirements.txt
```

### Frontend Setup

```bash
cd frontend
npm install
```

## Running the Services

### Backend

```bash
cd backend
python app.py
```

The Flask application will start on `http://localhost:5000`

### Frontend

```bash
cd frontend
npm start
```

The Express application will start on `http://localhost:3000`

## Testing

### Backend Tests

```bash
cd backend
pytest -v
```

### Frontend Tests

```bash
cd frontend
npm test
```

## Log Output Examples

### Backend JSON Log

```json
{
  "timestamp": "2024-04-05T10:30:45.123Z",
  "level": "info",
  "name": "app",
  "message": "request_completed",
  "method": "GET",
  "path": "/api/data",
  "status_code": 200,
  "duration_ms": 45.23,
  "process_id": 12345,
  "thread_id": 67890
}
```

### Frontend JSON Log

```json
{
  "timestamp": "2024-04-05 10:30:45.123",
  "level": "info",
  "message": "operation_completed",
  "service": "frontend-service",
  "operation": "get_data",
  "duration_ms": 42,
  "user_id": "123",
  "items_count": 3
}
```

## Monitoring and Debugging

### Log Aggregation

All logs are output in JSON format, making them suitable for aggregation with tools like:
- ELK Stack (Elasticsearch, Logstash, Kibana)
- Splunk
- CloudWatch
- Datadog

### Performance Analysis

Duration metrics are logged for all operations, enabling:
- Performance bottleneck identification
- SLA monitoring
- Trend analysis

### Debugging

Structured logs include:
- Request/operation context (user_id, operation name, etc.)
- Error details with stack traces
- Performance metrics
- Process and thread information (backend)

## Best Practices

1. **Use appropriate log levels**:
   - DEBUG: Detailed diagnostic information
   - INFO: General informational messages
   - WARNING: Warning messages for potentially harmful situations
   - ERROR: Error messages for serious problems

2. **Include context**: Always log relevant context (user_id, request_id, etc.)

3. **Track performance**: Use LogContext/PerformanceContext for all operations

4. **Avoid logging sensitive data**: Never log passwords, tokens, or PII

5. **Use structured fields**: Leverage JSON structure for better querying and analysis
