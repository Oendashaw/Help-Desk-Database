"""Generate a repeatable PostgreSQL import file using synthetic records."""

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


STAFF_COUNT = 200
AGENT_COUNT = 20
ASSET_COUNT = 1_000
TICKET_COUNT = 50_000
SEED = 4355


def generate_data(output):
    rng = random.Random(SEED)
    writer = csv.writer(output, lineterminator="\n")
    output.write(
        "\\set ON_ERROR_STOP on\n"
        "BEGIN;\n"
        # Hold these locks through the empty-table check and the import.
        "LOCK TABLE public.staff, public.assets, public.tickets, public.ticket_updates\n"
        "    IN SHARE ROW EXCLUSIVE MODE;\n"
        "DO $check$\n"
        "BEGIN\n"
        "    IF EXISTS (SELECT 1 FROM public.staff)\n"
        "       OR EXISTS (SELECT 1 FROM public.assets)\n"
        "       OR EXISTS (SELECT 1 FROM public.tickets)\n"
        "       OR EXISTS (SELECT 1 FROM public.ticket_updates) THEN\n"
        "        RAISE EXCEPTION 'Sample data requires all four tables to be empty';\n"
        "    END IF;\n"
        "END;\n"
        "$check$;\n"
        "COPY public.staff (staff_id, full_name, email, department)\n"
        "    FROM STDIN WITH (FORMAT csv);\n"
    )
    for staff_id in range(1, STAFF_COUNT + 1):
        department = "IT" if staff_id <= AGENT_COUNT else rng.choice(
            ("Finance", "HR", "Operations", "Sales")
        )
        writer.writerow(
            (staff_id, f"Staff {staff_id:04d}", f"staff{staff_id:04d}@example.invalid", department)
        )
    output.write("\\.\n")

    output.write(
        "COPY public.assets (asset_id, asset_tag, asset_type, assigned_to)\n"
        "    FROM STDIN WITH (FORMAT csv);\n"
    )
    asset_owners = []
    for asset_id in range(1, ASSET_COUNT + 1):
        owner = rng.randint(AGENT_COUNT + 1, STAFF_COUNT) if rng.random() < 0.9 else None
        asset_owners.append(owner)
        asset_type = rng.choices(("laptop", "desktop", "printer"), weights=(70, 25, 5))[0]
        writer.writerow((asset_id, f"ASSET-{asset_id:05d}", asset_type, owner))
    output.write("\\.\n")

    output.write(
        "COPY public.tickets (ticket_id, reported_by, assigned_to, asset_id,\n"
        "    subject, description, status, priority, created_at)\n"
        "    FROM STDIN WITH (FORMAT csv);\n"
    )
    topics = (
        "Cannot connect to Wi-Fi",
        "Printer won't respond",
        "Application freezes, then closes",
        'Access to "shared" folder denied',
        "Password reset needed",
        "Device runs slowly",
        "Software installation requested",
    )
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    updates = []
    for ticket_id in range(1, TICKET_COUNT + 1):
        asset_id = rng.randint(1, ASSET_COUNT) if rng.random() < 0.85 else None
        owner = asset_owners[asset_id - 1] if asset_id is not None else None
        reporter = owner if owner is not None else rng.randint(AGENT_COUNT + 1, STAFF_COUNT)
        status = rng.choices(
            ("open", "in_progress", "resolved", "closed"), weights=(15, 20, 20, 45)
        )[0]
        agent = None if status == "open" and rng.random() < 0.5 else rng.randint(1, AGENT_COUNT)
        priority = rng.choices(("low", "medium", "high", "urgent"), weights=(35, 45, 15, 5))[0]
        topic = rng.choice(topics)
        created_at = start_date + timedelta(minutes=rng.randrange(300 * 24 * 60))
        writer.writerow(
            (
                ticket_id, reporter, agent, asset_id, f"{topic} #{ticket_id}",
                f"Synthetic support request {ticket_id}. {topic}.",
                status, priority, created_at.isoformat(),
            )
        )
        for update_number in range(1, rng.randint(1, 3) + 1):
            updates.append(
                (
                    len(updates) + 1, ticket_id, agent or rng.randint(1, AGENT_COUNT),
                    f"Synthetic update {update_number} for ticket {ticket_id}",
                    (created_at + timedelta(hours=update_number)).isoformat(),
                )
            )
    output.write("\\.\n")

    output.write(
        "COPY public.ticket_updates (update_id, ticket_id, author_id, update_text, created_at)\n"
        "    FROM STDIN WITH (FORMAT csv);\n"
    )
    writer.writerows(updates)
    output.write("\\.\n")

    # COPY accepts explicit identity values, so advance each sequence after loading.
    for table, key in (
        ("staff", "staff_id"), ("assets", "asset_id"),
        ("tickets", "ticket_id"), ("ticket_updates", "update_id"),
    ):
        output.write(
            f"SELECT setval(pg_get_serial_sequence('public.{table}', '{key}'),\n"
            f"    (SELECT MAX({key}) FROM public.{table}));\n"
            f"ANALYZE public.{table};\n"
        )
    output.write("COMMIT;\n")
    return len(updates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", nargs="?", type=Path, default=Path("sample_data/helpdesk_data.sql"),
        help="new output file (default: sample_data/helpdesk_data.sql)",
    )
    args = parser.parse_args()
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="") as output:
            update_count = generate_data(output)
    except OSError as error:
        parser.exit(1, f"Could not generate sample data: {error}\n")
    print(
        f"Created {args.output} with {STAFF_COUNT} staff, {ASSET_COUNT} assets, "
        f"{TICKET_COUNT} tickets, and {update_count} updates."
    )


if __name__ == "__main__":
    main()
