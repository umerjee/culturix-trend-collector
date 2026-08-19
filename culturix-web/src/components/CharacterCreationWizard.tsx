"use client";

import { useState } from "react";
import { Plus, Loader2, Sparkles, X } from "lucide-react";
import type { Character, CharacterVariant, CastRelationshipSuggestion } from "@/lib/types";
import PersonalityFieldsEditor from "@/components/PersonalityFieldsEditor";

interface Props {
  brandId: string;
  characters: Character[];
  onCreated: (character: Character, defaultVariant: CharacterVariant | null) => void;
}

// Guided one-at-a-time character creation. The brand's first character is
// framed as the main character's origin story and needs no further review
// — there's no one else yet to build a relationship against. Every
// character after that automatically drafts both its personality and a
// relationship with EVERY existing castmate (not just whoever's currently
// marked main — reuses POST .../relationships/suggest-with-cast, the same
// batch endpoint RelationshipManager.tsx's own "Suggest with cast" button
// calls), for review before anything but the character itself is saved.
// See CastPlanWizard.tsx for the batch alternative ("describe your whole
// show at once").
export default function CharacterCreationWizard({ brandId, characters, onCreated }: Props) {
  const isFirstCharacter = characters.length === 0;

  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<"describe" | "review">("describe");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  // Defaults to true only when there's no existing main character to
  // displace — otherwise this is an explicit, visible choice rather than
  // the old silent "first character created wins" rule, which confirmed
  // live to surprise people (a secondary character created before the
  // intended lead locked in as main with no way to say otherwise).
  const [isMain, setIsMain] = useState(isFirstCharacter);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newCharacter, setNewCharacter] = useState<Character | null>(null);
  const [newDefaultVariant, setNewDefaultVariant] = useState<CharacterVariant | null>(null);
  const [traits, setTraits] = useState<Record<string, number>>({});
  const [behavioralRules, setBehavioralRules] = useState<string[]>([]);
  const [speechRules, setSpeechRules] = useState<string[]>([]);
  const [relationshipDrafts, setRelationshipDrafts] = useState<CastRelationshipSuggestion[]>([]);
  const [savedRelationshipIds, setSavedRelationshipIds] = useState<Set<string>>(new Set());
  const [savingRelationshipFor, setSavingRelationshipFor] = useState<string | null>(null);
  const [savingPersonality, setSavingPersonality] = useState(false);
  const [personalitySaved, setPersonalitySaved] = useState(false);

  function reset() {
    setStep("describe"); setName(""); setDescription(""); setIsMain(isFirstCharacter);
    setError(null); setNewCharacter(null); setNewDefaultVariant(null);
    setTraits({}); setBehavioralRules([]); setSpeechRules([]);
    setRelationshipDrafts([]); setSavedRelationshipIds(new Set()); setPersonalitySaved(false);
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
        body: JSON.stringify({
          brand_id: brandId, name: name.trim(), description: description.trim() || undefined, is_main: isMain,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Failed to create character");
        return;
      }
      const { default_variant, ...character } = data;
      const createdCharacter = character as Character;
      const createdVariant = (default_variant ?? null) as CharacterVariant | null;

      if (isFirstCharacter) {
        onCreated(createdCharacter, createdVariant);
        close();
        return;
      }

      setNewCharacter(createdCharacter);
      setNewDefaultVariant(createdVariant);

      const [personalityRes, relationshipsRes] = await Promise.all([
        fetch(`/api/culturetoons/characters/${createdCharacter.id}/personality/generate`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brand_id: brandId, hint: "" }),
        }),
        fetch(`/api/culturetoons/characters/${createdCharacter.id}/relationships/suggest-with-cast`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brand_id: brandId }),
        }),
      ]);
      const [personalityData, relationshipsData] = await Promise.all([
        personalityRes.json().catch(() => ({})), relationshipsRes.json().catch(() => ([])),
      ]);
      if (!personalityRes.ok || !relationshipsRes.ok) {
        setError(
          (typeof personalityData.detail === "string" && personalityData.detail) ||
          (typeof relationshipsData.detail === "string" && relationshipsData.detail) ||
          "AI suggestions failed — you can still fill these in later from the Characters/Relationships tabs."
        );
        setStep("review");
        return;
      }

      setTraits(personalityData.traits ?? {});
      setBehavioralRules(personalityData.behavioral_rules ?? []);
      setSpeechRules(personalityData.speech_rules ?? []);
      setRelationshipDrafts(relationshipsData as CastRelationshipSuggestion[]);
      setStep("review");
    } finally {
      setSubmitting(false);
    }
  }

  async function savePersonality() {
    if (!newCharacter) return;
    setSavingPersonality(true);
    try {
      await fetch(`/api/culturetoons/characters/${newCharacter.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, personality: { traits, behavioral_rules: behavioralRules, speech_rules: speechRules } }),
      });
      setPersonalitySaved(true);
    } finally {
      setSavingPersonality(false);
    }
  }

  async function saveRelationshipDraft(s: CastRelationshipSuggestion) {
    if ("error" in s) return;
    setSavingRelationshipFor(s.character_b_id);
    try {
      await fetch("/api/culturetoons/relationships", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          character_a_id: s.character_a_id, character_b_id: s.character_b_id,
          relationship_type: s.relationship_type,
          relationship_type_label: s.relationship_type === "custom" ? s.relationship_type_label : undefined,
          description: s.description ?? undefined,
          comedy_chemistry: s.comedy_chemistry,
          a_to_b: s.a_to_b, b_to_a: s.b_to_a,
        }),
      });
      setSavedRelationshipIds((prev) => new Set(prev).add(s.character_b_id));
    } finally {
      setSavingRelationshipFor(null);
    }
  }

  async function saveAllAndFinish() {
    if (!newCharacter) return;
    if (!personalitySaved) await savePersonality();
    await Promise.all(
      relationshipDrafts
        .filter((s) => !("error" in s) && !savedRelationshipIds.has(s.character_b_id))
        .map((s) => saveRelationshipDraft(s))
    );
    finish();
  }

  function finish() {
    if (newCharacter) onCreated(newCharacter, newDefaultVariant);
    close();
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
          {!isFirstCharacter && (
            <label className="flex items-center gap-2 text-[11px] text-gray-600">
              <input type="checkbox" checked={isMain} onChange={(e) => setIsMain(e.target.checked)} />
              Make this the main character
              {isMain && <span className="text-amber-600">— replaces whoever currently holds that</span>}
            </label>
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

      {step === "review" && newCharacter && (
        <div className="space-y-4">
          <p className="text-[11px] text-gray-400">
            {newCharacter.name} has been created. Review the AI-suggested personality and its relationship with{" "}
            each existing castmate below, then save what you want — or skip and fill these in later.
          </p>
          {error && <p className="text-[11px] text-red-500">{error}</p>}

          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-gray-700">Personality</p>
              <button
                type="button"
                onClick={savePersonality}
                disabled={savingPersonality || personalitySaved}
                className={`text-[11px] font-medium rounded-lg px-2.5 py-1 transition-colors ${
                  personalitySaved
                    ? "text-green-600 bg-green-50 cursor-default"
                    : "text-blue-600 border border-blue-200 hover:bg-blue-50 disabled:opacity-60"
                }`}
              >
                {personalitySaved ? "Saved ✓" : savingPersonality ? "Saving…" : "Save personality"}
              </button>
            </div>
            <div className="space-y-3">
              <PersonalityFieldsEditor
                traits={traits} onTraitsChange={setTraits}
                behavioralRules={behavioralRules} onBehavioralRulesChange={setBehavioralRules}
                speechRules={speechRules} onSpeechRulesChange={setSpeechRules}
              />
            </div>
          </div>

          <div>
            <p className="text-xs font-semibold text-gray-700 mb-2">
              Relationships with the cast{relationshipDrafts.length === 0 ? " — none yet, this is the first castmate" : ""}
            </p>
            {relationshipDrafts.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {relationshipDrafts.map((s) => {
                  const saved = savedRelationshipIds.has(s.character_b_id);
                  return (
                    <div key={s.character_b_id} className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                      <p className="text-xs font-medium text-gray-800">
                        {newCharacter.name} ↔ {s.character_b_name}
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
                              onClick={() => saveRelationshipDraft(s)}
                              disabled={saved || savingRelationshipFor === s.character_b_id}
                              className={`text-[11px] font-medium rounded-lg px-2.5 py-1 transition-colors ${
                                saved
                                  ? "text-green-600 bg-green-50 cursor-default"
                                  : "text-blue-600 border border-blue-200 hover:bg-blue-50 disabled:opacity-60"
                              }`}
                            >
                              {saved ? "Saved ✓" : savingRelationshipFor === s.character_b_id ? "Saving…" : "Save"}
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

          <div className="flex gap-2">
            <button
              onClick={saveAllAndFinish}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors"
            >
              Save all & finish
            </button>
            <button
              onClick={finish}
              className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1.5"
            >
              Finish — I&apos;ll fill in the rest later
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
