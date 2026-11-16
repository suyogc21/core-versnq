from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.core import errors
from app.core.health import router as health_router
from app.modules.accounts.router import router as accounts_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.brands.router import router as brands_router
from app.modules.calls.phone import router as phone_router
from app.modules.calls.router import router as calls_router
from app.modules.calls.twilio_router import public as twilio_public_router
from app.modules.calls.twilio_router import router as twilio_router
from app.modules.crm.automations_router import router as automations_router
from app.modules.crm.capture_router import forms_public
from app.modules.crm.capture_router import public as capture_public_router
from app.modules.crm.capture_router import router as capture_router
from app.modules.crm.customers_router import router as customers_router
from app.modules.crm.deals_router import router as deals_router
from app.modules.crm.imports_router import router as imports_router
from app.modules.crm.layouts_router import router as layouts_router
from app.modules.crm.lead_tools_router import router as lead_tools_router
from app.modules.crm.leads_router import router as leads_router
from app.modules.crm.notifications_router import router as notifications_router
from app.modules.crm.organise_router import router as organise_router
from app.modules.crm.pipelines_router import router as pipelines_router
from app.modules.crm.record_types_router import router as record_types_router
from app.modules.crm.records_router import router as records_router
from app.modules.crm.rules_router import router as rules_router
from app.modules.crm.setup_router import router as crm_setup_router
from app.modules.crm.work_router import router as work_router
from app.modules.engage.extension import account as extension_account_router
from app.modules.engage.extension import router as extension_router
from app.modules.engage.inbox_router import router as inbox_router
from app.modules.engage.mailbox_router import router as mailbox_router
from app.modules.engage.pool_router import router as pool_router
from app.modules.engage.router import public as engage_public_router
from app.modules.engage.router import router as engage_router
from app.modules.engage.whatsapp_router import public as whatsapp_public_router
from app.modules.engage.whatsapp_router import router as whatsapp_router
from app.modules.integrations import logs as integration_logs
from app.modules.integrations.ace_console import router as ace_console_router
from app.modules.integrations.lead_api import router as lead_api_router
from app.modules.integrations.router import router as integrations_router
from app.modules.money.router import public as money_webhooks_router
from app.modules.money.router import router as money_router
from app.modules.outreach.router import router as outreach_router
from app.modules.push.router import router as push_router
from app.modules.replies.router import router as replies_router
from app.modules.reports.router import router as reports_router
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
integration_logs.install(app)
app.include_router(health_router)
app.include_router(staff_auth_router)
app.include_router(tenants_router)
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(roles_router)
app.include_router(teams_router)
app.include_router(users_router)
app.include_router(audit_router)
app.include_router(reports_router)  # before the CRM routers: /leads/export is not a lead id
app.include_router(crm_setup_router)
app.include_router(layouts_router)
app.include_router(accounts_router)
app.include_router(lead_api_router)  # before leads: /leads/upsert is not a lead id
app.include_router(leads_router)
app.include_router(lead_tools_router)
app.include_router(rules_router)
app.include_router(notifications_router)
app.include_router(capture_router)
app.include_router(capture_public_router)
app.include_router(forms_public)
app.include_router(customers_router)
app.include_router(money_router)
app.include_router(money_webhooks_router)
app.include_router(imports_router)
app.include_router(record_types_router)
app.include_router(records_router)
app.include_router(pipelines_router)
app.include_router(deals_router)
app.include_router(organise_router)
app.include_router(automations_router)
app.include_router(integrations_router)
app.include_router(engage_router)
app.include_router(engage_public_router)
app.include_router(inbox_router)
app.include_router(mailbox_router)
app.include_router(pool_router)
app.include_router(outreach_router)
app.include_router(replies_router)
app.include_router(calls_router)
app.include_router(phone_router)
app.include_router(twilio_router)
app.include_router(twilio_public_router)
app.include_router(push_router)
app.include_router(brands_router)
app.include_router(ace_console_router)
app.include_router(extension_account_router)
app.include_router(extension_router)
app.include_router(whatsapp_router)
app.include_router(whatsapp_public_router)
app.include_router(work_router)
app.include_router(staff_accounts_router)
