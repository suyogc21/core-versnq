"""Permission catalogue and default grants. Owner implicitly holds every code."""

# code: (module, description). New codes go here and in a migration (0007, 0010, 0011, 0013).
CATALOGUE: dict[str, tuple[str, str]] = {
    "users.read": ("users", "See team members"),
    "users.manage": ("users", "Invite, edit and disable users"),
    "roles.manage": ("users", "Create and edit roles"),
    "teams.manage": ("users", "Create teams and set their members"),
    "settings.manage": ("settings", "Change workspace settings"),
    "audit.read": ("settings", "View the audit log"),
    "leads.create": ("crm", "Add leads"),
    "leads.edit": ("crm", "Edit visible leads, log activities and manage tasks"),
    "leads.assign": ("crm", "Change a lead's owner"),
    "leads.delete": ("crm", "Permanently delete leads"),
    "leads.import": ("crm", "Import leads from a CSV file"),
    "leads.merge": ("crm", "Merge duplicate leads"),
    "crm.configure": ("crm", "Set up stages, sources, custom fields and activity types"),
    "deals.create": ("crm", "Add deals"),
    "deals.edit": ("crm", "Edit visible deals, move them between stages and close them"),
    "deals.delete": ("crm", "Permanently delete deals"),
}
ALL_CODES = frozenset(CATALOGUE)

DEFAULT_GRANTS: dict[str, set[str]] = {
    "admin": set(ALL_CODES),
    "sales_manager": {
        "users.read",
        "leads.create",
        "leads.edit",
        "leads.assign",
        "leads.import",
        "leads.merge",
        "deals.create",
        "deals.edit",
    },
    "sales_user": {"leads.create", "leads.edit", "deals.create", "deals.edit"},
    "finance": {"audit.read"},
}
