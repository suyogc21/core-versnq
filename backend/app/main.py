from fastapi import FastAPI

from app.core import errors
from app.core.health import router as health_router
from app.modules.auth.router import router as auth_router
from app.modules.roles.router import router as roles_router
from app.modules.settings.router import router as settings_router
from app.modules.teams.router import router as teams_router
from app.modules.users.router import router as users_router
from app.platform.staff.router import router as staff_auth_router
from app.platform.tenants.router import router as tenants_router

app = FastAPI(title="Versnq Core API", version="0.1.0")
errors.install(app)
app.include_router(health_router)
app.include_router(staff_auth_router)
app.include_router(tenants_router)
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(roles_router)
app.include_router(teams_router)
app.include_router(users_router)
