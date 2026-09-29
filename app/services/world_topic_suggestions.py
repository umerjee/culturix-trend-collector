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
        # Added 2026-09-27: picked for the same reason as the original ten, plus a bias toward
        # subjects with real physical motion/change to film (a script-quality finding from the
        # first country-sweep batch: abstract/static subjects score far lower on the reviewer's
        # "dynamism"/"story" dimensions than a force visibly acting over time).
        "Waterspout",
        "Supercell",
        "Red tide",
        "Geyser",
        "Avalanche",
        "Sinkhole",
        "Sun dog",
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
        "Peregrine falcon",
        "Rafflesia",
        "Electric eel",
        "Great white shark",
        "Portuguese man o' war",
        "Flying fish",
        "Chameleon",
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
        "Electric vertical takeoff and landing aircraft",
        "Hyperloop",
        "Maglev",
        "Vertical farming",
        "Robotic surgery",
        "Offshore wind turbine",
    ],
    # Added 2026-09-27: genz has no route from any ingestion-pipeline category either (same
    # reason phenomenon/species needed this file to begin with). Picked for real Wikipedia
    # documentation depth AND genuine physical/visual dynamism — a real event with real motion
    # (people dumping ice water, a stadium of dancers, a phone held up walking down a street),
    # not just an app's logo — since that's what this session's own evidence shows actually
    # renders well versus a static "explain the app" subject.
    "genz": [
        "Ice Bucket Challenge",
        "Harlem Shake (meme)",
        "Pokémon Go",
        "Fortnite Battle Royale",
        "Among Us",
        "K-pop",
        "TikTok",
        "Roblox",
        "Twitch (service)",
        "Minecraft",
        "Fidget spinner",
        "Vine (service)",
    ],
}
