"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, Trash2, X, History, ChevronDown, ChevronUp, Sparkles, Pencil } from "lucide-react";
import type { Character, CharacterRelationship, CharacterRelationshipEvent, RelationshipDraft, CastRelationshipSuggestion } from "@/lib/types";
import { RELATIONSHIP_EVENT_TYPES, RELATIONSHIP_TYPES } from "@/lib/types";
import InfoTooltip from "@/components/ui/Tooltip";

const LEVEL_HINTS = {
  affection: "How warmly they feel toward the other. Independent of trust — bickering siblings can be low-trust, high-affection.",
  trust: "How much they rely on / believe the other. Independent of affection — you can trust a rival's word without liking them.",
  conflict: "How often they clash or disagree with the other. Can coexist with high affection (constant bickering) or low (mutual indifference).",
};

interface Props {
  brandId: string;
}

const EVENT_TYPE_LABELS: Record<(typeof RELATIONSHIP_EVENT_TYPES)[number], string> = {
  conflict: "Conflict", bonding: "Bonding", running_joke: "Running joke",
  betrayal: "Betrayal", reconciliation: "Reconciliation", milestone: "Milestone", general: "General",
};

export interface DirectionDraft {
  affection_level: number;
  trust_level: number;
  conflict_level: number;
  perspective_description: string;
  behavior_rules: string[];
}

export const EMPTY_DIRECTION: DirectionDraft = {
  affection_level: 5, trust_level: 5, conflict_level: 5, perspective_description: "", behavior_rules: [],
};

// One direction's editor — rendered twice (A->B and B->A) since
// personality toward another character isn't necessarily symmetrical.
// Exported so CharacterCreationWizard.tsx/CastPlanWizard.tsx can reuse it
// for their own relationship-draft review steps without duplicating this
// slider/rule-list markup.
export function DirectionEditor({
  title, direction, onChange, newRule, onNewRuleChange, onAddRule, onRemoveRule,
}: {
  title: string;
  direction: DirectionDraft;
  onChange: (patch: Partial<DirectionDraft>) => void;
  newRule: string;
  onNewRuleChange: (v: string) => void;
  onAddRule: () => void;
  onRemoveRule: (i: number) => void;
}) {
  return (
    <div className="rounded-xl border border-gray-100 bg-white p-3 space-y-2 flex-1 min-w-[14rem]">
      <p className="text-xs font-semibold text-gray-700">{title}</p>
      <div className="flex gap-3 flex-wrap">
        <div className="flex-1 min-w-[6rem]">
          <span className="flex items-center gap-1 text-[11px] text-gray-500">
            Affection {direction.affection_level}/10 <InfoTooltip text={LEVEL_HINTS.affection} />
          </span>
          <input type="range" min={0} max={10} value={direction.affection_level} onChange={(e) => onChange({ affection_level: parseInt(e.target.value) })} className="w-full" />
        </div>
        <div className="flex-1 min-w-[6rem]">
          <span className="flex items-center gap-1 text-[11px] text-gray-500">
            Trust {direction.trust_level}/10 <InfoTooltip text={LEVEL_HINTS.trust} />
          </span>
          <input type="range" min={0} max={10} value={direction.trust_level} onChange={(e) => onChange({ trust_level: parseInt(e.target.value) })} className="w-full" />
        </div>
        <div className="flex-1 min-w-[6rem]">
          <span className="flex items-center gap-1 text-[11px] text-gray-500">
            Conflict {direction.conflict_level}/10 <InfoTooltip text={LEVEL_HINTS.conflict} />
          </span>
          <input type="range" min={0} max={10} value={direction.conflict_level} onChange={(e) => onChange({ conflict_level: parseInt(e.target.value) })} className="w-full" />
        </div>
      </div>
      <textarea
        value={direction.perspective_description}
        onChange={(e) => onChange({ perspective_description: e.target.value })}
        placeholder={`Their perspective, e.g. "Hans takes rules too seriously."`}
        rows={2}
        className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none"
      />
      <div className="space-y-1">
        {direction.behavior_rules.map((rule, i) => (
          <div key={i} className="flex items-center gap-1.5 text-[11px] text-gray-600 bg-gray-50 rounded-lg px-2 py-1 border border-gray-100">
            <span className="flex-1">{rule}</span>
            <button type="button" onClick={() => onRemoveRule(i)} className="text-gray-400 hover:text-red-500">
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-1.5">
        <input
          type="text" value={newRule} onChange={(e) => onNewRuleChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onAddRule(); } }}
          placeholder="Behavior rule, e.g. tries to persuade the other"
          className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
        />
        <button type="button" onClick={onAddRule} className="rounded-lg bg-gray-100 text-gray-600 px-2.5 hover:bg-gray-200 transition-colors">
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// Card + form library, not a visual relationship graph — decided against a
// graph for v1, see docs/culturix-comedy-architecture.md §7 Phase 3.
// Self-fetches its own character roster (its own top-level nav tab, not
// nested inside Characters) — see docs/culturix-character-studio-
// upgrade.md §4 Phase 1. Directional refinement (docs/culturix-
// relationship-refinement.md): personality toward another character isn't
// necessarily symmetrical, so dynamics are edited per-direction, not as
// one shared set of levels.
export default function RelationshipManager({ brandId }: Props) {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [relationships, setRelationships] = useState<CharacterRelationship[]>([]);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [characterAId, setCharacterAId] = useState("");
  const [characterBId, setCharacterBId] = useState("");
  const [relationshipType, setRelationshipType] = useState("");
  const [relationshipTypeLabel, setRelationshipTypeLabel] = useState("");
  const [description, setDescription] = useState("");
  const [comedyChemistry, setComedyChemistry] = useState(5);
  const [directions, setDirections] = useState<{ a_to_b: DirectionDraft; b_to_a: DirectionDraft }>({
    a_to_b: { ...EMPTY_DIRECTION }, b_to_a: { ...EMPTY_DIRECTION },
  });
  const [newRuleAtoB, setNewRuleAtoB] = useState("");
  const [newRuleBtoA, setNewRuleBtoA] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [relationshipHint, setRelationshipHint] = useState("");

  // "Suggest relationships with cast" — for a character that wasn't part
  // of an AI-suggested cast batch (manually created, or added after
  // "Suggest a cast" already ran): drafts a relationship with every other
  // active character in one go, instead of running "Generate relationship"
  // once per castmate by hand. Cast suggestion itself never recalibrates
  // anything after the fact, so this is the explicit, opt-in way to catch
  // a character up.
  const [suggestCharacterId, setSuggestCharacterId] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<CastRelationshipSuggestion[]>([]);
  const [savingSuggestionFor, setSavingSuggestionFor] = useState<string | null>(null);
  const [savedSuggestionIds, setSavedSuggestionIds] = useState<Set<string>>(new Set());

  // History (events) — loaded lazily per relationship, not eagerly for
  // every relationship on mount.
  const [historyOpen, setHistoryOpen] = useState<Record<string, boolean>>({});
  const [eventsByRelationship, setEventsByRelationship] = useState<Record<string, CharacterRelationshipEvent[]>>({});
  const [eventsLoading, setEventsLoading] = useState<Record<string, boolean>>({});
  const [newEventType, setNewEventType] = useState<Record<string, string>>({});
  const [newEventDescription, setNewEventDescription] = useState<Record<string, string>>({});
  const [newEventAffectionDelta, setNewEventAffectionDelta] = useState<Record<string, number>>({});
  const [newEventTrustDelta, setNewEventTrustDelta] = useState<Record<string, number>>({});
  const [newEventConflictDelta, setNewEventConflictDelta] = useState<Record<string, number>>({});
  const [addingEvent, setAddingEvent] = useState<string | null>(null);
  const [eventError, setEventError] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetch(`/api/culturetoons/characters?brand_id=${brandId}&active_only=true`, { cache: "no-store" })
        .then((res) => (res.ok ? res.json() : [])),
      fetch(`/api/culturetoons/relationships?brand_id=${brandId}`, { cache: "no-store" })
        .then((res) => (res.ok ? res.json() : [])),
    ]).then(([chars, rels]) => {
      if (cancelled) return;
      setCharacters(chars);
      setRelationships(rels);
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [brandId]);

  function characterName(id: string) {
    return characters.find((c) => c.id === id)?.name ?? "Unknown";
  }

  function openNew() {
    setEditingId(null);
    setCharacterAId(""); setCharacterBId("");
    setRelationshipType(""); setRelationshipTypeLabel("");
    setDescription(""); setComedyChemistry(5);
    setDirections({ a_to_b: { ...EMPTY_DIRECTION }, b_to_a: { ...EMPTY_DIRECTION } });
    setError(null); setGenerateError(null); setRelationshipHint("");
    setFormOpen(true);
  }

  function openEdit(r: CharacterRelationship) {
    setEditingId(r.id);
    setCharacterAId(r.character_a_id); setCharacterBId(r.character_b_id);
    setRelationshipType(r.relationship_type ?? "");
    setRelationshipTypeLabel(r.relationship_type_label ?? "");
    setDescription(r.description ?? "");
    setComedyChemistry(r.comedy_chemistry ?? 5);
    const aToB = r.directions.find((d) => d.from_character_id === r.character_a_id);
    const bToA = r.directions.find((d) => d.from_character_id === r.character_b_id);
    const toDraft = (d: typeof aToB): DirectionDraft => d ? {
      affection_level: d.affection_level ?? 5, trust_level: d.trust_level ?? 5, conflict_level: d.conflict_level ?? 5,
      perspective_description: d.perspective_description ?? "", behavior_rules: d.behavior_rules,
    } : { ...EMPTY_DIRECTION };
    setDirections({ a_to_b: toDraft(aToB), b_to_a: toDraft(bToA) });
    setError(null); setGenerateError(null); setRelationshipHint("");
    setFormOpen(true);
    if (!eventsByRelationship[r.id]) loadEvents(r.id);
    setHistoryOpen((prev) => ({ ...prev, [r.id]: true }));
  }

  function closeForm() {
    setFormOpen(false);
    setEditingId(null);
  }

  function updateDirection(which: "a_to_b" | "b_to_a", patch: Partial<DirectionDraft>) {
    setDirections((prev) => ({ ...prev, [which]: { ...prev[which], ...patch } }));
  }

  async function generateDraft() {
    if (!characterAId || !characterBId || characterAId === characterBId) {
      setGenerateError("Pick two different characters first.");
      return;
    }
    setGenerating(true);
    setGenerateError(null);
    try {
      const res = await fetch("/api/culturetoons/relationships/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId, character_a_id: characterAId, character_b_id: characterBId,
          hint: relationshipHint.trim() || undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setGenerateError(typeof data.detail === "string" ? data.detail : "Generation failed");
        return;
      }
      // Populates the form only — nothing is saved until "Save relationship"
      // is clicked, so a generated draft never silently overwrites
      // existing data.
      const draft = data as RelationshipDraft;
      setRelationshipType(draft.relationship_type);
      setRelationshipTypeLabel(draft.relationship_type_label);
      setDescription(draft.description ?? "");
      setComedyChemistry(draft.comedy_chemistry);
      setDirections({
        a_to_b: {
          affection_level: draft.a_to_b.affection_level, trust_level: draft.a_to_b.trust_level,
          conflict_level: draft.a_to_b.conflict_level, perspective_description: draft.a_to_b.perspective_description ?? "",
          behavior_rules: draft.a_to_b.behavior_rules,
        },
        b_to_a: {
          affection_level: draft.b_to_a.affection_level, trust_level: draft.b_to_a.trust_level,
          conflict_level: draft.b_to_a.conflict_level, perspective_description: draft.b_to_a.perspective_description ?? "",
          behavior_rules: draft.b_to_a.behavior_rules,
        },
      });
    } finally {
      setGenerating(false);
    }
  }

  async function suggestWithCast() {
    if (!suggestCharacterId) {
      setSuggestError("Pick a character first.");
      return;
    }
    setSuggesting(true);
    setSuggestError(null);
    setSuggestions([]);
    setSavedSuggestionIds(new Set());
    try {
      const res = await fetch(`/api/culturetoons/characters/${suggestCharacterId}/relationships/suggest-with-cast`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setSuggestError(typeof data.detail === "string" ? data.detail : "Suggestion failed");
        return;
      }
      const list = data as CastRelationshipSuggestion[];
      if (list.length === 0) setSuggestError("No other active characters to suggest relationships with yet.");
      setSuggestions(list);
    } finally {
      setSuggesting(false);
    }
  }

  async function saveSuggestion(s: CastRelationshipSuggestion) {
    if ("error" in s) return;
    setSavingSuggestionFor(s.character_b_id);
    try {
      const res = await fetch("/api/culturetoons/relationships", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          character_a_id: s.character_a_id,
          character_b_id: s.character_b_id,
          relationship_type: s.relationship_type,
          relationship_type_label: s.relationship_type === "custom" ? s.relationship_type_label : undefined,
          description: s.description ?? undefined,
          comedy_chemistry: s.comedy_chemistry,
          a_to_b: s.a_to_b,
          b_to_a: s.b_to_a,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setSuggestError(typeof data.detail === "string" ? data.detail : "Failed to save relationship");
        return;
      }
      setRelationships((prev) => [...prev, data]);
      setSavedSuggestionIds((prev) => new Set(prev).add(s.character_b_id));
    } finally {
      setSavingSuggestionFor(null);
    }
  }

  async function saveRelationship() {
    if (!characterAId || !characterBId || characterAId === characterBId) {
      setError("Pick two different characters.");
      return;
    }
    if (relationshipType === "custom" && !relationshipTypeLabel.trim()) {
      setError("Enter a label for the custom relationship type.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const directionPayload = (d: DirectionDraft) => ({
        affection_level: d.affection_level, trust_level: d.trust_level, conflict_level: d.conflict_level,
        perspective_description: d.perspective_description.trim() || undefined,
        behavior_rules: d.behavior_rules,
      });
      const body: Record<string, unknown> = {
        brand_id: brandId,
        relationship_type: relationshipType || undefined,
        relationship_type_label: relationshipType === "custom" ? relationshipTypeLabel.trim() : undefined,
        description: description.trim() || undefined,
        comedy_chemistry: comedyChemistry,
        a_to_b: directionPayload(directions.a_to_b),
        b_to_a: directionPayload(directions.b_to_a),
      };
      let res: Response;
      if (editingId) {
        res = await fetch(`/api/culturetoons/relationships/${editingId}`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
      } else {
        body.character_a_id = characterAId;
        body.character_b_id = characterBId;
        res = await fetch("/api/culturetoons/relationships", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Failed to save relationship");
        return;
      }
      setRelationships((prev) => (
        prev.some((r) => r.id === data.id) ? prev.map((r) => (r.id === data.id ? data : r)) : [...prev, data]
      ));
      closeForm();
    } finally {
      setSaving(false);
    }
  }

  async function archiveRelationship(id: string) {
    setRelationships((prev) => prev.filter((r) => r.id !== id));
    if (editingId === id) closeForm();
    await fetch(`/api/culturetoons/relationships/${id}?brand_id=${brandId}`, { method: "DELETE" });
  }

  async function loadEvents(relationshipId: string) {
    setEventsLoading((prev) => ({ ...prev, [relationshipId]: true }));
    try {
      const res = await fetch(`/api/culturetoons/relationships/${relationshipId}/events?brand_id=${brandId}`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setEventsByRelationship((prev) => ({ ...prev, [relationshipId]: data }));
      }
    } finally {
      setEventsLoading((prev) => ({ ...prev, [relationshipId]: false }));
    }
  }

  function toggleHistory(relationshipId: string) {
    const opening = !historyOpen[relationshipId];
    setHistoryOpen((prev) => ({ ...prev, [relationshipId]: opening }));
    if (opening && !eventsByRelationship[relationshipId]) loadEvents(relationshipId);
  }

  async function addEvent(relationshipId: string) {
    const eventType = newEventType[relationshipId] || "general";
    const description = (newEventDescription[relationshipId] ?? "").trim();
    if (!description) return;
    setAddingEvent(relationshipId);
    setEventError((prev) => ({ ...prev, [relationshipId]: "" }));
    try {
      const res = await fetch(`/api/culturetoons/relationships/${relationshipId}/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId, event_type: eventType, description,
          affection_delta: newEventAffectionDelta[relationshipId] || undefined,
          trust_delta: newEventTrustDelta[relationshipId] || undefined,
          conflict_delta: newEventConflictDelta[relationshipId] || undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setEventError((prev) => ({ ...prev, [relationshipId]: typeof data.detail === "string" ? data.detail : "Couldn't add event" }));
        return;
      }
      setEventsByRelationship((prev) => ({ ...prev, [relationshipId]: [data, ...(prev[relationshipId] ?? [])] }));
      setNewEventDescription((prev) => ({ ...prev, [relationshipId]: "" }));
      setNewEventAffectionDelta((prev) => ({ ...prev, [relationshipId]: 0 }));
      setNewEventTrustDelta((prev) => ({ ...prev, [relationshipId]: 0 }));
      setNewEventConflictDelta((prev) => ({ ...prev, [relationshipId]: 0 }));
      // Deltas (if any) shifted the relationship's own legacy current-state
      // levels server-side — refetch the relationship list so those stay
      // in sync with what was just applied, instead of drifting stale.
      const relRes = await fetch(`/api/culturetoons/relationships?brand_id=${brandId}`, { cache: "no-store" });
      if (relRes.ok) setRelationships(await relRes.json());
    } finally {
      setAddingEvent(null);
    }
  }

  async function deleteEvent(relationshipId: string, eventId: string) {
    setEventsByRelationship((prev) => ({
      ...prev, [relationshipId]: (prev[relationshipId] ?? []).filter((e) => e.id !== eventId),
    }));
    await fetch(`/api/culturetoons/relationship-events/${eventId}?brand_id=${brandId}`, { method: "DELETE" });
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Relationships</h3>
        <p className="text-xs text-gray-400">
          Persistent dynamics between two characters (e.g. &quot;friendly rivalry&quot;) — different from
          Variants (the same character recast in a different culture, managed on the Characters tab).
          Each character&apos;s feelings/behavior toward the other are tracked independently (not assumed
          symmetrical) and automatically injected into script generation whenever both characters are cast
          together.
        </p>
      </div>

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : characters.length < 2 ? (
        <p className="text-xs text-gray-400">Add at least two characters first (Characters tab) before creating a relationship.</p>
      ) : (
        <>
          <div className="rounded-2xl bg-white border border-gray-100 p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-semibold text-gray-700">
                {relationships.length > 0 ? `${relationships.length} relationship${relationships.length > 1 ? "s" : ""}` : "No relationships yet"}
              </p>
              {!formOpen && (
                <button
                  onClick={openNew}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors"
                >
                  <Plus className="h-3.5 w-3.5" /> New relationship
                </button>
              )}
            </div>
            {relationships.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {relationships.map((r) => {
                  const aToB = r.directions.find((d) => d.from_character_id === r.character_a_id);
                  const bToA = r.directions.find((d) => d.from_character_id === r.character_b_id);
                  return (
                    <div
                      key={r.id}
                      onClick={() => openEdit(r)}
                      className={`rounded-xl border p-3 cursor-pointer transition-colors ${
                        editingId === r.id ? "border-blue-300 bg-blue-50" : "border-gray-100 bg-gray-50 hover:border-blue-200"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-xs font-medium text-gray-800">
                          {characterName(r.character_a_id)} ↔ {characterName(r.character_b_id)}
                        </p>
                        <button
                          onClick={(e) => { e.stopPropagation(); archiveRelationship(r.id); }}
                          className="text-gray-300 hover:text-red-500 shrink-0"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      {(r.relationship_type_label || r.relationship_type) && (
                        <p className="text-[11px] text-gray-500 mt-0.5">{r.relationship_type_label ?? r.relationship_type}</p>
                      )}
                      {aToB && bToA && (
                        <div className="mt-1.5 space-y-0.5 text-[10px] text-gray-400">
                          <div>
                            {characterName(aToB.from_character_id)}→{characterName(aToB.to_character_id)}:
                            {" "}A{aToB.affection_level ?? "—"} T{aToB.trust_level ?? "—"} C{aToB.conflict_level ?? "—"}
                          </div>
                          <div>
                            {characterName(bToA.from_character_id)}→{characterName(bToA.to_character_id)}:
                            {" "}A{bToA.affection_level ?? "—"} T{bToA.trust_level ?? "—"} C{bToA.conflict_level ?? "—"}
                          </div>
                        </div>
                      )}
                      <div className="flex gap-3 mt-1.5 text-[10px] text-gray-400">
                        {r.comedy_chemistry !== null && <span>Comedy chemistry {r.comedy_chemistry}/10</span>}
                        <span>{r.episodes_together} episode{r.episodes_together === 1 ? "" : "s"} together</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="rounded-2xl bg-white border border-gray-100 p-4 space-y-3">
            <div>
              <p className="text-xs font-semibold text-gray-700">Suggest relationships with cast</p>
              <p className="text-[11px] text-gray-400 mt-0.5">
                For a character that wasn&apos;t part of an AI-suggested cast batch — drafts a relationship with
                every other active character at once, instead of running &quot;Generate relationship&quot; one
                pair at a time. Nothing saves until you pick which drafts to keep.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 items-center">
              <select
                value={suggestCharacterId} onChange={(e) => setSuggestCharacterId(e.target.value)}
                className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
              >
                <option value="">Character to integrate…</option>
                {characters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <button
                type="button"
                onClick={suggestWithCast}
                disabled={suggesting || !suggestCharacterId}
                className="inline-flex items-center gap-1.5 rounded-lg border border-blue-200 text-blue-600 text-xs font-medium px-3 py-1.5 hover:bg-blue-50 transition-colors disabled:opacity-60"
              >
                {suggesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                {suggesting ? "Drafting…" : "Suggest with cast"}
              </button>
            </div>
            {suggestError && <p className="text-xs text-red-500">{suggestError}</p>}
            {suggestions.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                {suggestions.map((s) => {
                  const saved = savedSuggestionIds.has(s.character_b_id);
                  return (
                    <div key={s.character_b_id} className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                      <p className="text-xs font-medium text-gray-800">
                        {characterName(s.character_a_id)} ↔ {s.character_b_name}
                      </p>
                      {"error" in s ? (
                        <p className="text-[11px] text-red-500 mt-1">{s.error}</p>
                      ) : (
                        <>
                          <p className="text-[11px] text-gray-500 mt-0.5">{s.relationship_type_label}</p>
                          {s.description && <p className="text-[11px] text-gray-400 mt-1">{s.description}</p>}
                          <div className="flex items-center justify-between mt-2">
                            <span className="text-[10px] text-gray-400">Comedy chemistry {s.comedy_chemistry}/10</span>
                            <button
                              type="button"
                              onClick={() => saveSuggestion(s)}
                              disabled={saved || savingSuggestionFor === s.character_b_id}
                              className={`text-[11px] font-medium rounded-lg px-2.5 py-1 transition-colors ${
                                saved
                                  ? "text-green-600 bg-green-50 cursor-default"
                                  : "text-blue-600 border border-blue-200 hover:bg-blue-50 disabled:opacity-60"
                              }`}
                            >
                              {saved ? "Saved ✓" : savingSuggestionFor === s.character_b_id ? "Saving…" : "Save"}
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {formOpen && (
            <div className="rounded-2xl bg-white border border-gray-100 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-gray-700 flex items-center gap-1.5">
                  {editingId ? <><Pencil className="h-3.5 w-3.5" /> Edit relationship</> : "Add a relationship"}
                </p>
                <button onClick={closeForm} className="text-gray-400 hover:text-gray-600">
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="flex flex-wrap gap-2 items-center">
                <select
                  value={characterAId} onChange={(e) => setCharacterAId(e.target.value)}
                  disabled={!!editingId}
                  className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs disabled:opacity-60"
                >
                  <option value="">Character A</option>
                  {characters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                <select
                  value={characterBId} onChange={(e) => setCharacterBId(e.target.value)}
                  disabled={!!editingId}
                  className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs disabled:opacity-60"
                >
                  <option value="">Character B</option>
                  {characters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                <input
                  type="text"
                  value={relationshipHint}
                  onChange={(e) => setRelationshipHint(e.target.value)}
                  placeholder="Optional steer, e.g. &quot;rivals for the same promotion&quot;"
                  className="flex-1 min-w-[12rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
                />
                <button
                  type="button"
                  onClick={generateDraft}
                  disabled={generating || !characterAId || !characterBId || characterAId === characterBId}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-blue-200 text-blue-600 text-xs font-medium px-3 py-1.5 hover:bg-blue-50 transition-colors disabled:opacity-60"
                  title="Drafts a type, description, comedy chemistry, and both directions' dynamics from these two characters' existing personality/culture/speech/behavioral DNA (plus your optional steer above) — editable before saving, nothing is saved automatically."
                >
                  {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                  ✨ Generate relationship
                </button>
              </div>
              {generateError && <p className="text-[11px] text-red-500">{generateError}</p>}

              <div className="flex flex-wrap gap-2 items-center">
                <select
                  value={relationshipType}
                  onChange={(e) => setRelationshipType(e.target.value)}
                  className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
                >
                  <option value="">No type set</option>
                  {Object.entries(RELATIONSHIP_TYPES).map(([key, label]) => (
                    <option key={key} value={key}>{label}</option>
                  ))}
                </select>
                {relationshipType === "custom" && (
                  <input
                    type="text" value={relationshipTypeLabel} onChange={(e) => setRelationshipTypeLabel(e.target.value)}
                    placeholder="Custom type label, e.g. Frenemies"
                    className="flex-1 min-w-[8rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                  />
                )}
                <label className="flex items-center gap-1.5 text-[11px] text-gray-500">
                  Comedy chemistry {comedyChemistry}/10
                  <InfoTooltip text="How naturally this pair generates funny interactions — used later to pick high-performing character combinations for episode ideas." />
                  <input type="range" min={0} max={10} value={comedyChemistry} onChange={(e) => setComedyChemistry(parseInt(e.target.value))} className="w-20" />
                </label>
              </div>

              <textarea
                value={description} onChange={(e) => setDescription(e.target.value)}
                placeholder={`General description, e.g. "Friendly rivalry based on Kumar's improvisation versus Hans's obsession with rules."`}
                rows={2}
                className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none"
              />

              <div className="flex gap-3 flex-wrap">
                <DirectionEditor
                  title={`${characterAId ? characterName(characterAId) : "Character A"} → ${characterBId ? characterName(characterBId) : "Character B"}`}
                  direction={directions.a_to_b}
                  onChange={(patch) => updateDirection("a_to_b", patch)}
                  newRule={newRuleAtoB}
                  onNewRuleChange={setNewRuleAtoB}
                  onAddRule={() => { if (newRuleAtoB.trim()) { updateDirection("a_to_b", { behavior_rules: [...directions.a_to_b.behavior_rules, newRuleAtoB.trim()] }); setNewRuleAtoB(""); } }}
                  onRemoveRule={(i) => updateDirection("a_to_b", { behavior_rules: directions.a_to_b.behavior_rules.filter((_, idx) => idx !== i) })}
                />
                <DirectionEditor
                  title={`${characterBId ? characterName(characterBId) : "Character B"} → ${characterAId ? characterName(characterAId) : "Character A"}`}
                  direction={directions.b_to_a}
                  onChange={(patch) => updateDirection("b_to_a", patch)}
                  newRule={newRuleBtoA}
                  onNewRuleChange={setNewRuleBtoA}
                  onAddRule={() => { if (newRuleBtoA.trim()) { updateDirection("b_to_a", { behavior_rules: [...directions.b_to_a.behavior_rules, newRuleBtoA.trim()] }); setNewRuleBtoA(""); } }}
                  onRemoveRule={(i) => updateDirection("b_to_a", { behavior_rules: directions.b_to_a.behavior_rules.filter((_, idx) => idx !== i) })}
                />
              </div>

              {error && <p className="text-[11px] text-red-500">{error}</p>}
              <button
                onClick={saveRelationship}
                disabled={saving || !characterAId || !characterBId}
                className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
              >
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                {editingId ? "Save changes" : "Save relationship"}
              </button>

              {editingId && (
                <div className="pt-2 border-t border-gray-100">
                  <button
                    onClick={() => toggleHistory(editingId)}
                    className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-700"
                  >
                    <History className="h-3 w-3" />
                    History {(eventsByRelationship[editingId]?.length ?? 0) > 0 && `(${eventsByRelationship[editingId]!.length})`}
                    {historyOpen[editingId] ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  </button>

                  {historyOpen[editingId] && (
                    <div className="mt-2 space-y-2">
                      <p className="text-[10px] text-gray-400">
                        What actually happened between them, over time — the most recent few are given to
                        script generation as context, in addition to the current-state dynamic above.
                      </p>
                      {eventsLoading[editingId] && <Loader2 className="h-3 w-3 animate-spin text-gray-400" />}
                      {(eventsByRelationship[editingId] ?? []).map((ev) => (
                        <div key={ev.id} className="flex items-start gap-2 bg-gray-50 rounded-lg border border-gray-100 px-2 py-1.5">
                          <div className="flex-1">
                            <span className="text-[10px] uppercase tracking-wide text-gray-400">{EVENT_TYPE_LABELS[ev.event_type]}</span>
                            <p className="text-[11px] text-gray-600">{ev.description}</p>
                            {(ev.affection_delta || ev.trust_delta || ev.conflict_delta) && (
                              <div className="flex gap-2 mt-0.5 text-[10px] text-gray-400">
                                {!!ev.affection_delta && <span>Affection {ev.affection_delta > 0 ? "+" : ""}{ev.affection_delta}</span>}
                                {!!ev.trust_delta && <span>Trust {ev.trust_delta > 0 ? "+" : ""}{ev.trust_delta}</span>}
                                {!!ev.conflict_delta && <span>Conflict {ev.conflict_delta > 0 ? "+" : ""}{ev.conflict_delta}</span>}
                              </div>
                            )}
                          </div>
                          <button onClick={() => deleteEvent(editingId, ev.id)} className="text-gray-300 hover:text-red-500 shrink-0">
                            <X className="h-3 w-3" />
                          </button>
                        </div>
                      ))}
                      {!eventsLoading[editingId] && (eventsByRelationship[editingId] ?? []).length === 0 && (
                        <p className="text-[11px] text-gray-400">No history logged yet.</p>
                      )}

                      <div className="bg-gray-50 rounded-lg border border-dashed border-gray-200 p-2 space-y-1.5">
                        <div className="flex flex-wrap gap-1.5">
                          <select
                            value={newEventType[editingId] ?? "general"}
                            onChange={(e) => setNewEventType((prev) => ({ ...prev, [editingId]: e.target.value }))}
                            className="rounded-lg border border-gray-200 px-2 py-1 text-[11px]"
                          >
                            {RELATIONSHIP_EVENT_TYPES.map((t) => (
                              <option key={t} value={t}>{EVENT_TYPE_LABELS[t]}</option>
                            ))}
                          </select>
                          <input
                            type="text"
                            value={newEventDescription[editingId] ?? ""}
                            onChange={(e) => setNewEventDescription((prev) => ({ ...prev, [editingId]: e.target.value }))}
                            placeholder={`What happened, e.g. "Hans covered for Kumar's mistake in front of the boss"`}
                            className="flex-1 min-w-[10rem] rounded-lg border border-gray-200 px-2.5 py-1 text-[11px]"
                          />
                        </div>
                        <div className="flex items-center gap-1 text-[10px] text-gray-400">
                          Optional: nudge the relationship&apos;s current levels by this event
                          <InfoTooltip text="Applied once when you log this event, clamped to 0-10. Deleting the event later does not undo the change — it's a log, not an undo button." />
                        </div>
                        <div className="flex gap-3 flex-wrap">
                          <label className="flex items-center gap-1.5 text-[10px] text-gray-500">
                            Affection Δ
                            <input
                              type="number" min={-10} max={10}
                              value={newEventAffectionDelta[editingId] ?? 0}
                              onChange={(e) => setNewEventAffectionDelta((prev) => ({ ...prev, [editingId]: parseInt(e.target.value) || 0 }))}
                              className="w-14 rounded-lg border border-gray-200 px-1.5 py-0.5 text-[11px]"
                            />
                          </label>
                          <label className="flex items-center gap-1.5 text-[10px] text-gray-500">
                            Trust Δ
                            <input
                              type="number" min={-10} max={10}
                              value={newEventTrustDelta[editingId] ?? 0}
                              onChange={(e) => setNewEventTrustDelta((prev) => ({ ...prev, [editingId]: parseInt(e.target.value) || 0 }))}
                              className="w-14 rounded-lg border border-gray-200 px-1.5 py-0.5 text-[11px]"
                            />
                          </label>
                          <label className="flex items-center gap-1.5 text-[10px] text-gray-500">
                            Conflict Δ
                            <input
                              type="number" min={-10} max={10}
                              value={newEventConflictDelta[editingId] ?? 0}
                              onChange={(e) => setNewEventConflictDelta((prev) => ({ ...prev, [editingId]: parseInt(e.target.value) || 0 }))}
                              className="w-14 rounded-lg border border-gray-200 px-1.5 py-0.5 text-[11px]"
                            />
                          </label>
                          <button
                            onClick={() => addEvent(editingId)}
                            disabled={!(newEventDescription[editingId] ?? "").trim() || addingEvent === editingId}
                            className="ml-auto inline-flex items-center gap-1 rounded-lg bg-gray-900 text-white text-[11px] font-medium px-2.5 py-1 hover:bg-gray-800 transition-colors disabled:opacity-60"
                          >
                            {addingEvent === editingId ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                            Log event
                          </button>
                        </div>
                        {eventError[editingId] && <p className="text-[11px] text-red-500">{eventError[editingId]}</p>}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
