-- The app's own tables, with the database doing the enforcing (docs/decisions/0004):
-- - every row carries a session_id, and row-level security limits each request to its own
--   session, so each visitor gets a private copy of the company;
-- - audit_log is insert-only for every role, and each row carries the hash of the one before,
--   so an edited row breaks the chain when audit_verify runs;
-- - the agent's role cannot insert approvals.

CREATE SCHEMA app;

CREATE FUNCTION app.current_session() RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.session_id', true), '')::uuid
$$;

CREATE TABLE app.sessions (
  id         uuid PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.invoices (
  id          serial PRIMARY KEY,
  session_id  uuid NOT NULL REFERENCES app.sessions ON DELETE CASCADE,
  vendor_name text NOT NULL,
  number      text NOT NULL,
  status      text NOT NULL,
  total       numeric(12, 2) NOT NULL,
  po          text,
  extracted   jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.checks (
  id         serial PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES app.sessions ON DELETE CASCADE,
  invoice_id int  NOT NULL REFERENCES app.invoices ON DELETE CASCADE,
  code       text NOT NULL,
  passed     boolean NOT NULL,
  detail     text NOT NULL DEFAULT ''
);

CREATE TABLE app.approvals (
  id              serial PRIMARY KEY,
  session_id      uuid NOT NULL REFERENCES app.sessions ON DELETE CASCADE,
  invoice_id      int  NOT NULL REFERENCES app.invoices ON DELETE CASCADE,
  role            text NOT NULL CHECK (role IN ('clerk', 'controller')),
  decision        text NOT NULL CHECK (decision IN ('approve', 'reject', 'hold')),
  reason          text,
  phone_confirmed boolean NOT NULL DEFAULT false,
  signature       text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.audit_log (
  id         bigserial PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES app.sessions ON DELETE CASCADE,
  at         timestamptz NOT NULL,
  actor      text NOT NULL,
  action     text NOT NULL,
  entity     text NOT NULL,
  detail     jsonb NOT NULL DEFAULT '{}',
  prev_hash  text NOT NULL,
  hash       text NOT NULL
);

-- Row-level security: a row is visible and writable only within its own session.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['invoices', 'checks', 'approvals', 'audit_log'] LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY own_session ON app.%I USING (session_id = app.current_session()) WITH CHECK (session_id = app.current_session())', t);
  END LOOP;
END $$;
ALTER TABLE app.sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_session ON app.sessions USING (id = app.current_session()) WITH CHECK (id = app.current_session());

-- The hash of one audit row: the previous row's hash and this row's content, so editing any row
-- changes its hash and breaks every link after it.
CREATE FUNCTION app.audit_hash(prev text, actor text, action text, entity text, detail jsonb, at timestamptz)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(sha256(convert_to(concat_ws('|', prev, actor, action, entity, detail::text,
    to_char(at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')), 'UTF8')), 'hex')
$$;

CREATE FUNCTION app.audit_append(p_session uuid, p_actor text, p_action text, p_entity text, p_detail jsonb)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE
  prev text;
  ts timestamptz := clock_timestamp();
  new_id bigint;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(p_session::text));  -- one writer per session at a time
  SELECT hash INTO prev FROM app.audit_log WHERE session_id = p_session ORDER BY id DESC LIMIT 1;
  prev := coalesce(prev, 'genesis');
  INSERT INTO app.audit_log (session_id, at, actor, action, entity, detail, prev_hash, hash)
  VALUES (p_session, ts, p_actor, p_action, p_entity, p_detail, prev,
          app.audit_hash(prev, p_actor, p_action, p_entity, p_detail, ts))
  RETURNING id INTO new_id;
  RETURN new_id;
END $$;

-- The first row whose chain does not check out, or NULL when the whole log is intact.
CREATE FUNCTION app.audit_verify(p_session uuid) RETURNS bigint LANGUAGE plpgsql STABLE AS $$
DECLARE
  r record;
  prev text := 'genesis';
BEGIN
  FOR r IN SELECT * FROM app.audit_log WHERE session_id = p_session ORDER BY id LOOP
    IF r.prev_hash <> prev OR r.hash <> app.audit_hash(r.prev_hash, r.actor, r.action, r.entity, r.detail, r.at) THEN
      RETURN r.id;
    END IF;
    prev := r.hash;
  END LOOP;
  RETURN NULL;
END $$;

GRANT USAGE ON SCHEMA app TO ledger_app, ledger_agent;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO ledger_app, ledger_agent;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO ledger_app, ledger_agent;

-- The app: reads and writes its own rows, records approvals, appends to the audit log.
GRANT SELECT, INSERT ON app.sessions TO ledger_app;
GRANT SELECT, INSERT, UPDATE ON app.invoices, app.checks TO ledger_app;
GRANT SELECT, INSERT ON app.approvals TO ledger_app;
GRANT SELECT, INSERT ON app.audit_log TO ledger_app;

-- The agent: reads, writes its own check notes, appends to the audit log. No approvals at all.
GRANT SELECT ON app.sessions, app.invoices, app.checks TO ledger_agent;
GRANT INSERT ON app.checks TO ledger_agent;
GRANT SELECT, INSERT ON app.audit_log TO ledger_agent;

-- No role gets UPDATE or DELETE on audit_log.
