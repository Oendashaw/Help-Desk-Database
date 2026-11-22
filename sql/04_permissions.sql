-- Run once per dedicated help desk database as its table owner, after 03_roles.sql.
BEGIN;
CREATE SCHEMA reporting;

-- Views use the owner's table access; readers receive only aggregate results.
CREATE VIEW reporting.ticket_summary AS
SELECT status, priority, count(*) AS ticket_count
FROM public.tickets
GROUP BY status, priority;

CREATE VIEW reporting.asset_inventory AS
SELECT asset_type, count(*) AS asset_count,
       count(*) FILTER (WHERE assigned_to IS NOT NULL) AS assigned_count,
       count(*) FILTER (WHERE assigned_to IS NULL) AS unassigned_count
FROM public.assets
GROUP BY asset_type;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON public.staff, public.assets, public.tickets, public.ticket_updates FROM PUBLIC;
REVOKE ALL ON SEQUENCE public.staff_staff_id_seq, public.assets_asset_id_seq,
    public.tickets_ticket_id_seq, public.ticket_updates_update_id_seq FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO helpdesk_agent, asset_reader;
GRANT SELECT (staff_id, full_name, department) ON public.staff TO helpdesk_agent;
GRANT SELECT ON public.assets, public.tickets, public.ticket_updates TO helpdesk_agent;
GRANT INSERT (reported_by, assigned_to, asset_id, subject, description, status, priority)
    ON public.tickets TO helpdesk_agent;
GRANT UPDATE (assigned_to, status, priority) ON public.tickets TO helpdesk_agent;
GRANT INSERT (ticket_id, author_id, update_text) ON public.ticket_updates TO helpdesk_agent;
GRANT USAGE ON SEQUENCE public.tickets_ticket_id_seq,
    public.ticket_updates_update_id_seq TO helpdesk_agent;

GRANT SELECT ON public.assets TO asset_reader;
GRANT USAGE ON SCHEMA reporting TO report_reader;
GRANT SELECT ON reporting.ticket_summary, reporting.asset_inventory TO report_reader;
COMMIT;
