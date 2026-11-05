"""Permission catalogue and default grants. Owner implicitly holds every code."""

# code: (module, description). Phase 2 adds lead/deal codes here and in a migration.
CATALOGUE: dict[str, tuple[str, str]] = {
    "users.read": ("users", "See team members"),
    "users.manage": ("users", "Invite, edit and disable users"),
    "roles.manage": ("users", "Create and edit roles"),
    "teams.manage": ("users", "Create teams and set their members"),
    "settings.manage": ("settings", "Change workspace settings"),
    "audit.read": ("settings", "View the audit log"),
}
ALL_CODES = frozenset(CATALOGUE)

DEFAULT_GRANTS: dict[str, set[str]] = {
    "admin": set(ALL_CODES),
    "sales_manager": {"users.read"},
    "sales_user": set(),
    "finance": {"audit.read"},
}
