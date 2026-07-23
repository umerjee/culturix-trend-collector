"""Canonical target-region catalog — single source of truth for both the
backend region filter (app/pipeline/nodes/persona_mapper.py) and the
frontend Settings/Onboarding region picker (served via GET /regions,
fetched by culturix-web/src/components/RegionChips.tsx).

Previously these were two independently-maintained lists — a private dict
here, a hardcoded TS array in culturix-web/src/lib/types.ts — that could
silently drift apart. That drift is exactly what caused a France-only
profile to see zero clusters (FR was offered in the picker but Twitter, the
dominant collector, never tagged it) and what makes "CN" a permanently
broken picker option today (offered, but its only tagger — Xiaohongshu —
currently contributes zero rows). Keeping one canonical mapping that both
sides read from means adding a region here is the only place it needs to
happen, and the picker can never offer something the filter doesn't know
about (or vice versa).
"""

# Maps a profile-facing region label to the collector-level region codes
# (app/collectors/region_codes.py's canonical form) that should match it.
# "EU" is used in the broad/colloquial "Europe" sense, not the strict
# political union — GB is included despite not being an EU member post-
# Brexit. "UK" (label) vs "GB" (collector code) is a direct alias. "Global"
# maps to an empty set here but is actually handled as an unconditional
# bypass in persona_mapper.py's _filter_by_region (matches everything,
# never reaches a code comparison) — kept as an entry so it still appears
# in the served catalog for the frontend picker.
REGION_LABEL_TO_CODES: dict[str, set[str]] = {
    "US": {"US"},
    "CN": {"CN"},
    "Global": set(),
    "EU": {"FR", "GB", "ES", "IT", "PT", "DE"},
    "UK": {"GB"},
    "FR": {"FR"},
    "CA": {"CA"},
    "AU": {"AU"},
}
