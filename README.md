# FastAPI Application

A FastAPI-based microservice with PostgreSQL, SQLAlchemy, and Qdrant vector database integration.

## Setup

### Local Development

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run tests:
   ```bash
   pytest -v
   ```

4. Run the application:
   ```bash
   uvicorn main:app --reload
   ```

### Docker Compose

```bash
docker-compose up
```

## Testing

Run unit tests with coverage:
```bash
pytest -v --cov=. --cov-report=html
```

Run integration tests (requires Docker Compose):
```bash
pytest tests/test_integration.py -v
```
