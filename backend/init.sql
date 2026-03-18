-- Minimal init for WorldCup Oracle Postgres container.
-- Keeps docker-compose volume mount valid even if app doesn't query DB yet.

CREATE TABLE IF NOT EXISTS app_healthcheck (
  id SERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO app_healthcheck DEFAULT VALUES;

