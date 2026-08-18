"use client";

import { useState } from "react";
import { Sparkles, Loader2, X, Check } from "lucide-react";
import type { Character, CharacterVariant } from "@/lib/types";
import { RELATIONSHIP_TYPES } from "@/lib/types";
import PersonalityFieldsEditor from "@/components/PersonalityFieldsEditor";
import { DirectionEditor, type DirectionDraft } from "@/components/RelationshipManager";

interface Props {
  brandId: string;
  characters: Character[];
  onCreated: (newCharacters: Character[], newVariants: CharacterVariant[]) => void;
}

interface DraftPersonality {
  traits: Record<string, number>;
  behavioral_rules: string[];
  speech_rules: string[];
}

interface DraftCharacter {
  name: string;
  description: string;
  suggested_main: boolean;
  included: boolean;
  personality: DraftPersonality;
}

interface DraftRelationship {
  character_a_index: number;
  character_b_index: number;
  relationship_type: string;
  relationship_type_label: string;
  description: string;
  comedy_chemistry: number;
  a_to_b: DirectionDraft;
  b_to_a: DirectionDraft;
  included: boolean;
}

function toDirectionDraft(d: { affection_level: number; trust_level: number; conflict_level: number; perspective_description: string | null; behavior_rules: string[] }): DirectionDraft {
  return {
    affection_level: d.affection_level, trust_level: d.trust_level, conflict_level: d.conflict_level,
    perspective_description: d.perspective_description ?? "", behavior_rules: d.behavior_rules,
  };
}

function directionPayload(d: DirectionDraft) {
  return {
    affection_level: d.affection_level, trust_level: d.trust_level, conflict_level: d.conflict_level,
    perspective_description: d.perspective_description.trim() || undefined,
    behavior_rules: d.behavior_rules,
  };
}

// "Describe your whole show at once" — the batch alternative to
// CharacterCreationWizard.tsx's one-character-at-a-time flow. One AI call
// suggests a cohesive cast plus the relationships between them (see
// app/services/culturetoon_cast.py for why a cast is generated together
// rather than pairwise), the user edits/excludes anything before a single
// "Create cast" action persists everything via the same existing
// characters/personality/relationships endpoints the rest of this product
// already uses.
export default function CastPlanWizard({ brandId, characters, onCreated }: Props) {
  const brandHasNoCharacters = characters.length === 0;

  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<"describe" | "review">("describe");
  const [planDescription, setPlanDescription] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [draftCharacters, setDraftCharacters] = useState<DraftCharacter[]>([]);
  const [draftRelationships, setDraftRelationships] = useState<DraftRelationship[]>([]);
  const [newRuleDrafts, setNewRuleDrafts] = useState<Record<string, string>>({});

  function close() {
    setOpen(false);
    setStep("describe"); setPlanDescription(""); setError(null);
    setDraftCharacters([]); setDraftRelationships([]); setNewRuleDrafts({});
  }

  async function generateCast() {
    if (!planDescription.trim()) return;
    setGenerating(true);
    setError(null);
    try {
      const res = await fetch(`/api/culturetoons/brands/${brandId}/cast/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_description: planDescription.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Cast generation failed");
        return;
      }
      setDraftCharacters(
        (data.characters ?? []).map((c: { name: string; description: string; suggested_main: boolean; personality: DraftPersonality }) => ({
          name: c.name, description: c.description,
          suggested_main: brandHasNoCharacters && c.suggested_main,
          included: true,
          personality: c.personality,
        }))
      );
      setDraftRelationships(
        (data.relationships ?? []).map((r: {
          character_a_index: number; character_b_index: number; relationship_type: string; relationship_type_label: string;
          description: string | null; comedy_chemistry: number;
          a_to_b: DirectionDraft; b_to_a: DirectionDraft;
        }) => ({
          character_a_index: r.character_a_index, character_b_index: r.character_b_index,
          relationship_type: r.relationship_type, relationship_type_label: r.relationship_type_label,
          description: r.description ?? "", comedy_chemistry: r.comedy_chemistry,
          a_to_b: toDirectionDraft(r.a_to_b), b_to_a: toDirectionDraft(r.b_to_a),
          included: true,
        }))
      );
      setStep("review");
    } finally {
      setGenerating(false);
    }
  }

  function updateCharacter(index: number, patch: Partial<DraftCharacter>) {
    setDraftCharacters((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }

  function makeTraitsSetter(index: number): React.Dispatch<React.SetStateAction<Record<string, number>>> {
    return (update) => setDraftCharacters((prev) => prev.map((c, i) => {
      if (i !== index) return c;
      const next = typeof update === "function" ? (update as (p: Record<string, number>) => Record<string, number>)(c.personality.traits) : update;
      return { ...c, personality: { ...c.personality, traits: next } };
    }));
  }

  function makeRulesSetter(index: number, key: "behavioral_rules" | "speech_rules"): React.Dispatch<React.SetStateAction<string[]>> {
    return (update) => setDraftCharacters((prev) => prev.map((c, i) => {
      if (i !== index) return c;
      const next = typeof update === "function" ? (update as (p: string[]) => string[])(c.personality[key]) : update;
      return { ...c, personality: { ...c.personality, [key]: next } };
    }));
  }

  function updateRelationship(index: number, patch: Partial<DraftRelationship>) {
    setDraftRelationships((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  function updateRelationshipDirection(index: number, which: "a_to_b" | "b_to_a", patch: Partial<DirectionDraft>) {
    setDraftRelationships((prev) => prev.map((r, i) => (i === index ? { ...r, [which]: { ...r[which], ...patch } } : r)));
  }

  async function createCast() {
    setCreating(true);
    setError(null);
    try {
      const includedIndices = draftCharacters
        .map((c, i) => (c.included ? i : -1))
        .filter((i) => i !== -1);
      if (brandHasNoCharacters) {
        // The brand's first created character auto-becomes main
        // server-side (create_character) — order the suggested main
        // first so that logic lands on the right one.
        includedIndices.sort((a, b) => (draftCharacters[b].suggested_main ? 1 : 0) - (draftCharacters[a].suggested_main ? 1 : 0));
      }

      const indexToReal = new Map<number, { character: Character; variant: CharacterVariant | null }>();
      for (const index of includedIndices) {
        const draft = draftCharacters[index];
        const res = await fetch("/api/culturetoons/characters", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brand_id: brandId, name: draft.name.trim(), description: draft.description.trim() || undefined }),
        });
        if (!res.ok) continue;
        const data = await res.json();
        const { default_variant, ...character } = data;
        indexToReal.set(index, { character: character as Character, variant: (default_variant ?? null) as CharacterVariant | null });

        await fetch(`/api/culturetoons/characters/${character.id}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brand_id: brandId, personality: draft.personality }),
        });
      }

      for (const rel of draftRelationships) {
        if (!rel.included) continue;
        const a = indexToReal.get(rel.character_a_index);
        const b = indexToReal.get(rel.character_b_index);
        if (!a || !b) continue;
        await fetch("/api/culturetoons/relationships", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            brand_id: brandId, character_a_id: a.character.id, character_b_id: b.character.id,
            relationship_type: rel.relationship_type || undefined,
            relationship_type_label: rel.relationship_type === "custom" ? rel.relationship_type_label.trim() : undefined,
            description: rel.description.trim() || undefined,
            comedy_chemistry: rel.comedy_chemistry,
            a_to_b: directionPayload(rel.a_to_b), b_to_a: directionPayload(rel.b_to_a),
          }),
        });
      }

      const createdCharacters = includedIndices.map((i) => indexToReal.get(i)?.character).filter(Boolean) as Character[];
      const createdVariants = includedIndices.map((i) => indexToReal.get(i)?.variant).filter(Boolean) as CharacterVariant[];
      onCreated(createdCharacters, createdVariants);
      close();
    } finally {
      setCreating(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-full border border-blue-200 text-blue-600 text-xs font-medium px-3 py-1.5 hover:bg-blue-50 transition-colors"
      >
        <Sparkles className="h-3.5 w-3.5" /> Describe your show
      </button>
    );
  }

  return (
    <div className="w-full rounded-2xl bg-white border border-gray-100 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-gray-700">Describe your show</p>
        <button onClick={close} className="text-gray-400 hover:text-gray-600">
          <X className="h-4 w-4" />
        </button>
      </div>

      {step === "describe" && (
        <div className="space-y-2">
          <textarea
            value={planDescription}
            onChange={(e) => setPlanDescription(e.target.value)}
            placeholder={`What's this account about? Describe the setting, the cast, the vibe. E.g. "A sitcom about a Nigerian family running a restaurant in London — strict dad, easygoing mom, two kids embarrassed by them both."`}
            rows={4}
            className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          {error && <p className="text-[11px] text-red-500">{error}</p>}
          <button
            onClick={generateCast}
            disabled={generating || !planDescription.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
          >
            {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            Suggest a cast
          </button>
        </div>
      )}

      {step === "review" && (
        <div className="space-y-4">
          <p className="text-[11px] text-gray-400">
            Review the suggested cast below — edit anything, uncheck what you don&apos;t want, then create.
          </p>
          {error && <p className="text-[11px] text-red-500">{error}</p>}

          {draftCharacters.map((c, index) => (
            <div key={index} className="rounded-xl border border-gray-100 p-3 space-y-2">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox" checked={c.included}
                  onChange={(e) => updateCharacter(index, { included: e.target.checked })}
                />
                <input
                  type="text" value={c.name} onChange={(e) => updateCharacter(index, { name: e.target.value })}
                  className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-medium"
                />
                {c.suggested_main && (
                  <span className="text-[10px] uppercase tracking-wide text-amber-600 bg-amber-50 rounded-full px-2 py-0.5 shrink-0">Main</span>
                )}
              </div>
              <textarea
                value={c.description} onChange={(e) => updateCharacter(index, { description: e.target.value })}
                rows={2}
                className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none"
              />
              {c.included && (
                <div className="space-y-3 pt-1">
                  <PersonalityFieldsEditor
                    traits={c.personality.traits} onTraitsChange={makeTraitsSetter(index)}
                    behavioralRules={c.personality.behavioral_rules} onBehavioralRulesChange={makeRulesSetter(index, "behavioral_rules")}
                    speechRules={c.personality.speech_rules} onSpeechRulesChange={makeRulesSetter(index, "speech_rules")}
                  />
                </div>
              )}
            </div>
          ))}

          {draftRelationships.map((rel, index) => {
            const a = draftCharacters[rel.character_a_index];
            const b = draftCharacters[rel.character_b_index];
            if (!a || !b || !a.included || !b.included) return null;
            const aKey = `${index}-a`, bKey = `${index}-b`;
            return (
              <div key={index} className="rounded-xl border border-gray-100 p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox" checked={rel.included}
                    onChange={(e) => updateRelationship(index, { included: e.target.checked })}
                  />
                  <p className="text-xs font-semibold text-gray-700">{a.name} & {b.name}</p>
                </div>
                {rel.included && (
                  <>
                    <div className="flex flex-wrap gap-2 items-center">
                      <select
                        value={rel.relationship_type}
                        onChange={(e) => updateRelationship(index, { relationship_type: e.target.value })}
                        className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
                      >
                        <option value="">No type set</option>
                        {Object.entries(RELATIONSHIP_TYPES).map(([key, label]) => (
                          <option key={key} value={key}>{label}</option>
                        ))}
                      </select>
                      {rel.relationship_type === "custom" && (
                        <input
                          type="text" value={rel.relationship_type_label}
                          onChange={(e) => updateRelationship(index, { relationship_type_label: e.target.value })}
                          placeholder="Custom type label"
                          className="flex-1 min-w-[8rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                        />
                      )}
                      <label className="flex items-center gap-1.5 text-[11px] text-gray-500">
                        Comedy chemistry {rel.comedy_chemistry}/10
                        <input
                          type="range" min={0} max={10} value={rel.comedy_chemistry}
                          onChange={(e) => updateRelationship(index, { comedy_chemistry: parseInt(e.target.value) })}
                          className="w-20"
                        />
                      </label>
                    </div>
                    <textarea
                      value={rel.description} onChange={(e) => updateRelationship(index, { description: e.target.value })}
                      rows={2}
                      className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none"
                    />
                    <div className="flex gap-3 flex-wrap">
                      <DirectionEditor
                        title={`${a.name} → ${b.name}`}
                        direction={rel.a_to_b}
                        onChange={(patch) => updateRelationshipDirection(index, "a_to_b", patch)}
                        newRule={newRuleDrafts[aKey] ?? ""}
                        onNewRuleChange={(v) => setNewRuleDrafts((prev) => ({ ...prev, [aKey]: v }))}
                        onAddRule={() => {
                          const v = (newRuleDrafts[aKey] ?? "").trim();
                          if (!v) return;
                          updateRelationshipDirection(index, "a_to_b", { behavior_rules: [...rel.a_to_b.behavior_rules, v] });
                          setNewRuleDrafts((prev) => ({ ...prev, [aKey]: "" }));
                        }}
                        onRemoveRule={(i) => updateRelationshipDirection(index, "a_to_b", { behavior_rules: rel.a_to_b.behavior_rules.filter((_, idx) => idx !== i) })}
                      />
                      <DirectionEditor
                        title={`${b.name} → ${a.name}`}
                        direction={rel.b_to_a}
                        onChange={(patch) => updateRelationshipDirection(index, "b_to_a", patch)}
                        newRule={newRuleDrafts[bKey] ?? ""}
                        onNewRuleChange={(v) => setNewRuleDrafts((prev) => ({ ...prev, [bKey]: v }))}
                        onAddRule={() => {
                          const v = (newRuleDrafts[bKey] ?? "").trim();
                          if (!v) return;
                          updateRelationshipDirection(index, "b_to_a", { behavior_rules: [...rel.b_to_a.behavior_rules, v] });
                          setNewRuleDrafts((prev) => ({ ...prev, [bKey]: "" }));
                        }}
                        onRemoveRule={(i) => updateRelationshipDirection(index, "b_to_a", { behavior_rules: rel.b_to_a.behavior_rules.filter((_, idx) => idx !== i) })}
                      />
                    </div>
                  </>
                )}
              </div>
            );
          })}

          <button
            onClick={createCast}
            disabled={creating || draftCharacters.every((c) => !c.included)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
          >
            {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            Create cast
          </button>
        </div>
      )}
    </div>
  );
}
