-- Provenance for World Features: which curated source item produced a Toon,
-- and the public URL of that source (for attribution).
ALTER TABLE curated_items ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE toons ADD COLUMN IF NOT EXISTS curated_item_id UUID;
CREATE INDEX IF NOT EXISTS ix_toons_curated_item_id ON toons (curated_item_id);
