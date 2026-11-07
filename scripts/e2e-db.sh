#!/bin/sh
# Creates the end-to-end test database on an existing Postgres volume (new volumes get it
# from docker/postgres/init). Safe to run more than once.
set -e
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres <<'SQL'
SELECT 'CREATE DATABASE versnq_e2e OWNER versnq_owner'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'versnq_e2e')\gexec
SQL
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d versnq_e2e <<'SQL'
REVOKE ALL ON DATABASE versnq_e2e FROM PUBLIC;
GRANT CONNECT ON DATABASE versnq_e2e TO versnq_owner, versnq_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO versnq_app;
ALTER DEFAULT PRIVILEGES FOR ROLE versnq_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO versnq_app;
ALTER DEFAULT PRIVILEGES FOR ROLE versnq_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO versnq_app;
SQL
echo "versnq_e2e is ready"
