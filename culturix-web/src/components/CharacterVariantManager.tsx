"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, CheckCircle2, XCircle, Sparkles, ChevronDown, ChevronRight, Pencil, Trash2, Star } from "lucide-react";
import type { Character, CharacterVariant, VoiceProvider, CharacterPersonality } from "@/lib/types";
import { buildPersonalitySummary } from "@/lib/personalitySummary";
import CharacterImageBuilder from "@/components/CharacterImageBuilder";
import ExpressionUploadGrid from "@/components/ExpressionUploadGrid";
import MemoryManager from "@/components/MemoryManager";
import PersonalityFieldsEditor from "@/components/PersonalityFieldsEditor";
import CharacterCreationWizard from "@/components/CharacterCreationWizard";
import CastPlanWizard from "@/components/CastPlanWizard";
import InfoTooltip from "@/components/ui/Tooltip";

interface Props {
  brandId: string;
  hasElevenLabsKey: boolean;
  // Both lifted up to CultureToonWorkspace. `variants` for cross-tab
  // staleness (Scripts/Toons/Episodes read it too); `characters` for a
  // different reason — this whole component unmounts/remounts on every
  // tab switch away and back (conditional rendering in
  // CultureToonWorkspace), so state owned locally here doesn't survive
  // that. Confirmed live: AI-generated character portraits vanished after
  // switching to the Toons tab and back — this component's own
  // `useState(initialCharacters)` was resetting to the original page-load
  // snapshot on every remount. See CultureToonWorkspace.tsx for the fuller
  // explanation.
  characters: Character[];
  setCharacters: React.Dispatch<React.SetStateAction<Character[]>>;
  variants: CharacterVariant[];
  setVariants: React.Dispatch<React.SetStateAction<CharacterVariant[]>>;
  // When set (by a blocker elsewhere, e.g. ToonManager's "register this
  // character" prompt), selects this exact variant — and its parent
  // character — on arrival instead of defaulting to the first character.
  focusVariantId?: string | null;
}

function ElementStatusIcon({ status }: { status: CharacterVariant["element_status"] }) {
  if (status === "ready") return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />;
  if (status === "pending") return <Loader2 className="h-3.5 w-3.5 text-amber-500 animate-spin shrink-0" />;
  if (status === "failed") return <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />;
  return null;
}

// The variant create_character auto-creates alongside every new character
// (same name, no description/culture_tag of its own) — this is "the
// character itself" for registration/Expressions/LoRA purposes, as opposed
// to a deliberately-created cultural recast. There's no explicit
// is_default flag in the schema, so name-match (falling back to whichever
// variant is oldest/first) is the same heuristic the backend's own
// portrait-propagation fix uses.
function resolveDefaultVariantId(
  characterId: string | null, chars: Character[], vars: CharacterVariant[],
): string | null {
  if (!characterId) return null;
  const character = chars.find((c) => c.id === characterId);
  const owned = vars.filter((v) => v.character_id === characterId);
  return (character ? owned.find((v) => v.name === character.name) : undefined)?.id ?? owned[0]?.id ?? null;
}

export default function CharacterVariantManager({ brandId, hasElevenLabsKey, characters, setCharacters, variants, setVariants, focusVariantId }: Props) {
  const focusedVariant = focusVariantId ? variants.find((v) => v.id === focusVariantId) : null;
  const [selectedCharacterId, setSelectedCharacterId] = useState<string | null>(
    focusedVariant?.character_id ?? characters[0]?.id ?? null
  );
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(
    focusedVariant?.id ?? resolveDefaultVariantId(characters[0]?.id ?? null, characters, variants)
  );

  useEffect(() => {
    if (!focusVariantId) return;
    const variant = variants.find((v) => v.id === focusVariantId);
    if (!variant) return;
    setSelectedCharacterId(variant.character_id);
    setSelectedVariantId(variant.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusVariantId]);

  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [artStyleDraft, setArtStyleDraft] = useState<Character["art_style"]>("cartoon_3d");
  const [generatingImage, setGeneratingImage] = useState(false);
  const [imageGenError, setImageGenError] = useState<string | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [saveNameError, setSaveNameError] = useState<string | null>(null);
  const [makeMainError, setMakeMainError] = useState<string | null>(null);
  const [archivingCharacter, setArchivingCharacter] = useState(false);
  const [archiveCharacterError, setArchiveCharacterError] = useState<string | null>(null);

  const [personalityOpen, setPersonalityOpen] = useState(false);
  const [traits, setTraits] = useState<Record<string, number>>({});
  const [behavioralRules, setBehavioralRules] = useState<string[]>([]);
  const [speechRules, setSpeechRules] = useState<string[]>([]);
  const [savingPersonality, setSavingPersonality] = useState(false);
  const [savePersonalityError, setSavePersonalityError] = useState<string | null>(null);
  const [personalityHint, setPersonalityHint] = useState("");
  const [generatingPersonality, setGeneratingPersonality] = useState(false);
  const [personalityGenError, setPersonalityGenError] = useState<string | null>(null);

  const [newVariantName, setNewVariantName] = useState("");
  const [creatingVariant, setCreatingVariant] = useState(false);
  const [voiceProvider, setVoiceProvider] = useState<VoiceProvider>("kling");
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [training, setTraining] = useState(false);
  const [trainError, setTrainError] = useState<string | null>(null);
  const [startingGenerateAll, setStartingGenerateAll] = useState(false);
  const [generateAllStartError, setGenerateAllStartError] = useState<string | null>(null);
  const [startingLoraPreview, setStartingLoraPreview] = useState(false);
  const [loraPreviewStartError, setLoraPreviewStartError] = useState<string | null>(null);

  const [variantDescriptionDraft, setVariantDescriptionDraft] = useState("");
  const [variantCultureTagDraft, setVariantCultureTagDraft] = useState("");
  const [generatingVariantImage, setGeneratingVariantImage] = useState(false);
  const [variantImageGenError, setVariantImageGenError] = useState<string | null>(null);
  const [variantImageGenWarning, setVariantImageGenWarning] = useState<string | null>(null);
  const [variantNameDraft, setVariantNameDraft] = useState("");
  const [savingVariantName, setSavingVariantName] = useState(false);
  const [saveVariantNameError, setSaveVariantNameError] = useState<string | null>(null);
  const [archivingVariant, setArchivingVariant] = useState(false);
  const [archiveVariantError, setArchiveVariantError] = useState<string | null>(null);

  const selectedCharacter = characters.find((c) => c.id === selectedCharacterId) ?? null;
  const characterVariants = variants.filter((v) => v.character_id === selectedCharacterId);
  const selectedVariant = variants.find((v) => v.id === selectedVariantId) ?? null;

  // Poll while a variant's element registration, LoRA training, LoRA
  // preview generation, or bulk expression generation is in flight.
  useEffect(() => {
    if (!selectedVariant) return;
    if (
      selectedVariant.element_status !== "pending"
      && selectedVariant.lora_status !== "training"
      && selectedVariant.lora_preview_status !== "generating"
      && !selectedVariant.expressions_generating
    ) return;
    const interval = setInterval(async () => {
      const res = await fetch(`/api/culturetoons/variants/${selectedVariant.id}?brand_id=${brandId}`, { cache: "no-store" });
      if (res.ok) {
        const updated = await res.json();
        setVariants((prev) => prev.map((v) => (v.id === updated.id ? updated : v)));
      }
    }, 4000);
    return () => clearInterval(interval);
  }, [selectedVariant, brandId]);

  useEffect(() => {
    setDescriptionDraft(selectedCharacter?.description ?? "");
    setArtStyleDraft(selectedCharacter?.art_style ?? "cartoon_3d");
    setImageGenError(null);
    setNameDraft(selectedCharacter?.name ?? "");
    setSaveNameError(null);
    setMakeMainError(null);
    setSavePersonalityError(null);
    setTraits(selectedCharacter?.personality?.traits ?? {});
    setBehavioralRules(selectedCharacter?.personality?.behavioral_rules ?? []);
    setSpeechRules(selectedCharacter?.personality?.speech_rules ?? []);
  }, [selectedCharacterId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setVariantDescriptionDraft(selectedVariant?.description ?? "");
    setVariantCultureTagDraft(selectedVariant?.culture_tag ?? "");
    setVariantImageGenError(null);
    setVariantImageGenWarning(null);
    setVariantNameDraft(selectedVariant?.name ?? "");
    setSaveVariantNameError(null);
    setRegisterError(null);
    setTrainError(null);
  }, [selectedVariantId]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleCharacterCreated(character: Character, defaultVariant: CharacterVariant | null) {
    setCharacters((prev) => [...prev, character]);
    if (defaultVariant) setVariants((prev) => [...prev, defaultVariant]);
    setSelectedCharacterId(character.id);
    setSelectedVariantId(defaultVariant?.id ?? null);
  }

  function handleCastCreated(newCharacters: Character[], newVariants: CharacterVariant[]) {
    setCharacters((prev) => [...prev, ...newCharacters]);
    setVariants((prev) => [...prev, ...newVariants]);
    if (newCharacters[0]) {
      setSelectedCharacterId(newCharacters[0].id);
      setSelectedVariantId(newVariants.find((v) => v.character_id === newCharacters[0].id)?.id ?? null);
    }
  }

  async function makeMainCharacter(characterId: string) {
    setMakeMainError(null);
    try {
      const res = await fetch(`/api/culturetoons/characters/${characterId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, is_main: true }),
      });
      if (res.ok) {
        const updated = await res.json();
        setCharacters((prev) => prev.map((c) => (c.id === characterId ? (updated as Character) : { ...c, is_main: false })));
      } else {
        const data = await res.json().catch(() => ({}));
        setMakeMainError(typeof data.detail === "string" ? data.detail : `Couldn't set main character (${res.status})`);
      }
    } catch {
      setMakeMainError("Network error — check your connection and try again.");
    }
  }

  async function addVariant(e: React.FormEvent) {
    e.preventDefault();
    if (!newVariantName.trim() || !selectedCharacterId) return;
    setCreatingVariant(true);
    try {
      const res = await fetch("/api/culturetoons/variants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, character_id: selectedCharacterId, name: newVariantName.trim() }),
      });
      if (res.ok) {
        const variant = await res.json();
        setVariants((prev) => [...prev, variant]);
        setSelectedVariantId(variant.id);
        setNewVariantName("");
      }
    } finally {
      setCreatingVariant(false);
    }
  }

  async function registerElement() {
    if (!selectedVariant) return;
    setRegistering(true);
    setRegisterError(null);
    try {
      const res = await fetch(`/api/culturetoons/variants/${selectedVariant.id}/register-element`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, voice_provider: voiceProvider }),
      });
      if (res.ok) {
        setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? { ...v, element_status: "pending" } : v)));
      } else {
        const data = await res.json().catch(() => ({}));
        setRegisterError(typeof data.detail === "string" ? data.detail : `Couldn't register (${res.status})`);
      }
    } catch {
      setRegisterError("Network error — check your connection and try again.");
    } finally {
      setRegistering(false);
    }
  }

  async function trainLora() {
    if (!selectedVariant) return;
    setTraining(true);
    setTrainError(null);
    try {
      const res = await fetch(`/api/culturetoons/variants/${selectedVariant.id}/train-lora`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      if (res.ok) {
        setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? { ...v, lora_status: "training", lora_error: null } : v)));
      } else {
        const data = await res.json().catch(() => ({}));
        setTrainError(typeof data.detail === "string" ? data.detail : `Couldn't start training (${res.status})`);
      }
    } catch {
      setTrainError("Network error — check your connection and try again.");
    } finally {
      setTraining(false);
    }
  }

  async function generateAllExpressions() {
    if (!selectedVariant) return;
    setStartingGenerateAll(true);
    setGenerateAllStartError(null);
    try {
      const res = await fetch(`/api/culturetoons/variants/${selectedVariant.id}/expressions/generate-all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      if (res.ok) {
        // Optimistic flip, same pattern as registerElement/trainLora above —
        // the poll effect (keyed on expressions_generating) picks up from
        // here and keeps refetching until the background job finishes.
        setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? { ...v, expressions_generating: true, expressions_generate_errors: {} } : v)));
      } else {
        const data = await res.json().catch(() => ({}));
        setGenerateAllStartError(typeof data.detail === "string" ? data.detail : `Couldn't start (${res.status})`);
      }
    } catch {
      setGenerateAllStartError("Network error — check your connection and try again.");
    } finally {
      setStartingGenerateAll(false);
    }
  }

  async function generateLoraPreview() {
    if (!selectedVariant) return;
    setStartingLoraPreview(true);
    setLoraPreviewStartError(null);
    try {
      const res = await fetch(`/api/culturetoons/variants/${selectedVariant.id}/lora-preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId }),
      });
      if (res.ok) {
        setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? { ...v, lora_preview_status: "generating", lora_preview_error: null } : v)));
      } else {
        const data = await res.json().catch(() => ({}));
        setLoraPreviewStartError(typeof data.detail === "string" ? data.detail : `Couldn't start (${res.status})`);
      }
    } catch {
      setLoraPreviewStartError("Network error — check your connection and try again.");
    } finally {
      setStartingLoraPreview(false);
    }
  }

  // Mirrors the backend's own propagation rule (see
  // app/routers/culturetoons.py::_propagate_portrait_to_untouched_default_variants)
  // so the UI reflects it immediately instead of only after a refetch —
  // only fills in a variant that's still exactly as auto-created (no
  // image/description/culture_tag of its own yet).
  function propagatePortraitToUntouchedVariants(characterId: string, imageUrl: string) {
    setVariants((prev) => prev.map((v) => (
      v.character_id === characterId && !v.image_url && !v.description && !v.culture_tag
        ? { ...v, image_url: imageUrl }
        : v
    )));
  }

  async function generateCharacterImage() {
    if (!selectedCharacter) return;
    if (!descriptionDraft.trim()) {
      setImageGenError("Add a description first.");
      return;
    }
    setGeneratingImage(true);
    setImageGenError(null);
    try {
      const res = await fetch(`/api/culturetoons/characters/${selectedCharacter.id}/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, description: descriptionDraft.trim(), art_style: artStyleDraft }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setImageGenError(typeof data.detail === "string" ? data.detail : "Image generation failed");
        return;
      }
      setCharacters((prev) => prev.map((c) => (c.id === selectedCharacter.id ? (data as Character) : c)));
      if (typeof data.base_image_url === "string") {
        propagatePortraitToUntouchedVariants(selectedCharacter.id, data.base_image_url);
      }
    } finally {
      setGeneratingImage(false);
    }
  }

  async function generateVariantImage() {
    if (!selectedVariant) return;
    if (!variantDescriptionDraft.trim()) {
      setVariantImageGenError("Add a description first.");
      return;
    }
    setGeneratingVariantImage(true);
    setVariantImageGenError(null);
    setVariantImageGenWarning(null);
    try {
      const res = await fetch(`/api/culturetoons/variants/${selectedVariant.id}/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          description: variantDescriptionDraft.trim(),
          culture_tag: variantCultureTagDraft.trim(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setVariantImageGenError(typeof data.detail === "string" ? data.detail : "Image generation failed");
        return;
      }
      if (typeof data.generation_warning === "string") setVariantImageGenWarning(data.generation_warning);
      setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? (data as CharacterVariant) : v)));
    } finally {
      setGeneratingVariantImage(false);
    }
  }

  async function saveCharacterName() {
    if (!selectedCharacter || !nameDraft.trim() || nameDraft.trim() === selectedCharacter.name) return;
    setSavingName(true);
    setSaveNameError(null);
    try {
      const res = await fetch(`/api/culturetoons/characters/${selectedCharacter.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, name: nameDraft.trim() }),
      });
      if (res.ok) {
        const data = await res.json();
        setCharacters((prev) => prev.map((c) => (c.id === selectedCharacter.id ? (data as Character) : c)));
      } else {
        const data = await res.json().catch(() => ({}));
        setSaveNameError(typeof data.detail === "string" ? data.detail : `Couldn't save name (${res.status})`);
      }
    } catch {
      setSaveNameError("Network error — check your connection and try again.");
    } finally {
      setSavingName(false);
    }
  }

  async function savePersonality() {
    if (!selectedCharacter) return;
    setSavingPersonality(true);
    setSavePersonalityError(null);
    try {
      const personality: CharacterPersonality = {
        traits, behavioral_rules: behavioralRules, speech_rules: speechRules,
      };
      const res = await fetch(`/api/culturetoons/characters/${selectedCharacter.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, personality }),
      });
      if (res.ok) {
        const data = await res.json();
        setCharacters((prev) => prev.map((c) => (c.id === selectedCharacter.id ? (data as Character) : c)));
      } else {
        const data = await res.json().catch(() => ({}));
        setSavePersonalityError(typeof data.detail === "string" ? data.detail : `Couldn't save personality (${res.status})`);
      }
    } catch {
      setSavePersonalityError("Network error — check your connection and try again.");
    } finally {
      setSavingPersonality(false);
    }
  }

  async function generatePersonalityDraft() {
    if (!selectedCharacter) return;
    setGeneratingPersonality(true);
    setPersonalityGenError(null);
    try {
      const res = await fetch(`/api/culturetoons/characters/${selectedCharacter.id}/personality/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, hint: personalityHint.trim() || undefined }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setPersonalityGenError(typeof data.detail === "string" ? data.detail : "Personality generation failed");
        return;
      }
      setTraits(data.traits ?? {});
      setBehavioralRules(data.behavioral_rules ?? []);
      setSpeechRules(data.speech_rules ?? []);
    } finally {
      setGeneratingPersonality(false);
    }
  }

  async function archiveCharacter() {
    if (!selectedCharacter) return;
    setArchivingCharacter(true);
    setArchiveCharacterError(null);
    try {
      const res = await fetch(`/api/culturetoons/characters/${selectedCharacter.id}?brand_id=${brandId}`, { method: "DELETE" });
      if (res.ok) {
        const remaining = characters.filter((c) => c.id !== selectedCharacter.id);
        setCharacters(remaining);
        setVariants((prev) => prev.filter((v) => v.character_id !== selectedCharacter.id));
        setSelectedCharacterId(remaining[0]?.id ?? null);
        setSelectedVariantId(null);
      } else {
        const data = await res.json().catch(() => ({}));
        setArchiveCharacterError(typeof data.detail === "string" ? data.detail : `Couldn't archive (${res.status})`);
      }
    } catch {
      setArchiveCharacterError("Network error — check your connection and try again.");
    } finally {
      setArchivingCharacter(false);
    }
  }

  async function saveVariantName() {
    if (!selectedVariant || !variantNameDraft.trim() || variantNameDraft.trim() === selectedVariant.name) return;
    setSavingVariantName(true);
    setSaveVariantNameError(null);
    try {
      const res = await fetch(`/api/culturetoons/variants/${selectedVariant.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, name: variantNameDraft.trim() }),
      });
      if (res.ok) {
        const data = await res.json();
        setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? (data as CharacterVariant) : v)));
      } else {
        const data = await res.json().catch(() => ({}));
        setSaveVariantNameError(typeof data.detail === "string" ? data.detail : `Couldn't save name (${res.status})`);
      }
    } catch {
      setSaveVariantNameError("Network error — check your connection and try again.");
    } finally {
      setSavingVariantName(false);
    }
  }

  async function archiveVariant() {
    if (!selectedVariant) return;
    setArchivingVariant(true);
    setArchiveVariantError(null);
    try {
      const res = await fetch(`/api/culturetoons/variants/${selectedVariant.id}?brand_id=${brandId}`, { method: "DELETE" });
      if (res.ok) {
        setVariants((prev) => prev.filter((v) => v.id !== selectedVariant.id));
        setSelectedVariantId(null);
      } else {
        const data = await res.json().catch(() => ({}));
        setArchiveVariantError(typeof data.detail === "string" ? data.detail : `Couldn't archive (${res.status})`);
      }
    } catch {
      setArchiveVariantError("Network error — check your connection and try again.");
    } finally {
      setArchivingVariant(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Step 1 — base character */}
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Step 1 · Base character</h3>
        <p className="text-xs text-gray-400 mb-3">Name it, describe how it should look, pick an art style, then generate.</p>

        <div className="flex flex-wrap items-center gap-2 mb-3">
          {characters.map((c) => (
            <button
              key={c.id}
              onClick={() => { setSelectedCharacterId(c.id); setSelectedVariantId(resolveDefaultVariantId(c.id, characters, variants)); }}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                c.id === selectedCharacterId ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {c.is_main && <Star className="h-3 w-3 fill-current" />}
              {c.name}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2 mb-4">
          <CharacterCreationWizard
            brandId={brandId}
            characters={characters}
            onCreated={handleCharacterCreated}
          />
          <CastPlanWizard
            brandId={brandId}
            characters={characters}
            onCreated={handleCastCreated}
          />
        </div>

        {selectedCharacter ? (
          <>
            <div className="flex items-center gap-2 mb-3">
              <Pencil className="h-3.5 w-3.5 text-gray-400 shrink-0" />
              <input
                type="text"
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onBlur={saveCharacterName}
                onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                className="flex-1 min-w-[8rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
              {savingName && <Loader2 className="h-3.5 w-3.5 text-gray-400 animate-spin shrink-0" />}
              {!selectedCharacter.is_main && (
                <button
                  onClick={() => makeMainCharacter(selectedCharacter.id)}
                  title="Make this the main character this brand's cast/story is built around"
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-200 text-gray-500 hover:text-amber-600 hover:border-amber-200 text-xs px-2.5 py-1.5 transition-colors shrink-0"
                >
                  <Star className="h-3.5 w-3.5" />
                  Make main
                </button>
              )}
              <button
                onClick={archiveCharacter}
                disabled={archivingCharacter}
                title="Archive this character and all its variants"
                className="inline-flex items-center gap-1 rounded-lg border border-gray-200 text-gray-500 hover:text-red-600 hover:border-red-200 text-xs px-2.5 py-1.5 transition-colors disabled:opacity-60 shrink-0"
              >
                {archivingCharacter ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                Archive
              </button>
            </div>
            {saveNameError && <p className="text-[11px] text-red-500 mb-3">{saveNameError}</p>}
            {makeMainError && <p className="text-[11px] text-red-500 mb-3">{makeMainError}</p>}
            {archiveCharacterError && <p className="text-[11px] text-red-500 mb-3">{archiveCharacterError}</p>}
            <CharacterImageBuilder
            description={descriptionDraft}
            onDescriptionChange={setDescriptionDraft}
            descriptionPlaceholder="Describe the character — appearance, age, culture, personality, style. E.g. &quot;A cheerful Nigerian uncle in his 50s, round glasses, colorful agbada, warm expressive face.&quot;"
            artStyle={{ value: artStyleDraft, onChange: setArtStyleDraft }}
            referencePhotoUrl={selectedCharacter.reference_image_url}
            referenceUploadUrl={`/api/culturetoons/characters/${selectedCharacter.id}/reference-image`}
            portraitUrl={selectedCharacter.base_image_url}
            portraitUploadUrl={`/api/culturetoons/characters/${selectedCharacter.id}/image`}
            extraFields={{ brand_id: brandId }}
            onReferenceUploaded={(data) => setCharacters((prev) => prev.map((c) => (c.id === selectedCharacter.id ? { ...c, ...data } as Character : c)))}
            onPortraitUploaded={(data) => {
              setCharacters((prev) => prev.map((c) => (c.id === selectedCharacter.id ? { ...c, ...data } as Character : c)));
              if (typeof data.base_image_url === "string") {
                propagatePortraitToUntouchedVariants(selectedCharacter.id, data.base_image_url);
              }
            }}
            onGenerate={generateCharacterImage}
            generating={generatingImage}
            error={imageGenError}
            helperText="A reference photo is optional — with one, generation is grounded on your photo's likeness but always re-illustrated in the chosen style. Regenerate as many times as you like to refine it."
          />

          <div className="rounded-xl border border-gray-100 mt-4">
            <button
              onClick={() => setPersonalityOpen((v) => !v)}
              className="w-full flex items-center justify-between px-3 py-2.5 text-xs font-semibold text-gray-700"
            >
              <span className="flex items-center gap-1.5">
                {personalityOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                Personality
              </span>
              {(behavioralRules.length > 0 || speechRules.length > 0 || Object.keys(traits).length > 0) && (
                <span className="text-[10px] text-gray-400">Configured</span>
              )}
            </button>
            {(() => {
              const summary = buildPersonalitySummary(selectedCharacter.name, selectedCharacter.personality);
              return summary ? (
                <p className="px-3 pb-2.5 text-[11px] text-gray-500 italic">{summary}</p>
              ) : null;
            })()}
            {personalityOpen && (
              <div className="px-3 pb-3 space-y-4">
                <p className="text-[11px] text-gray-400">
                  Drives future script generation so {selectedCharacter.name}&apos;s personality stays consistent
                  across episodes instead of being reinvented by the AI each time.
                </p>

                <div className="rounded-lg bg-blue-50 border border-blue-100 p-2.5 space-y-2">
                  <div className="flex items-center gap-1.5 text-[11px] font-medium text-blue-700">
                    <Sparkles className="h-3.5 w-3.5" /> Let AI draft a personality
                  </div>
                  <div className="flex gap-1.5">
                    <input
                      type="text" value={personalityHint} onChange={(e) => setPersonalityHint(e.target.value)}
                      placeholder="Optional: e.g. &quot;sarcastic older brother who loves cricket&quot;"
                      className="flex-1 rounded-lg border border-blue-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
                    />
                    <button
                      onClick={generatePersonalityDraft}
                      disabled={generatingPersonality}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60 shrink-0"
                    >
                      {generatingPersonality ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      Generate
                    </button>
                  </div>
                  <p className="text-[10px] text-blue-600/70">
                    Fills in the traits and rules below from {selectedCharacter.name}&apos;s description — review and adjust before saving.
                  </p>
                  {personalityGenError && <p className="text-[11px] text-red-500">{personalityGenError}</p>}
                </div>

                <PersonalityFieldsEditor
                  traits={traits} onTraitsChange={setTraits}
                  behavioralRules={behavioralRules} onBehavioralRulesChange={setBehavioralRules}
                  speechRules={speechRules} onSpeechRulesChange={setSpeechRules}
                />

                <button
                  onClick={savePersonality}
                  disabled={savingPersonality}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
                >
                  {savingPersonality ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  Save personality
                </button>
                {savePersonalityError && <p className="text-[11px] text-red-500">{savePersonalityError}</p>}
              </div>
            )}
          </div>
          </>
        ) : (
          <p className="text-xs text-gray-400">Name a character above to get started.</p>
        )}
      </div>

      {/* Step 2 — Expressions & video readiness. Operates on selectedVariant,
          which defaults to the character's own auto-created identity (see
          resolveDefaultVariantId) — the common case never needs to touch
          Step 3 at all. Selecting a different variant chip in Step 3
          re-targets this section at that variant instead. Deliberately
          placed above Variants: building out the expression catalogue for
          the character's own identity is the thing nearly everyone needs
          first, Variants (cultural recasts) is an optional later step. */}
      {selectedCharacter && (
        <div className="rounded-2xl bg-white border border-gray-100 p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-1 flex items-center gap-1.5">
            Step 2 · Expressions &amp; video readiness
            {selectedVariant && <ElementStatusIcon status={selectedVariant.element_status} />}
          </h3>
          <p className="text-xs text-gray-400 mb-3">
            {selectedVariant && selectedVariant.name !== selectedCharacter.name
              ? `Editing the "${selectedVariant.name}" variant instead of ${selectedCharacter.name}'s own identity — switch back in Step 3 below.`
              : `${selectedCharacter.name}'s own expression catalogue and video registration — most characters only ever need this.`}
          </p>

          {selectedVariant ? (
            <div className="space-y-4">
              <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-gray-700">Kling character registration</span>
                  {selectedVariant.element_status === "ready" && (
                    <span className="inline-flex items-center gap-1 text-xs text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" /> Ready</span>
                  )}
                  {selectedVariant.element_status === "pending" && (
                    <span className="inline-flex items-center gap-1 text-xs text-amber-600"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Registering…</span>
                  )}
                  {selectedVariant.element_status === "failed" && (
                    <span className="inline-flex items-center gap-1 text-xs text-red-600"><XCircle className="h-3.5 w-3.5" /> Failed</span>
                  )}
                </div>
                <p className="text-[11px] text-gray-500 mb-2">
                  Registers this variant&apos;s image as a reusable Kling character so it stays visually
                  consistent across every video generated for it. Required before generating any video.
                </p>
                {selectedVariant.element_error && (
                  <p className="text-[11px] text-red-500 mb-2">{selectedVariant.element_error}</p>
                )}
                <div className="flex items-center gap-2">
                  <select
                    value={voiceProvider}
                    onChange={(e) => setVoiceProvider(e.target.value as VoiceProvider)}
                    className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
                  >
                    <option value="kling">Auto (Kling picks a voice)</option>
                    <option value="elevenlabs" disabled={!hasElevenLabsKey}>
                      ElevenLabs {!hasElevenLabsKey && "(add API key in brand settings)"}
                    </option>
                  </select>
                  <button
                    onClick={registerElement}
                    disabled={registering || !selectedVariant.image_url || selectedVariant.element_status === "pending"}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
                  >
                    {registering ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                    {selectedVariant.element_status === "ready" ? "Re-register" : "Register"}
                  </button>
                </div>
                <p className="text-[11px] text-gray-400 mt-1.5">
                  Neither option lets you preview a voice ahead of time — &quot;Auto&quot; means Kling
                  assigns one automatically when a video is generated, no specific voice chosen now.
                  ElevenLabs is only meaningfully different once you have a specific cloned or
                  pre-selected voice for this character (not yet supported from this screen).
                </p>
                {!selectedVariant.image_url && (
                  <p className="text-[11px] text-gray-400 mt-1.5">Build {selectedCharacter.name}&apos;s portrait in Step 1 above first.</p>
                )}
                {registerError && <p className="text-[11px] text-red-500 mt-1.5">{registerError}</p>}
              </div>

              <ExpressionUploadGrid
                key={selectedVariant.id} brandId={brandId} variantId={selectedVariant.id}
                hasPortrait={!!selectedVariant.image_url}
                generatingAll={selectedVariant.expressions_generating}
                generateAllErrors={selectedVariant.expressions_generate_errors}
                onGenerateAll={generateAllExpressions}
                startingGenerateAll={startingGenerateAll}
                generateAllStartError={generateAllStartError}
              />

              <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-gray-700">Visual identity (self-hosted)</span>
                  {selectedVariant.lora_status === "ready" && (
                    <span className="inline-flex items-center gap-1 text-xs text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" /> Ready</span>
                  )}
                  {selectedVariant.lora_status === "training" && (
                    <span className="inline-flex items-center gap-1 text-xs text-amber-600"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Training…</span>
                  )}
                  {selectedVariant.lora_status === "failed" && (
                    <span className="inline-flex items-center gap-1 text-xs text-red-600"><XCircle className="h-3.5 w-3.5" /> Failed</span>
                  )}
                </div>
                <p className="text-[11px] text-gray-500 mb-2">
                  Trains this variant&apos;s own visual identity for self-hosted (RunPod/LTX-2) video
                  generation — separate from Kling registration above, and required before self-hosted
                  video can use this character. Uses the Expression set above as training images
                  automatically, so finishing that set is usually all that&apos;s needed here.
                </p>
                {selectedVariant.lora_error && (
                  <p className="text-[11px] text-red-500 mb-2">{selectedVariant.lora_error}</p>
                )}
                <button
                  onClick={trainLora}
                  disabled={training || selectedVariant.lora_status === "training"}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
                >
                  {training ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                  {selectedVariant.lora_status === "ready" || selectedVariant.lora_status === "failed" ? "Retrain" : "Start training"}
                </button>
                <p className="text-[11px] text-gray-400 mt-1.5">
                  Training runs on a dedicated GPU pod and can take up to an hour — feel free to switch
                  tabs or characters; it&apos;ll keep running and update here when done.
                </p>
                {trainError && <p className="text-[11px] text-red-500 mt-1.5">{trainError}</p>}

                {selectedVariant.lora_status === "ready" && (
                  <div className="mt-3 pt-3 border-t border-gray-200">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold text-gray-700">Preview</span>
                      {selectedVariant.lora_preview_status === "ready" && (
                        <span className="inline-flex items-center gap-1 text-xs text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" /> Ready</span>
                      )}
                      {selectedVariant.lora_preview_status === "generating" && (
                        <span className="inline-flex items-center gap-1 text-xs text-amber-600"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Generating…</span>
                      )}
                      {selectedVariant.lora_preview_status === "failed" && (
                        <span className="inline-flex items-center gap-1 text-xs text-red-600"><XCircle className="h-3.5 w-3.5" /> Failed</span>
                      )}
                    </div>
                    <p className="text-[11px] text-gray-500 mb-2">
                      There&apos;s no automated quality check for a trained LoRA — this generates one
                      cheap, short test clip using it, so you can actually look at whether the character
                      looks right before using it for real.
                    </p>
                    {selectedVariant.lora_preview_error && (
                      <p className="text-[11px] text-red-500 mb-2">{selectedVariant.lora_preview_error}</p>
                    )}
                    <button
                      onClick={generateLoraPreview}
                      disabled={startingLoraPreview || selectedVariant.lora_preview_status === "generating"}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
                    >
                      {startingLoraPreview || selectedVariant.lora_preview_status === "generating"
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        : <Sparkles className="h-3.5 w-3.5" />}
                      {selectedVariant.lora_preview_status === "ready" || selectedVariant.lora_preview_status === "failed"
                        ? "Regenerate preview" : "Generate preview"}
                    </button>
                    {loraPreviewStartError && <p className="text-[11px] text-red-500 mt-1.5">{loraPreviewStartError}</p>}
                    {selectedVariant.lora_preview_url && (
                      <video
                        key={selectedVariant.lora_preview_url}
                        src={selectedVariant.lora_preview_url}
                        controls
                        className="mt-2 rounded-lg max-w-[240px] border border-gray-200"
                      />
                    )}
                  </div>
                )}
              </div>

              <MemoryManager key={`memory-${selectedVariant.id}`} brandId={brandId} variantId={selectedVariant.id} />
            </div>
          ) : (
            <p className="text-xs text-gray-400">This character has no variant yet — create one in Step 3 below.</p>
          )}
        </div>
      )}

      {/* Step 3 — Variants & Related Characters. "Variants" (below) is
          THIS character recast for a different context — same identity,
          personality, and backstory, just a different cultural look.
          "Related Characters" (a separate person, e.g. Kumar's wife or
          neighbour, with their own personality) is deliberately NOT here —
          see the Relationships tab, which links two independent Character
          records instead of creating a variant of one. Optional/later —
          Step 2 above already covers the common "just this character"
          case via its auto-selected default variant. */}
      {selectedCharacter && (
        <div className="rounded-2xl bg-white border border-gray-100 p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-1">
            Step 3 · Variants of {selectedCharacter.name} <span className="text-gray-400 font-normal">(optional, for later)</span>
          </h3>
          <p className="text-xs text-gray-400 mb-3">
            The same character, recast for a different cultural context (e.g. &quot;Chinese version&quot;, &quot;Swiss
            version&quot;) — same identity and personality, different look. Each one stays visually connected
            to {selectedCharacter.name} unless it has its own reference photo, and needs its own Expression
            set (Step 2 above, once selected below). Looking for a{" "}
            <strong>different</strong> person connected to {selectedCharacter.name} (a wife, a neighbour, a
            friend) instead? That&apos;s a separate character — create it on this tab, then link the two on
            the <strong>Relationships</strong> tab.
          </p>

          {characterVariants.length > 0 && (
            <div className="flex items-center gap-1 text-[10px] text-gray-400 mb-2">
              <CheckCircle2 className="h-3 w-3 text-emerald-500" /> ready to generate video
              <span className="mx-1">·</span>
              <Loader2 className="h-3 w-3 text-amber-500" /> registering
              <span className="mx-1">·</span>
              <XCircle className="h-3 w-3 text-red-500" /> registration failed
              <span className="mx-1">·</span>
              no icon = not registered yet
              <InfoTooltip text="Registration is a one-time step (Step 2 above, per variant) that teaches Kling this character's face so future videos stay visually consistent — required before generating any video." />
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 mb-4">
            {characterVariants.map((v) => (
              <button
                key={v.id}
                onClick={() => setSelectedVariantId(v.id)}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  v.id === selectedVariantId ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {v.name}
                {v.culture_tag && <span className={v.id === selectedVariantId ? "text-blue-100" : "text-gray-400"}> · {v.culture_tag}</span>}
                <ElementStatusIcon status={v.element_status} />
              </button>
            ))}
            <form onSubmit={addVariant} className="flex gap-1">
              <input
                type="text"
                value={newVariantName}
                onChange={(e) => setNewVariantName(e.target.value)}
                placeholder="New variant name, e.g. Wife"
                className="rounded-full border border-gray-200 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200 w-40"
              />
              <button
                type="submit"
                disabled={creatingVariant || !newVariantName.trim()}
                className="inline-flex items-center justify-center rounded-full bg-blue-600 text-white h-7 w-7 hover:bg-blue-700 transition-colors disabled:opacity-60 shrink-0"
              >
                {creatingVariant ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
              </button>
            </form>
          </div>

          {selectedVariant ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Pencil className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                <input
                  type="text"
                  value={variantNameDraft}
                  onChange={(e) => setVariantNameDraft(e.target.value)}
                  onBlur={saveVariantName}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                  className="flex-1 min-w-[8rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
                />
                {savingVariantName && <Loader2 className="h-3.5 w-3.5 text-gray-400 animate-spin shrink-0" />}
                <button
                  onClick={archiveVariant}
                  disabled={archivingVariant}
                  title="Archive this variant"
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-200 text-gray-500 hover:text-red-600 hover:border-red-200 text-xs px-2.5 py-1.5 transition-colors disabled:opacity-60 shrink-0"
                >
                  {archivingVariant ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  Archive
                </button>
              </div>
              {saveVariantNameError && <p className="text-[11px] text-red-500 mb-2">{saveVariantNameError}</p>}
              {archiveVariantError && <p className="text-[11px] text-red-500 mb-2">{archiveVariantError}</p>}
              <CharacterImageBuilder
                description={variantDescriptionDraft}
                onDescriptionChange={setVariantDescriptionDraft}
                descriptionPlaceholder={`How this variant looks, e.g. "She is Kumar's wife, elegant, from high society" or "Same friendly personality, Chinese heritage."`}
                cultureTag={{ value: variantCultureTagDraft, onChange: setVariantCultureTagDraft }}
                referencePhotoUrl={selectedVariant.reference_image_url}
                referenceUploadUrl={`/api/culturetoons/variants/${selectedVariant.id}/reference-image`}
                portraitUrl={selectedVariant.image_url}
                portraitUploadUrl={`/api/culturetoons/variants/${selectedVariant.id}/image`}
                extraFields={{ brand_id: brandId }}
                onReferenceUploaded={(data) => setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? { ...v, ...data } as CharacterVariant : v)))}
                onPortraitUploaded={(data) => setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? { ...v, ...data } as CharacterVariant : v)))}
                onGenerate={generateVariantImage}
                generating={generatingVariantImage}
                error={variantImageGenError}
                warning={variantImageGenWarning}
                helperText={
                  selectedVariant.reference_image_url
                    ? "Grounded on this variant's own reference photo."
                    : `No reference photo of its own — generation stays visually connected to ${selectedCharacter.name} while following this description for who the variant actually is (gender, ethnicity, etc.).`
                }
              />
            </div>
          ) : (
            <p className="text-xs text-gray-400">Name a variant above, or skip this if {selectedCharacter.name} doesn&apos;t need one.</p>
          )}
        </div>
      )}
    </div>
  );
}
