from typing import TypedDict, List, Optional


class PipelineState(TypedDict):
    raw_signals: List[dict]        # from trends table (translated_content)
    user_profiles: List[dict]      # from user_profiles table
    embeddings: List[List[float]]  # from Voyage AI
    clusters: List[dict]           # AI-identified cultural clusters
    persona_matches: List[dict]    # user_id -> relevant clusters + signals
    generated_content: List[dict]  # final content ideas per user
    errors: List[str]
