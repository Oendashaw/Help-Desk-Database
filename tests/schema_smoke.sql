\set ON_ERROR_STOP on

BEGIN;

DO $test$
DECLARE
    test_staff_id integer;
    test_asset_id integer;
    test_ticket_id integer;
    test_update_id integer;
    test_suffix text := pg_current_xact_id()::text;
BEGIN
    INSERT INTO public.staff (full_name, email, department)
    VALUES ('Schema Test', 'schema-test-' || test_suffix || '@example.invalid', 'IT')
    RETURNING staff_id INTO test_staff_id;

    INSERT INTO public.assets (asset_tag, asset_type, assigned_to)
    VALUES ('SCHEMA-TEST-' || test_suffix, 'laptop', test_staff_id)
    RETURNING asset_id INTO test_asset_id;

    INSERT INTO public.tickets (reported_by, assigned_to, asset_id, subject, description)
    VALUES (test_staff_id, test_staff_id, test_asset_id, 'Test ticket', 'Synthetic schema check')
    RETURNING ticket_id INTO test_ticket_id;

    INSERT INTO public.ticket_updates (ticket_id, author_id, update_text)
    VALUES (test_ticket_id, test_staff_id, 'Investigating the test ticket')
    RETURNING update_id INTO test_update_id;

    IF NOT EXISTS (
        SELECT 1
        FROM public.ticket_updates AS u
        JOIN public.tickets AS t ON t.ticket_id = u.ticket_id
        JOIN public.assets AS a ON a.asset_id = t.asset_id
        JOIN public.staff AS s ON s.staff_id = t.reported_by
        WHERE u.update_id = test_update_id
          AND u.author_id = s.staff_id
          AND a.assigned_to = s.staff_id
          AND t.assigned_to = s.staff_id
          AND t.status = 'open'
          AND t.priority = 'medium'
          AND t.created_at IS NOT NULL
          AND u.created_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Ticket relationships or defaults failed';
    END IF;

    INSERT INTO public.tickets (reported_by, subject, description)
    VALUES (test_staff_id, 'General IT request', 'A device is optional');

    BEGIN
        UPDATE public.tickets SET status = 'invalid' WHERE ticket_id = test_ticket_id;
        RAISE EXCEPTION 'Invalid ticket status was accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    BEGIN
        UPDATE public.tickets SET priority = 'invalid' WHERE ticket_id = test_ticket_id;
        RAISE EXCEPTION 'Invalid ticket priority was accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    BEGIN
        UPDATE public.tickets SET subject = '   ' WHERE ticket_id = test_ticket_id;
        RAISE EXCEPTION 'Blank ticket subject was accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    BEGIN
        UPDATE public.tickets SET reported_by = NULL WHERE ticket_id = test_ticket_id;
        RAISE EXCEPTION 'Missing ticket reporter was accepted';
    EXCEPTION WHEN not_null_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO public.staff (full_name, email, department)
        VALUES ('Duplicate Test', 'schema-test-' || test_suffix || '@example.invalid', 'IT');
        RAISE EXCEPTION 'Duplicate staff email was accepted';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;

    BEGIN
        UPDATE public.ticket_updates SET ticket_id = 0 WHERE update_id = test_update_id;
        RAISE EXCEPTION 'An update without an existing ticket was accepted';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    BEGIN
        DELETE FROM public.staff WHERE staff_id = test_staff_id;
        RAISE EXCEPTION 'A staff member with linked records was deleted';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    RAISE NOTICE 'Schema checks passed';
END;
$test$;

ROLLBACK;
