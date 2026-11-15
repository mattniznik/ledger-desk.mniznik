-- Runs: one row per workflow run a visitor starts. The run's progress and its
-- approval pause live in LangGraph's checkpoint tables (thread id "<session>:<run>"); this row is
-- what says which session owns the run, under the same row-level security as every app table, so
-- one visitor cannot read another's run by guessing its id.

CREATE TABLE app.runs (
  id          uuid PRIMARY KEY,
  session_id  uuid NOT NULL REFERENCES app.sessions ON DELETE CASCADE,
  invoice_id  int REFERENCES app.invoices ON DELETE CASCADE,
  sample      text NOT NULL,
  invoice_ref text NOT NULL,
  mode        text NOT NULL CHECK (mode IN ('replay', 'scripted', 'live')),
  model       text NOT NULL,
  status      text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE app.runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_session ON app.runs USING (session_id = app.current_session()) WITH CHECK (session_id = app.current_session());

GRANT SELECT, INSERT, UPDATE ON app.runs TO ledger_app;
GRANT SELECT ON app.runs TO ledger_agent;
