\set ON_ERROR_STOP on

DO $test$
BEGIN
    IF (SELECT count(*) FROM public.staff) <> 200
       OR (SELECT count(*) FROM public.assets) <> 1000
       OR (SELECT count(*) FROM public.tickets) <> 50000 THEN
        RAISE EXCEPTION 'Generated staff, asset, or ticket counts are incorrect';
    END IF;

    IF (
        SELECT count(*)
        FROM (
            SELECT ticket_id
            FROM public.ticket_updates
            GROUP BY ticket_id
            HAVING count(*) BETWEEN 1 AND 3
        ) AS valid_update_counts
    ) <> 50000 THEN
        RAISE EXCEPTION 'Each generated ticket must have one to three updates';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.ticket_updates AS u
        JOIN public.tickets AS t ON t.ticket_id = u.ticket_id
        WHERE u.created_at <= t.created_at
    ) THEN
        RAISE EXCEPTION 'A generated update does not follow its ticket creation time';
    END IF;

    IF (SELECT count(DISTINCT status) FROM public.tickets) <> 4
       OR (SELECT count(DISTINCT priority) FROM public.tickets) <> 4
       OR NOT EXISTS (SELECT 1 FROM public.tickets WHERE asset_id IS NULL)
       OR NOT EXISTS (SELECT 1 FROM public.tickets WHERE assigned_to IS NULL) THEN
        RAISE EXCEPTION 'Generated tickets lack expected variety';
    END IF;

    RAISE NOTICE 'Generated data checks passed';
END;
$test$;

SELECT 'staff' AS table_name, count(*) AS row_count FROM public.staff
UNION ALL SELECT 'assets', count(*) FROM public.assets
UNION ALL SELECT 'tickets', count(*) FROM public.tickets
UNION ALL SELECT 'ticket_updates', count(*) FROM public.ticket_updates;
