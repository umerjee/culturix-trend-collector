import type { CharacterPersonality } from "@/lib/types";

// Template-based, not an LLM call — this only needs to accurately restate
// the sliders/rules already set, not creative writing, so a cheap
// deterministic sentence is both simpler and more predictable than a
// round-trip generation call for something purely derived from data
// already on the page. See docs/culturix-character-studio-upgrade.md §4
// Phase 1.
const TRAIT_ADJECTIVES: Record<string, string> = {
  confidence: "confident",
  humor: "funny",
  patience: "patient",
  competitiveness: "competitive",
  warmth: "warm",
  risk_tolerance: "bold",
  formality: "formal",
  impulsiveness: "impulsive",
};

function joinWithAnd(items: string[]): string {
  if (items.length === 0) return "";
  if (items.length === 1) return items[0];
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

export function buildPersonalitySummary(name: string, personality: CharacterPersonality | null): string | null {
  if (!personality) return null;
  const traits = personality.traits ?? {};
  const rules = personality.behavioral_rules ?? [];

  const topTraits = Object.entries(traits)
    .filter(([, value]) => value >= 0.5)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)
    .map(([key]) => TRAIT_ADJECTIVES[key] ?? key.replace(/_/g, " "));

  if (topTraits.length === 0 && rules.length === 0) return null;

  let summary = "";
  if (topTraits.length > 0) {
    summary = `${name} is ${joinWithAnd(topTraits)}.`;
  }
  if (rules.length > 0) {
    const shown = rules.slice(0, 2).map((r) => r.replace(/\.$/, "").toLowerCase());
    const rulesSentence = `They tend to ${joinWithAnd(shown)}.`;
    summary = summary ? `${summary} ${rulesSentence}` : `${name}: ${rulesSentence}`;
  }
  return summary;
}
