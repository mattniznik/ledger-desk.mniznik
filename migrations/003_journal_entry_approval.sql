-- What the ERP keeps about each posting request: who approved it and their
-- signature, and a hash of the request body. The hash is how a repeated Idempotency-Key is told
-- apart: the same body is a retry and gets the first entry back; a different body is a conflict.

ALTER TABLE erp.journal_entries
  ADD COLUMN request_hash text NOT NULL DEFAULT '',
  ADD COLUMN approver     text NOT NULL DEFAULT '',
  ADD COLUMN signature    text NOT NULL DEFAULT '';
