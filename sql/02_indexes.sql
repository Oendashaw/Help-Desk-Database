-- Run once after loading sample data; plain SQL also works in pgAdmin.
-- Fail on an existing name rather than silently accepting a different definition.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

-- Ticket conversation: equality lookup followed by stable chronological order.
CREATE INDEX idx_updates_ticket_created
    ON public.ticket_updates (ticket_id, created_at, update_id);

-- Reporter history: avoids scanning and sorting all tickets for LIMIT 50.
CREATE INDEX idx_tickets_reporter_created
    ON public.tickets (reported_by, created_at DESC, ticket_id DESC);

-- Active agent queue: exclude resolved/closed records from this index.
-- This partial index does not cover foreign-key checks for all assigned tickets.
CREATE INDEX idx_tickets_active_agent_created
    ON public.tickets (assigned_to, created_at DESC, ticket_id DESC)
    WHERE status IN ('open', 'in_progress');
COMMIT;
