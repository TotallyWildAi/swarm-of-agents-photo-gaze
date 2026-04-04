from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="App API")


@app.get("/health")
async def health_check():
    """Health check endpoint for service verification."""
    return JSONResponse(status_code=200, content={"status": "healthy"})
