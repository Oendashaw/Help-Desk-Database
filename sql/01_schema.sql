\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE public.staff (
    staff_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name text NOT NULL CHECK (btrim(full_name) <> ''),
    email text NOT NULL UNIQUE CHECK (btrim(email) <> ''),
    department text NOT NULL CHECK (btrim(department) <> '')
);

CREATE TABLE public.assets (
    asset_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_tag text NOT NULL UNIQUE CHECK (btrim(asset_tag) <> ''),
    asset_type text NOT NULL CHECK (btrim(asset_type) <> ''),
    assigned_to integer REFERENCES public.staff (staff_id)
);

CREATE TABLE public.tickets (
    ticket_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reported_by integer NOT NULL REFERENCES public.staff (staff_id),
    assigned_to integer REFERENCES public.staff (staff_id),
    asset_id integer REFERENCES public.assets (asset_id),
    subject text NOT NULL CHECK (btrim(subject) <> ''),
    description text NOT NULL CHECK (btrim(description) <> ''),
    status text NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    priority text NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.ticket_updates (
    update_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id integer NOT NULL REFERENCES public.tickets (ticket_id),
    author_id integer NOT NULL REFERENCES public.staff (staff_id),
    update_text text NOT NULL CHECK (btrim(update_text) <> ''),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
