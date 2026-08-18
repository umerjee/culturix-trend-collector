"use client";

import { useState } from "react";
import { Plus, Loader2, Sparkles, X } from "lucide-react";
import type { Character, CharacterVariant, RelationshipDraft } from "@/lib/types";
import { RELATIONSHIP_TYPES } from "@/lib/types";
import PersonalityFieldsEditor from "@/components/PersonalityFieldsEditor";
import { DirectionEditor, EMPTY_DIRECTION, type DirectionDraft } from "@/components/RelationshipManager";

interface Props {
  brandId: string;
  characters: Character[];
  onCreated: (character: Character, defaultVariant: CharacterVariant | null) => void;
}

// Guided one-at-a-time character creation. The brand's first character is
// framed as the main character's origin story and needs no further review
// — there's no one else yet to build a relationship against. Every
// character after that also asks how it relates to the main character,
// then automatically drafts both its personality and its relationship to
// the main character for review before anything but the character itself
// is saved. See CastPlanWizard.tsx for the batch alternative ("describe
// your whole show at once").
export default function CharacterCreationWizard({ brandId, characters, onCreated }: Props) {
  const mainCharacter = characters.find((c) => c.is_main) ?? null;
  const isFirstCharacter = characters.length === 0;

  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<"describe" | "review">("describe");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [relationshipHint, setRelationshipHint] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newCharacter, setNewCharacter] = useState<Character | null>(null);
  const [newDefaultVariant, setNewDefaultVariant] = useState<CharacterVariant | null>(null);
  const [traits, setTraits] = useState<Record<string, number>>({});
  const [behavioralRules, setBehavioralRules] = useState<string[]>([]);
  const [speechRules, setSpeechRules] = useState<string[]>([]);
  const [relationshipType, setRelationshipType] = useState("");
  const [relationshipTypeLabel, setRelationshipTypeLabel] = useState("");
  const [relationshipDescription, setRelationshipDescription] = useState("");
  const [comedyChemistry, setComedyChemistry] = useState(5);
  const [directions, setDirections] = useState<{ a_to_b: DirectionDraft; b_to_a: DirectionDraft }>({
    a_to_b: { ...EMPTY_DIRECTION }, b_to_a: { ...EMPTY_DIRECTION },
  });
  const [newRuleAtoB, setNewRuleAtoB] = useState("");
  const [newRuleBtoA, setNewRuleBtoA] = useState("");
  const [saving, setSaving] = useState(false);

  function reset() {
    setStep("describe"); setName(""); setDescription(""); setRelationshipHint("");
    setError(null); setNewCharacter(null); setNewDefaultVariant(null);
    setTraits({}); setBehavioralRules([]); setSpeechRules([]);
    setRelationshipType(""); setRelationshipTypeLabel(""); setRelationshipDescription(""); setComedyChemistry(5);
    setDirections({ a_to_b: { ...EMPTY_DIRECTION }, b_to_a: { ...EMPTY_DIRECTION } });
  }

  function close() {
    setOpen(false);
    reset();
  }

  async function createAndMaybeGenerate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/culturetoons/characters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, name: name.trim(), description: description.trim() || undefined }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Failed to create character");
        return;
      }
      const { default_variant, ...character } = data;
      const createdCharacter = character as Character;
      const createdVariant = (default_variant ?? null) as CharacterVariant | null;

      if (isFirstCharacter || !mainCharacter) {
        onCreated(createdCharacter, createdVariant);
        close();
        return;
      }

      setNewCharacter(createdCharacter);
      setNewDefaultVariant(createdVariant);

      const [personalityRes, relationshipRes] = await Promise.all([
        fetch(`/api/culturetoons/characters/${createdCharacter.id}/personality/generate`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brand_id: brandId, hint: "" }),
        }),
        fetch("/api/culturetoons/relationships/generate", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            brand_id: brandId, character_a_id: mainCharacter.id, character_b_id: createdCharacter.id,
            hint: relationshipHint.trim() || undefined,
          }),
        }),
      ]);
      const [personalityData, relationshipData] = await Promise.all([
        personalityRes.json().catch(() => ({})), relationshipRes.json().catch(() => ({})),
      ]);
      if (!personalityRes.ok || !relationshipRes.ok) {
        setError(
          (typeof personalityData.detail === "string" && personalityData.detail) ||
          (typeof relationshipData.detail === "string" && relationshipData.detail) ||
          "AI suggestions failed — you can still fill these in later from the Characters/Relationships tabs."
        );
        setStep("review");
        return;
      }

      setTraits(personalityData.traits ?? {});
      setBehavioralRules(personalityData.behavioral_rules ?? []);
      setSpeechRules(personalityData.speech_rules ?? []);

      const draft = relationshipData as RelationshipDraft;
      setRelationshipType(draft.relationship_type);
      setRelationshipTypeLabel(draft.relationship_type_label);
      setRelationshipDescription(draft.description ?? "");
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
      setStep("review");
    } finally {
      setSubmitting(false);
    }
  }

  function updateDirection(which: "a_to_b" | "b_to_a", patch: Partial<DirectionDraft>) {
    setDirections((prev) => ({ ...prev, [which]: { ...prev[which], ...patch } }));
  }

  function skipReview() {
    if (newCharacter) onCreated(newCharacter, newDefaultVariant);
    close();
  }

  async function saveAndFinish() {
    if (!newCharacter || !mainCharacter) return;
    setSaving(true);
    try {
      await fetch(`/api/culturetoons/characters/${newCharacter.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, personality: { traits, behavioral_rules: behavioralRules, speech_rules: speechRules } }),
      });
      const directionPayload = (d: DirectionDraft) => ({
        affection_level: d.affection_level, trust_level: d.trust_level, conflict_level: d.conflict_level,
        perspective_description: d.perspective_description.trim() || undefined,
        behavior_rules: d.behavior_rules,
      });
      await fetch("/api/culturetoons/relationships", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId, character_a_id: mainCharacter.id, character_b_id: newCharacter.id,
          relationship_type: relationshipType || undefined,
          relationship_type_label: relationshipType === "custom" ? relationshipTypeLabel.trim() : undefined,
          description: relationshipDescription.trim() || undefined,
          comedy_chemistry: comedyChemistry,
          a_to_b: directionPayload(directions.a_to_b), b_to_a: directionPayload(directions.b_to_a),
        }),
      });
      onCreated(newCharacter, newDefaultVariant);
      close();
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 text-gray-600 text-xs font-medium px-3 py-1.5 hover:bg-gray-50 transition-colors"
      >
        <Plus className="h-3.5 w-3.5" /> New character
      </button>
    );
  }

  return (
    <div className="w-full rounded-2xl bg-white border border-gray-100 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-gray-700">
          {isFirstCharacter ? "Create your main character" : "Create a new character"}
        </p>
        <button onClick={close} className="text-gray-400 hover:text-gray-600">
          <X className="h-4 w-4" />
        </button>
      </div>

      {step === "describe" && (
        <form onSubmit={createAndMaybeGenerate} className="space-y-2">
          <input
            type="text" value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Character name"
            className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <textarea
            value={description} onChange={(e) => setDescription(e.target.value)}
            placeholder={
              isFirstCharacter
                ? `Who is the heart of this account? Give them a real backstory — where they're from, what they want, what makes them funny.`
                : "Describe this character — appearance, role, personality."
            }
            rows={3}
            className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          {!isFirstCharacter && mainCharacter && (
            <textarea
              value={relationshipHint} onChange={(e) => setRelationshipHint(e.target.value)}
              placeholder={`How do they know/relate to ${mainCharacter.name}? (optional, e.g. "younger sibling who's always competing for attention")`}
              rows={2}
              className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-blue-200"
            />
          )}
          {error && <p className="text-[11px] text-red-500">{error}</p>}
          <button
            type="submit"
            disabled={submitting || !name.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
          >
            {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            {isFirstCharacter ? "Create character" : "Create & suggest personality/relationship"}
          </button>
        </form>
      )}

      {step === "review" && newCharacter && mainCharacter && (
        <div className="space-y-4">
          <p className="text-[11px] text-gray-400">
            {newCharacter.name} has been created. Review the AI-suggested personality and relationship to{" "}
            {mainCharacter.name} below, then save — or skip and fill these in later.
          </p>
          {error && <p className="text-[11px] text-red-500">{error}</p>}

          <div>
            <p className="text-xs font-semibold text-gray-700 mb-2">Personality</p>
            <div className="space-y-3">
              <PersonalityFieldsEditor
                traits={traits} onTraitsChange={setTraits}
                behavioralRules={behavioralRules} onBehavioralRulesChange={setBehavioralRules}
                speechRules={speechRules} onSpeechRulesChange={setSpeechRules}
              />
            </div>
          </div>

          <div>
            <p className="text-xs font-semibold text-gray-700 mb-2">Relationship to {mainCharacter.name}</p>
            <div className="space-y-2">
              <div className="flex flex-wrap gap-2 items-center">
                <select
                  value={relationshipType} onChange={(e) => setRelationshipType(e.target.value)}
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
                    placeholder="Custom type label"
                    className="flex-1 min-w-[8rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                  />
                )}
                <label className="flex items-center gap-1.5 text-[11px] text-gray-500">
                  Comedy chemistry {comedyChemistry}/10
                  <input type="range" min={0} max={10} value={comedyChemistry} onChange={(e) => setComedyChemistry(parseInt(e.target.value))} className="w-20" />
                </label>
              </div>
              <textarea
                value={relationshipDescription} onChange={(e) => setRelationshipDescription(e.target.value)}
                rows={2}
                className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none"
              />
              <div className="flex gap-3 flex-wrap">
                <DirectionEditor
                  title={`${mainCharacter.name} → ${newCharacter.name}`}
                  direction={directions.a_to_b}
                  onChange={(patch) => updateDirection("a_to_b", patch)}
                  newRule={newRuleAtoB}
                  onNewRuleChange={setNewRuleAtoB}
                  onAddRule={() => { if (newRuleAtoB.trim()) { updateDirection("a_to_b", { behavior_rules: [...directions.a_to_b.behavior_rules, newRuleAtoB.trim()] }); setNewRuleAtoB(""); } }}
                  onRemoveRule={(i) => updateDirection("a_to_b", { behavior_rules: directions.a_to_b.behavior_rules.filter((_, idx) => idx !== i) })}
                />
                <DirectionEditor
                  title={`${newCharacter.name} → ${mainCharacter.name}`}
                  direction={directions.b_to_a}
                  onChange={(patch) => updateDirection("b_to_a", patch)}
                  newRule={newRuleBtoA}
                  onNewRuleChange={setNewRuleBtoA}
                  onAddRule={() => { if (newRuleBtoA.trim()) { updateDirection("b_to_a", { behavior_rules: [...directions.b_to_a.behavior_rules, newRuleBtoA.trim()] }); setNewRuleBtoA(""); } }}
                  onRemoveRule={(i) => updateDirection("b_to_a", { behavior_rules: directions.b_to_a.behavior_rules.filter((_, idx) => idx !== i) })}
                />
              </div>
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={saveAndFinish}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Save personality & relationship
            </button>
            <button
              onClick={skipReview}
              className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1.5"
            >
              Skip — I&apos;ll fill these in later
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
