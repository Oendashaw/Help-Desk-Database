\set ON_ERROR_STOP on

-- Run as a superuser after loading the sample data and permissions; tests SET ROLE.
BEGIN;
SET LOCAL statement_timeout = '30s';
DO $test$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.staff WHERE staff_id = 1)
       OR NOT EXISTS (SELECT 1 FROM public.assets WHERE asset_id = 1) THEN
        RAISE EXCEPTION 'Load the standard sample data before testing permissions';
    END IF;
    IF (SELECT count(*) FROM pg_roles WHERE rolname IN
        ('helpdesk_agent', 'asset_reader', 'report_reader')
        AND NOT (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) <> 3
       OR EXISTS (
           SELECT 1 FROM pg_auth_members AS m JOIN pg_roles AS r ON r.oid = m.member
           WHERE r.rolname IN ('helpdesk_agent', 'asset_reader', 'report_reader')
       ) THEN
        RAISE EXCEPTION 'Expected three limited NOLOGIN roles without inherited memberships';
    END IF;
END;
$test$;

SET LOCAL ROLE helpdesk_agent;
DO $test$
DECLARE
    new_ticket integer;
    command text;
BEGIN
    PERFORM staff_id, full_name, department FROM public.staff LIMIT 1;
    PERFORM asset_id FROM public.assets LIMIT 1;
    PERFORM update_id FROM public.ticket_updates LIMIT 1;
    INSERT INTO public.tickets (reported_by, asset_id, subject, description)
    VALUES (1, 1, 'Permission test', 'Synthetic permission check')
    RETURNING ticket_id INTO new_ticket;
    UPDATE public.tickets SET assigned_to = 1, status = 'in_progress', priority = 'high'
    WHERE ticket_id = new_ticket;
    INSERT INTO public.ticket_updates (ticket_id, author_id, update_text)
    VALUES (new_ticket, 1, 'Permission test update');
    IF NOT EXISTS (SELECT 1 FROM public.tickets WHERE ticket_id = new_ticket
        AND assigned_to = 1 AND status = 'in_progress' AND priority = 'high') THEN
        RAISE EXCEPTION 'Agent ticket update failed';
    END IF;
    FOREACH command IN ARRAY ARRAY[
        'SELECT email FROM public.staff LIMIT 1',
        'UPDATE public.assets SET asset_type = asset_type WHERE false',
        'UPDATE public.tickets SET reported_by = reported_by WHERE false',
        'UPDATE public.ticket_updates SET update_text = update_text WHERE false',
        'DELETE FROM public.tickets WHERE false',
        'DELETE FROM public.ticket_updates WHERE false',
        'TRUNCATE public.ticket_updates',
        'CREATE TABLE public.permission_probe (id integer)'
    ] LOOP
        BEGIN
            EXECUTE command;
            RAISE EXCEPTION 'Agent unexpectedly allowed: %', command;
        EXCEPTION WHEN insufficient_privilege THEN
            NULL;
        END;
    END LOOP;
    RAISE NOTICE 'helpdesk_agent allowed/denied checks passed';
END;
$test$;
RESET ROLE;

SET LOCAL ROLE asset_reader;
DO $test$
DECLARE
    command text;
BEGIN
    PERFORM asset_id, asset_tag, asset_type, assigned_to FROM public.assets LIMIT 1;
    FOREACH command IN ARRAY ARRAY[
        'SELECT * FROM public.staff LIMIT 1',
        'SELECT * FROM public.tickets LIMIT 1',
        'SELECT * FROM public.ticket_updates LIMIT 1',
        'UPDATE public.assets SET asset_type = asset_type WHERE false',
        'INSERT INTO public.assets (asset_tag, asset_type) VALUES (''DENIED'', ''laptop'')',
        'DELETE FROM public.assets WHERE false',
        'SELECT nextval(''public.assets_asset_id_seq'')',
        'CREATE TABLE public.permission_probe (id integer)'
    ] LOOP
        BEGIN
            EXECUTE command;
            RAISE EXCEPTION 'Asset reader unexpectedly allowed: %', command;
        EXCEPTION WHEN insufficient_privilege THEN
            NULL;
        END;
    END LOOP;
    RAISE NOTICE 'asset_reader allowed/denied checks passed';
END;
$test$;
RESET ROLE;

SET LOCAL ROLE report_reader;
DO $test$
DECLARE
    command text;
BEGIN
    PERFORM status, priority, ticket_count FROM reporting.ticket_summary;
    PERFORM asset_type, asset_count, assigned_count, unassigned_count FROM reporting.asset_inventory;
    FOREACH command IN ARRAY ARRAY[
        'SELECT * FROM public.staff LIMIT 1',
        'SELECT * FROM public.assets LIMIT 1',
        'SELECT * FROM public.tickets LIMIT 1',
        'SELECT * FROM public.ticket_updates LIMIT 1',
        'INSERT INTO public.tickets (reported_by, subject, description) VALUES (1, ''Denied'', ''Denied'')',
        'CREATE TABLE reporting.permission_probe (id integer)',
        'CREATE TABLE public.permission_probe (id integer)'
    ] LOOP
        BEGIN
            EXECUTE command;
            RAISE EXCEPTION 'Report reader unexpectedly allowed: %', command;
        EXCEPTION WHEN insufficient_privilege THEN
            NULL;
        END;
    END LOOP;
    RAISE NOTICE 'report_reader allowed/denied checks passed';
END;
$test$;
RESET ROLE;

DO $test$
BEGIN
    IF (SELECT sum(ticket_count) FROM reporting.ticket_summary) <> (SELECT count(*) FROM public.tickets)
       OR (SELECT sum(asset_count) FROM reporting.asset_inventory) <> (SELECT count(*) FROM public.assets)
       OR EXISTS (SELECT 1 FROM reporting.asset_inventory
                  WHERE asset_count <> assigned_count + unassigned_count) THEN
        RAISE EXCEPTION 'Reporting totals do not match the source tables';
    END IF;
END;
$test$;

GRANT SELECT ON public.assets TO report_reader;
SET LOCAL ROLE report_reader;
SELECT asset_id FROM public.assets LIMIT 1;
RESET ROLE;
REVOKE SELECT ON public.assets FROM report_reader;
SET LOCAL ROLE report_reader;
DO $test$
BEGIN
    BEGIN
        PERFORM asset_id FROM public.assets LIMIT 1;
        RAISE EXCEPTION 'Revoked asset access still works';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;
    END;
    RAISE NOTICE 'GRANT and REVOKE checks passed';
END;
$test$;
RESET ROLE;
ROLLBACK;
