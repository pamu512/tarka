-- Expand: claim tracking for tarka_outbox crash reclaim.
-- PROCESSING rows orphaned by worker death are re-admitted by
-- fetch_pending_tasks once claimed_at is older than OUTBOX_RECLAIM_SECONDS.

-- UP
ALTER TABLE tarka_outbox
    ADD COLUMN claimed_at TIMESTAMPTZ NULL;

-- DOWN
ALTER TABLE tarka_outbox
    DROP COLUMN claimed_at;
