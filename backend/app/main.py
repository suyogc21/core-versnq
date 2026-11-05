from fastapi import FastAPI

from app.core.health import router as health_router
from app.platform.staff.router import router as staff_auth_router
from app.platform.tenants.router import router as tenants_router

app = FastAPI(title="Versnq Core API", version="0.1.0")
app.include_router(health_router)
app.include_router(staff_auth_router)
app.include_router(tenants_router)
