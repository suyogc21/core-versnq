from fastapi import FastAPI

from app.core.health import router as health_router

app = FastAPI(title="Versnq Core API", version="0.1.0")
app.include_router(health_router)
