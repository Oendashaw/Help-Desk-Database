-- MANUAL DEMO: use a disposable sample database and three pgAdmin Query Tools.
-- Execute the sections individually, never this entire file at once.

-- SESSION A: select these statements and run. Leave the transaction open.
BEGIN;
SET LOCAL idle_in_transaction_session_timeout = '2min';
SELECT ticket_id FROM public.tickets WHERE ticket_id = 25000 FOR UPDATE;

-- SESSION B: select these statements in a second Query Tool and run.
-- This waits for A, without changing any data. Timeout bounds the demonstration.
BEGIN;
SET LOCAL statement_timeout = '60s';
SELECT ticket_id FROM public.tickets WHERE ticket_id = 25000 FOR UPDATE;

-- SESSION C: while B is waiting, run sql/monitoring.sql in a third Query Tool.
-- Confirm B's blocked_pid points to A's blocking_pid.

-- CLEANUP: run ROLLBACK separately in both A and B.
-- If B is still waiting, roll back A first, then roll back B after it returns.
ROLLBACK;
