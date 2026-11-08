from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.core import errors
from app.core.health import router as health_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.crm.capture_router import public as capture_public_router
from app.modules.crm.capture_router import router as capture_router
from app.modules.crm.imports_router import router as imports_router
from app.modules.crm.lead_tools_router import router as lead_tools_router
from app.modules.crm.leads_router import router as leads_router
from app.modules.crm.notifications_router import router as notifications_router
from app.modules.crm.rules_router import router as rules_router
from app.modules.crm.setup_router import router as crm_setup_router
from app.modules.crm.work_router import router as work_router
from app.modules.roles.router import router as roles_router
from app.modules.settings.router import router as settings_router
from app.modules.teams.router import router as teams_router
from app.modules.users.router import router as users_router
from app.platform.staff.accounts import router as staff_accounts_router
from app.platform.staff.router import router as staff_auth_router
from app.platform.tenants.router import router as tenants_router


def _operation_id(route: APIRoute) -> str:
    """Stable, readable operation IDs (e.g. users-invite_user) for generated clients."""
    return f"{route.tags[0]}-{route.name}" if route.tags else route.name


app = FastAPI(title="Versnq Core API", version="0.1.0", generate_unique_id_function=_operation_id)
errors.install(app)
app.include_router(health_router)
app.include_router(staff_auth_router)
app.include_router(tenants_router)
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(roles_router)
app.include_router(teams_router)
app.include_router(users_router)
app.include_router(audit_router)
app.include_router(crm_setup_router)
app.include_router(leads_router)
app.include_router(lead_tools_router)
app.include_router(rules_router)
app.include_router(notifications_router)
app.include_router(capture_router)
app.include_router(capture_public_router)
app.include_router(imports_router)
app.include_router(work_router)
app.include_router(staff_accounts_router)
