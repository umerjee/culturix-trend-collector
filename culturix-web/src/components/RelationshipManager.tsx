"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, Trash2, X, Users } from "lucide-react";
import type { Character, CharacterRelationship } from "@/lib/types";

interface Props {
  brandId: string;
  characters: Character[];
}

// Simple list, not a graph — decided against a visual relationship graph
// for v1, see docs/culturix-comedy-architecture.md §7 Phase 3.
export default function RelationshipManager({ brandId, characters }: Props) {
  const [relationships, setRelationships] = useState<CharacterRelationship[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);

  const [characterAId, setCharacterAId] = useState("");
  const [characterBId, setCharacterBId] = useState("");
  const [relationshipType, setRelationshipType] = useState("");
  const [description, setDescription] = useState("");
  const [conflictLevel, setConflictLevel] = useState(5);
  const [trustLevel, setTrustLevel] = useState(5);
  const [behavioralRules, setBehavioralRules] = useState<string[]>([]);
  const [newRule, setNewRule] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(`/api/culturetoons/relationships?brand_id=${brandId}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => { if (!cancelled) setRelationships(data); })
      .finally(() => { if (!cancelled) setLoading(false); });
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
          conflict_level: conflictLevel, trust_level: trustLevel,
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
      setConflictLevel(5); setTrustLevel(5); setBehavioralRules([]);
    } finally {
      setCreating(false);
    }
  }

  async function archiveRelationship(id: string) {
    setRelationships((prev) => prev.filter((r) => r.id !== id));
    await fetch(`/api/culturetoons/relationships/${id}?brand_id=${brandId}`, { method: "DELETE" });
  }

  if (characters.length < 2) return null;

  return (
    <div className="rounded-2xl bg-white border border-gray-100 p-4">
      <button onClick={() => setOpen((v) => !v)} className="w-full flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Users className="h-4 w-4 text-gray-400" /> Relationships
        </h3>
        {relationships.length > 0 && <span className="text-xs text-gray-400">{relationships.length}</span>}
      </button>
      {open && (
        <div className="mt-3 space-y-4">
          <p className="text-xs text-gray-400">
            Persistent dynamics between two characters (e.g. &quot;friendly rivalry&quot;) — automatically
            injected into script generation whenever both are cast in the same scene.
          </p>

          {loading ? (
            <p className="text-xs text-gray-400">Loading…</p>
          ) : relationships.length === 0 ? (
            <p className="text-xs text-gray-400">No relationships yet.</p>
          ) : (
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
                        {r.conflict_level !== null && <span>Conflict {r.conflict_level}/10</span>}
                        {r.trust_level !== null && <span>Trust {r.trust_level}/10</span>}
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
                </div>
              ))}
            </div>
          )}

          <form onSubmit={createRelationship} className="rounded-xl border border-gray-100 bg-gray-50 p-3 space-y-2">
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
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-[11px] text-gray-500 flex-1">
                Conflict {conflictLevel}/10
                <input type="range" min={0} max={10} value={conflictLevel} onChange={(e) => setConflictLevel(parseInt(e.target.value))} className="flex-1" />
              </label>
              <label className="flex items-center gap-2 text-[11px] text-gray-500 flex-1">
                Trust {trustLevel}/10
                <input type="range" min={0} max={10} value={trustLevel} onChange={(e) => setTrustLevel(parseInt(e.target.value))} className="flex-1" />
              </label>
            </div>
            <div>
              <div className="space-y-1 mb-1.5">
                {behavioralRules.map((rule, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-[11px] text-gray-600 bg-white rounded-lg px-2 py-1 border border-gray-100">
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
        </div>
      )}
    </div>
  );
}
