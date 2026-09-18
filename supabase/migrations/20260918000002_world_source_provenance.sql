-- Public source URL for a curated item (Wikipedia article / UNESCO list entry),
-- shown as attribution on World Features produced from it.
--
-- Only curated_items lives in this database. toons.curated_item_id is part of
-- the app's own schema, added by the idempotent ALTER list in app/main.py's
-- lifespan() — this database has no `toons` table (see README.md here).
ALTER TABLE curated_items ADD COLUMN IF NOT EXISTS source_url TEXT;
