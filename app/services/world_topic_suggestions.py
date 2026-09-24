"""Hand-picked Wikipedia topic suggestions for the World browse categories that the
per-country "History of X" / UNESCO sweep can't reach — phenomenon and species have no
route from any ingestion-pipeline category (see WORLD_SUBJECT_CATEGORIES in
world_production.py), and tech topics are more reliably found by naming the technology
directly than by hoping a country's general history page mentions it.

Single source of truth for both scripts/ingest_topic_subjects.py (CLI batch ingestion)
and GET /admin/curated-items/suggested-topics (the admin UI's one-click "add a topic"
panel) — used to live only in the script; duplicating it there and in the API would have
let the two silently drift, the same bug class as _PEOPLE_WORDS/_CLOSEUP_OF_PEOPLE having
two independent copies of one word list (culturetoon_script.py).

Picked for real documentation depth (a thin stub makes a poor source) and range within
each category, not just the most obvious pick each time. Extend this list to get more
topics in either the script or the UI — both read from here."""

TOPIC_SUGGESTIONS: dict[str, list[str]] = {
    "phenomenon": [
        "Aurora",
        "Bioluminescence",
        "St. Elmo's Fire",
        "Volcanic lightning",
        "Bird migration",
        "Tsunami",
        "Bermuda Triangle",
        "Ball lightning",
        "Mirage",
        "Meteor shower",
    ],
    "species": [
        "Axolotl",
        "Mimic octopus",
        "Tardigrade",
        "Komodo dragon",
        "Giant sequoia",
        "Blue whale",
        "Mantis shrimp",
        "Naked mole-rat",
        "Venus flytrap",
        "Immortal jellyfish",
    ],
    "tech": [
        "CRISPR gene editing",
        "Quantum computing",
        "Fusion power",
        "Brain–computer interface",
        "3D printing",
        "Self-driving car",
        "Reusable launch vehicle",
        "Lab-grown meat",
        "Humanoid robot",
        "Solid-state battery",
    ],
}
