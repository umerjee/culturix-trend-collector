"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, Trash2, X, History, ChevronDown, ChevronUp } from "lucide-react";
import type { Character, CharacterRelationship, CharacterRelationshipEvent } from "@/lib/types";
import { RELATIONSHIP_EVENT_TYPES } from "@/lib/types";
import InfoTooltip from "@/components/InfoTooltip";

const LEVEL_HINTS = {
  affection: "How warmly they feel toward each other. Independent of trust — bickering siblings can be low-trust, high-affection.",
  trust: "How much they rely on / believe each other. Independent of affection — you can trust a rival's word without liking them.",
  conflict: "How often they clash or disagree. Can coexist with high affection (constant bickering) or low (mutual indifference).",
};

interface Props {
  brandId: string;
}

const EVENT_TYPE_LABELS: Record<(typeof RELATIONSHIP_EVENT_TYPES)[number], string> = {
  conflict: "Conflict", bonding: "Bonding", running_joke: "Running joke",
  betrayal: "Betrayal", reconciliation: "Reconciliation", milestone: "Milestone", general: "General",
};

// Simple list, not a graph — decided against a visual relationship graph
// for v1, see docs/culturix-comedy-architecture.md §7 Phase 3. Self-fetches
// its own character roster (rather than taking it as a prop from a parent
// tab's state) since this is now its own top-level nav tab, not nested
// inside the Characters tab — see
// docs/culturix-character-studio-upgrade.md §4 Phase 1.
export default function RelationshipManager({ brandId }: Props) {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [relationships, setRelationships] = useState<CharacterRelationship[]>([]);
  const [loading, setLoading] = useState(true);

  const [characterAId, setCharacterAId] = useState("");
  const [characterBId, setCharacterBId] = useState("");
  const [relationshipType, setRelationshipType] = useState("");
  const [description, setDescription] = useState("");
  const [conflictLevel, setConflictLevel] = useState(5);
  const [trustLevel, setTrustLevel] = useState(5);
  const [affectionLevel, setAffectionLevel] = useState(5);
  const [behavioralRules, setBehavioralRules] = useState<string[]>([]);
  const [newRule, setNewRule] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  function addRule() {
    if (!newRule.trim()) return;
    setBehavioralRules((prev) => [...prev, newRule.trim()]);
    setNewRule("");
  }

  async function createRelationship(e: React.FormEvent) {
    e.preventDefault();
    if (!characterAId || !characterBId || characterAId === characterBId) {
      setError("Pick two different characters.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const res = await fetch("/api/culturetoons/relationships", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId, character_a_id: characterAId, character_b_id: characterBId,
          relationship_type: relationshipType.trim() || undefined,
          description: description.trim() || undefined,
          conflict_level: conflictLevel, trust_level: trustLevel, affection_level: affectionLevel,
          behavioral_rules: behavioralRules.length > 0 ? behavioralRules : undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Failed to create relationship");
        return;
      }
      setRelationships((prev) => [...prev, data as CharacterRelationship]);
      setCharacterAId(""); setCharacterBId(""); setRelationshipType(""); setDescription("");
      setConflictLevel(5); setTrustLevel(5); setAffectionLevel(5); setBehavioralRules([]);
    } finally {
      setCreating(false);
    }
  }

  async function archiveRelationship(id: string) {
    setRelationships((prev) => prev.filter((r) => r.id !== id));
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
      // Deltas (if any) shifted the relationship's own current-state levels
      // server-side — refetch the relationship list so those numbers stay
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
          Automatically injected into script generation whenever both characters are cast together.
        </p>
      </div>

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : characters.length < 2 ? (
        <p className="text-xs text-gray-400">Add at least two characters first (Characters tab) before creating a relationship.</p>
      ) : (
        <>
          <div className="rounded-2xl bg-white border border-gray-100 p-4">
            <p className="text-xs font-semibold text-gray-700 mb-3">
              {relationships.length > 0 ? `${relationships.length} relationship${relationships.length > 1 ? "s" : ""}` : "No relationships yet"}
            </p>
            {relationships.length > 0 && (
              <div className="space-y-2">
                {relationships.map((r) => (
                  <div key={r.id} className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-xs font-medium text-gray-800">
                          {characterName(r.character_a_id)} ↔ {characterName(r.character_b_id)}
                          {r.relationship_type && <span className="ml-1.5 text-gray-400 font-normal">· {r.relationship_type}</span>}
                        </p>
                        {r.description && <p className="text-[11px] text-gray-500 mt-0.5">{r.description}</p>}
                        <div className="flex gap-3 mt-1 text-[10px] text-gray-400">
                          {r.affection_level !== null && <span>Affection {r.affection_level}/10</span>}
                          {r.trust_level !== null && <span>Trust {r.trust_level}/10</span>}
                          {r.conflict_level !== null && <span>Conflict {r.conflict_level}/10</span>}
                        </div>
                        {r.behavioral_rules.length > 0 && (
                          <ul className="mt-1.5 space-y-0.5">
                            {r.behavioral_rules.map((rule, i) => (
                              <li key={i} className="text-[11px] text-gray-500">· {rule}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                      <button onClick={() => archiveRelationship(r.id)} className="text-gray-300 hover:text-red-500 shrink-0">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>

                    <button
                      onClick={() => toggleHistory(r.id)}
                      className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-700 mt-2"
                    >
                      <History className="h-3 w-3" />
                      History {(eventsByRelationship[r.id]?.length ?? 0) > 0 && `(${eventsByRelationship[r.id]!.length})`}
                      {historyOpen[r.id] ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    </button>

                    {historyOpen[r.id] && (
                      <div className="mt-2 pt-2 border-t border-gray-100 space-y-2">
                        <p className="text-[10px] text-gray-400">
                          What actually happened between them, over time — the most recent few are given to
                          script generation as context, in addition to the current-state dynamic above.
                        </p>
                        {eventsLoading[r.id] && <Loader2 className="h-3 w-3 animate-spin text-gray-400" />}
                        {(eventsByRelationship[r.id] ?? []).map((ev) => (
                          <div key={ev.id} className="flex items-start gap-2 bg-white rounded-lg border border-gray-100 px-2 py-1.5">
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
                            <button onClick={() => deleteEvent(r.id, ev.id)} className="text-gray-300 hover:text-red-500 shrink-0">
                              <X className="h-3 w-3" />
                            </button>
                          </div>
                        ))}
                        {!eventsLoading[r.id] && (eventsByRelationship[r.id] ?? []).length === 0 && (
                          <p className="text-[11px] text-gray-400">No history logged yet.</p>
                        )}

                        <div className="bg-white rounded-lg border border-dashed border-gray-200 p-2 space-y-1.5">
                          <div className="flex flex-wrap gap-1.5">
                            <select
                              value={newEventType[r.id] ?? "general"}
                              onChange={(e) => setNewEventType((prev) => ({ ...prev, [r.id]: e.target.value }))}
                              className="rounded-lg border border-gray-200 px-2 py-1 text-[11px]"
                            >
                              {RELATIONSHIP_EVENT_TYPES.map((t) => (
                                <option key={t} value={t}>{EVENT_TYPE_LABELS[t]}</option>
                              ))}
                            </select>
                            <input
                              type="text"
                              value={newEventDescription[r.id] ?? ""}
                              onChange={(e) => setNewEventDescription((prev) => ({ ...prev, [r.id]: e.target.value }))}
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
                                value={newEventAffectionDelta[r.id] ?? 0}
                                onChange={(e) => setNewEventAffectionDelta((prev) => ({ ...prev, [r.id]: parseInt(e.target.value) || 0 }))}
                                className="w-14 rounded-lg border border-gray-200 px-1.5 py-0.5 text-[11px]"
                              />
                            </label>
                            <label className="flex items-center gap-1.5 text-[10px] text-gray-500">
                              Trust Δ
                              <input
                                type="number" min={-10} max={10}
                                value={newEventTrustDelta[r.id] ?? 0}
                                onChange={(e) => setNewEventTrustDelta((prev) => ({ ...prev, [r.id]: parseInt(e.target.value) || 0 }))}
                                className="w-14 rounded-lg border border-gray-200 px-1.5 py-0.5 text-[11px]"
                              />
                            </label>
                            <label className="flex items-center gap-1.5 text-[10px] text-gray-500">
                              Conflict Δ
                              <input
                                type="number" min={-10} max={10}
                                value={newEventConflictDelta[r.id] ?? 0}
                                onChange={(e) => setNewEventConflictDelta((prev) => ({ ...prev, [r.id]: parseInt(e.target.value) || 0 }))}
                                className="w-14 rounded-lg border border-gray-200 px-1.5 py-0.5 text-[11px]"
                              />
                            </label>
                            <button
                              onClick={() => addEvent(r.id)}
                              disabled={!(newEventDescription[r.id] ?? "").trim() || addingEvent === r.id}
                              className="ml-auto inline-flex items-center gap-1 rounded-lg bg-gray-900 text-white text-[11px] font-medium px-2.5 py-1 hover:bg-gray-800 transition-colors disabled:opacity-60"
                            >
                              {addingEvent === r.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                              Log event
                            </button>
                          </div>
                          {eventError[r.id] && <p className="text-[11px] text-red-500">{eventError[r.id]}</p>}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <form onSubmit={createRelationship} className="rounded-2xl bg-white border border-gray-100 p-4 space-y-2">
            <p className="text-xs font-semibold text-gray-700">Add a relationship</p>
            <div className="flex flex-wrap gap-2">
              <select value={characterAId} onChange={(e) => setCharacterAId(e.target.value)} className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs">
                <option value="">Character A</option>
                {characters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <select value={characterBId} onChange={(e) => setCharacterBId(e.target.value)} className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs">
                <option value="">Character B</option>
                {characters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <input
                type="text" value={relationshipType} onChange={(e) => setRelationshipType(e.target.value)}
                placeholder="Type, e.g. friendly_rivalry"
                className="flex-1 min-w-[8rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
              />
            </div>
            <textarea
              value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder='e.g. "Kumar finds Hans excessively rule-oriented. Hans considers Kumar unpredictable."'
              rows={2}
              className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none"
            />
            <div className="flex gap-4 flex-wrap">
              <div className="flex-1 min-w-[8rem]">
                <span className="flex items-center gap-1 text-[11px] text-gray-500">
                  Affection {affectionLevel}/10 <InfoTooltip text={LEVEL_HINTS.affection} />
                </span>
                <input type="range" min={0} max={10} value={affectionLevel} onChange={(e) => setAffectionLevel(parseInt(e.target.value))} className="w-full" />
              </div>
              <div className="flex-1 min-w-[8rem]">
                <span className="flex items-center gap-1 text-[11px] text-gray-500">
                  Trust {trustLevel}/10 <InfoTooltip text={LEVEL_HINTS.trust} />
                </span>
                <input type="range" min={0} max={10} value={trustLevel} onChange={(e) => setTrustLevel(parseInt(e.target.value))} className="w-full" />
              </div>
              <div className="flex-1 min-w-[8rem]">
                <span className="flex items-center gap-1 text-[11px] text-gray-500">
                  Conflict {conflictLevel}/10 <InfoTooltip text={LEVEL_HINTS.conflict} />
                </span>
                <input type="range" min={0} max={10} value={conflictLevel} onChange={(e) => setConflictLevel(parseInt(e.target.value))} className="w-full" />
              </div>
            </div>
            <div>
              <div className="space-y-1 mb-1.5">
                {behavioralRules.map((rule, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-[11px] text-gray-600 bg-gray-50 rounded-lg px-2 py-1 border border-gray-100">
                    <span className="flex-1">{rule}</span>
                    <button type="button" onClick={() => setBehavioralRules((prev) => prev.filter((_, idx) => idx !== i))} className="text-gray-400 hover:text-red-500">
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
              <div className="flex gap-1.5">
                <input
                  type="text" value={newRule} onChange={(e) => setNewRule(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addRule(); } }}
                  placeholder="Behavioral rule, e.g. Kumar attempts to persuade Hans"
                  className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                />
                <button type="button" onClick={addRule} className="rounded-lg bg-gray-100 text-gray-600 px-2.5 hover:bg-gray-200 transition-colors">
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
            {error && <p className="text-[11px] text-red-500">{error}</p>}
            <button
              type="submit"
              disabled={creating || !characterAId || !characterBId}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
            >
              {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
              Add relationship
            </button>
          </form>
        </>
      )}
    </div>
  );
}
