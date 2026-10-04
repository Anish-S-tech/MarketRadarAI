-- Runs once on first container start (as the superuser/owner role).
-- The application connects as a NON-superuser role so Postgres row-level security applies to it.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marketradar_app') THEN
    CREATE ROLE marketradar_app LOGIN PASSWORD 'marketradar_app';
  END IF;
END$$;

GRANT CONNECT ON DATABASE marketradar TO marketradar_app;
GRANT USAGE ON SCHEMA public TO marketradar_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO marketradar_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO marketradar_app;
