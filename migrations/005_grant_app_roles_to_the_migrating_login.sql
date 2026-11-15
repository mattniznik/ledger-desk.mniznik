-- The login that runs the migrations (the server's admin) connects for the app and the ERP and switches to their
-- roles with SET ROLE. Postgres 16 and later give a non-superuser that creates a role only admin rights over it, not
-- the right to switch to it: on a managed server, where the admin is not a superuser, every SET ROLE failed with
-- "permission denied to set role" (measured on Postgres 17 with a CREATEROLE admin). Grant the switch explicitly;
-- INHERIT FALSE so the admin does not take on the roles' privileges without switching. A superuser running this
-- locally gains a harmless membership; granting it again only raises a notice.
GRANT ledger_app, ledger_agent, ledger_erp TO CURRENT_USER WITH INHERIT FALSE, SET TRUE;
