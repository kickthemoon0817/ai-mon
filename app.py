from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

import db
from models import UsageSummary, ServiceUsage

app = FastAPI(title="AI Usage Monitor")

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
async def startup():
    db.refresh_all()


@app.get("/api/summary", response_model=UsageSummary)
async def summary():
    return db.get_summary()


@app.get("/api/usage/{service}", response_model=ServiceUsage)
async def usage(service: str):
    result = db.get_service(service)
    if result is None:
        raise HTTPException(404, f"Unknown service: {service}")
    return result


@app.get("/api/refresh", response_model=UsageSummary)
async def refresh():
    return db.refresh_all()


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
