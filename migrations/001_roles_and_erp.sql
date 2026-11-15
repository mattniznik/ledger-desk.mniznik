-- The mock ERP's tables, in their own schema with their own role (docs/decisions/0004).
-- The app and the agent never touch these directly; they go through the ERP's API.

-- Roles are cluster-wide, so create them only once. NOLOGIN: services connect as a login role
-- and SET ROLE, and tests do the same.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ledger_app') THEN CREATE ROLE ledger_app NOLOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ledger_agent') THEN CREATE ROLE ledger_agent NOLOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ledger_erp') THEN CREATE ROLE ledger_erp NOLOGIN; END IF;
END $$;

CREATE SCHEMA erp;

CREATE TABLE erp.accounts (
  number text PRIMARY KEY,
  name   text NOT NULL
);

CREATE TABLE erp.vendors (
  id              text PRIMARY KEY,
  name            text NOT NULL,
  tax_id          text NOT NULL UNIQUE,
  category        text NOT NULL,
  terms_days      int  NOT NULL,
  default_account text NOT NULL REFERENCES erp.accounts,
  bank            text NOT NULL,
  account_last4   text NOT NULL,
  uses_po         boolean NOT NULL,
  recurring       boolean NOT NULL
);

CREATE TABLE erp.purchase_orders (
  number    text PRIMARY KEY,
  vendor_id text NOT NULL REFERENCES erp.vendors,
  date      date NOT NULL
);

CREATE TABLE erp.po_lines (
  po          text NOT NULL REFERENCES erp.purchase_orders,
  line        int  NOT NULL,
  description text NOT NULL,
  quantity    numeric(12, 3) NOT NULL,
  unit_price  numeric(12, 4) NOT NULL,
  account     text NOT NULL REFERENCES erp.accounts,
  PRIMARY KEY (po, line)
);

CREATE TABLE erp.receipts (
  id       serial PRIMARY KEY,
  po       text NOT NULL,
  line     int  NOT NULL,
  quantity numeric(12, 3) NOT NULL,
  date     date NOT NULL,
  FOREIGN KEY (po, line) REFERENCES erp.po_lines
);

CREATE TABLE erp.bills (
  id        serial PRIMARY KEY,
  vendor_id text NOT NULL REFERENCES erp.vendors,
  number    text NOT NULL,
  date      date NOT NULL,
  total     numeric(12, 2) NOT NULL,
  po        text REFERENCES erp.purchase_orders,
  status    text NOT NULL,
  UNIQUE (vendor_id, number)
);

CREATE TABLE erp.bill_lines (
  bill_id  int NOT NULL REFERENCES erp.bills,
  po_line  int NOT NULL,
  quantity numeric(12, 3) NOT NULL
);

CREATE TABLE erp.journal_entries (
  id              serial PRIMARY KEY,
  invoice_ref     text NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  posted_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE erp.journal_lines (
  id       serial PRIMARY KEY,
  entry_id int  NOT NULL REFERENCES erp.journal_entries,
  account  text NOT NULL REFERENCES erp.accounts,
  debit    numeric(12, 2) NOT NULL DEFAULT 0,
  credit   numeric(12, 2) NOT NULL DEFAULT 0,
  -- each line is a debit or a credit, never both, never negative
  CHECK (debit >= 0 AND credit >= 0 AND (debit = 0) <> (credit = 0))
);

-- An entry balances when its debits equal its credits and it has at least two lines. Checked at
-- COMMIT (deferred), so the lines of one entry can be inserted one at a time inside a transaction.
CREATE FUNCTION erp.assert_balanced(p_entry int) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  n int; d numeric; c numeric;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM erp.journal_entries WHERE id = p_entry) THEN
    RETURN;
  END IF;
  SELECT count(*), coalesce(sum(debit), 0), coalesce(sum(credit), 0) INTO n, d, c
    FROM erp.journal_lines WHERE entry_id = p_entry;
  IF n < 2 OR d <> c THEN
    RAISE EXCEPTION 'journal entry % does not balance: debits %, credits %, % lines', p_entry, d, c, n;
  END IF;
END $$;

CREATE FUNCTION erp.journal_lines_balance() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM erp.assert_balanced(CASE WHEN TG_OP = 'DELETE' THEN OLD.entry_id ELSE NEW.entry_id END);
  RETURN NULL;
END $$;

CREATE FUNCTION erp.journal_entries_balance() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM erp.assert_balanced(NEW.id);
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER journal_lines_balance
  AFTER INSERT OR UPDATE OR DELETE ON erp.journal_lines
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION erp.journal_lines_balance();

CREATE CONSTRAINT TRIGGER journal_entries_balance
  AFTER INSERT ON erp.journal_entries
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION erp.journal_entries_balance();

GRANT USAGE ON SCHEMA erp TO ledger_erp;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA erp TO ledger_erp;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA erp TO ledger_erp;
