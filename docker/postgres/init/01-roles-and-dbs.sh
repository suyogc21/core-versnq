#!/bin/sh
# Runs once, on first start of an empty data volume.
# versnq_owner: owns the databases and runs migrations.
# versnq_app:   used by the API and worker; cannot bypass row-level security.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
  CREATE ROLE versnq_owner LOGIN PASSWORD '${OWNER_DB_PASSWORD}';
  CREATE ROLE versnq_app LOGIN PASSWORD '${APP_DB_PASSWORD}'
    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  CREATE DATABASE versnq OWNER versnq_owner;
  CREATE DATABASE versnq_test OWNER versnq_owner;
  CREATE DATABASE versnq_e2e OWNER versnq_owner;
EOSQL

for db in versnq versnq_test versnq_e2e; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-EOSQL
    REVOKE ALL ON DATABASE $db FROM PUBLIC;
    GRANT CONNECT ON DATABASE $db TO versnq_owner, versnq_app;
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    GRANT USAGE ON SCHEMA public TO versnq_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE versnq_owner IN SCHEMA public
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO versnq_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE versnq_owner IN SCHEMA public
      GRANT USAGE, SELECT ON SEQUENCES TO versnq_app;
EOSQL
done
