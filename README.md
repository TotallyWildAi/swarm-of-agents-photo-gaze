# Project

Full-stack application with FastAPI backend and React TypeScript frontend.

## Architecture

- **Backend**: FastAPI (Python) on port 8000
- **Frontend**: React TypeScript on port 3000
- **Database**: PostgreSQL on port 5432
- **Vector DB**: Qdrant on port 6333

## Setup

### Backend

```bash
pip install -r requirements.txt
pytest -v
```

### Frontend

```bash
npm install
npm start
```

### Docker Compose

```bash
docker-compose up
```

Access the app at http://localhost:3000
