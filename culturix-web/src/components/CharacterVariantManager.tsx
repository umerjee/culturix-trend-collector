"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, CheckCircle2, XCircle, Sparkles, Wand2 } from "lucide-react";
import type { Character, CharacterVariant, VoiceProvider } from "@/lib/types";
import { ART_STYLES } from "@/lib/types";
import ImageUploadButton from "@/components/ImageUploadButton";
import ExpressionUploadGrid from "@/components/ExpressionUploadGrid";

interface Props {
  brandId: string;
  hasElevenLabsKey: boolean;
  initialCharacters: Character[];
  initialVariants: CharacterVariant[];
}

export default function CharacterVariantManager({ brandId, hasElevenLabsKey, initialCharacters, initialVariants }: Props) {
  const [characters, setCharacters] = useState(initialCharacters);
  const [variants, setVariants] = useState(initialVariants);
  const [selectedCharacterId, setSelectedCharacterId] = useState<string | null>(characters[0]?.id ?? null);
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(null);

  const [newCharacterName, setNewCharacterName] = useState("");
  const [creatingCharacter, setCreatingCharacter] = useState(false);
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [artStyleDraft, setArtStyleDraft] = useState<(typeof ART_STYLES)[number]["key"]>("cartoon_3d");
  const [generatingImage, setGeneratingImage] = useState(false);
  const [imageGenError, setImageGenError] = useState<string | null>(null);

  const [newVariantName, setNewVariantName] = useState("");
  const [newVariantCulture, setNewVariantCulture] = useState("");
  const [newVariantDescription, setNewVariantDescription] = useState("");
  const [creatingVariant, setCreatingVariant] = useState(false);
  const [voiceProvider, setVoiceProvider] = useState<VoiceProvider>("kling");
  const [registering, setRegistering] = useState(false);

  const [variantDescriptionDraft, setVariantDescriptionDraft] = useState("");
  const [generatingVariantImage, setGeneratingVariantImage] = useState(false);
  const [variantImageGenError, setVariantImageGenError] = useState<string | null>(null);

  const selectedCharacter = characters.find((c) => c.id === selectedCharacterId) ?? null;
  const characterVariants = variants.filter((v) => v.character_id === selectedCharacterId);
  const selectedVariant = variants.find((v) => v.id === selectedVariantId) ?? null;

  // Poll while a variant's element registration is in flight.
  useEffect(() => {
    if (!selectedVariant || selectedVariant.element_status !== "pending") return;
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
  }, [selectedCharacterId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setVariantDescriptionDraft(selectedVariant?.description ?? "");
    setVariantImageGenError(null);
  }, [selectedVariantId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function addCharacter(e: React.FormEvent) {
    e.preventDefault();
    if (!newCharacterName.trim()) return;
    setCreatingCharacter(true);
    try {
      const res = await fetch("/api/culturetoons/characters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, name: newCharacterName.trim() }),
      });
      if (res.ok) {
        const character = await res.json();
        setCharacters((prev) => [...prev, character]);
        setSelectedCharacterId(character.id);
        setNewCharacterName("");
      }
    } finally {
      setCreatingCharacter(false);
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
        body: JSON.stringify({
          brand_id: brandId,
          character_id: selectedCharacterId,
          name: newVariantName.trim(),
          culture_tag: newVariantCulture.trim() || undefined,
          description: newVariantDescription.trim() || undefined,
        }),
      });
      if (res.ok) {
        const variant = await res.json();
        setVariants((prev) => [...prev, variant]);
        setSelectedVariantId(variant.id);
        setNewVariantName("");
        setNewVariantCulture("");
        setNewVariantDescription("");
      }
    } finally {
      setCreatingVariant(false);
    }
  }

  async function registerElement() {
    if (!selectedVariant) return;
    setRegistering(true);
    try {
      await fetch(`/api/culturetoons/variants/${selectedVariant.id}/register-element`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, voice_provider: voiceProvider }),
      });
      setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? { ...v, element_status: "pending" } : v)));
    } finally {
      setRegistering(false);
    }
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
    try {
      const res = await fetch(`/api/culturetoons/variants/${selectedVariant.id}/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, description: variantDescriptionDraft.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setVariantImageGenError(typeof data.detail === "string" ? data.detail : "Image generation failed");
        return;
      }
      setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? (data as CharacterVariant) : v)));
    } finally {
      setGeneratingVariantImage(false);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Characters column */}
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Base characters</h3>
        <div className="space-y-1 mb-3">
          {characters.length === 0 && (
            <p className="text-xs text-gray-400">No characters yet — add your first base character below.</p>
          )}
          {characters.map((c) => (
            <button
              key={c.id}
              onClick={() => { setSelectedCharacterId(c.id); setSelectedVariantId(null); }}
              className={`w-full text-left rounded-lg px-3 py-2 text-sm transition-colors ${
                c.id === selectedCharacterId ? "bg-blue-50 text-blue-600 font-medium" : "text-gray-600 hover:bg-gray-50"
              }`}
            >
              {c.name}
            </button>
          ))}
        </div>
        <form onSubmit={addCharacter} className="flex gap-2">
          <input
            type="text"
            value={newCharacterName}
            onChange={(e) => setNewCharacterName(e.target.value)}
            placeholder="New base character name"
            className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <button
            type="submit"
            disabled={creatingCharacter || !newCharacterName.trim()}
            className="rounded-lg bg-blue-600 text-white px-2.5 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60 shrink-0"
          >
            {creatingCharacter ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          </button>
        </form>
        <p className="text-[11px] text-gray-400 mt-2">
          Name it first, then build its look — description, art style, and photo — once it&apos;s selected.
        </p>
      </div>

      {/* Variants column */}
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Cultural variants</h3>
        {!selectedCharacter ? (
          <p className="text-xs text-gray-400">Select a base character to see its variants.</p>
        ) : (
          <>
            <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 mb-4">
              <span className="text-xs font-semibold text-gray-700 block mb-2">Build character image</span>
              <textarea
                value={descriptionDraft}
                onChange={(e) => setDescriptionDraft(e.target.value)}
                placeholder="Describe the character — appearance, age, culture, personality, style. E.g. &quot;A cheerful Nigerian uncle in his 50s, round glasses, colorful agbada, warm expressive face.&quot;"
                rows={3}
                className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs mb-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
              <label className="block text-[11px] font-medium text-gray-500 mb-1">Character type / art style</label>
              <select
                value={artStyleDraft}
                onChange={(e) => setArtStyleDraft(e.target.value as (typeof ART_STYLES)[number]["key"])}
                className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs mb-2"
              >
                {ART_STYLES.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
              <div className="flex items-center gap-3 mb-2">
                <ImageUploadButton
                  uploadUrl={`/api/culturetoons/characters/${selectedCharacter.id}/reference-image`}
                  currentImageUrl={selectedCharacter.reference_image_url}
                  label="Reference photo"
                  size="sm"
                  extraFields={{ brand_id: brandId }}
                  onUploaded={(data) => {
                    setCharacters((prev) => prev.map((c) => (c.id === selectedCharacter.id ? { ...c, ...data } as Character : c)));
                  }}
                />
                <button
                  onClick={generateCharacterImage}
                  disabled={generatingImage || !descriptionDraft.trim()}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60 shrink-0"
                >
                  {generatingImage ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
                  {selectedCharacter.base_image_url ? "Regenerate image" : "Generate image"}
                </button>
              </div>
              {imageGenError && <p className="text-[11px] text-red-500 mb-2">{imageGenError}</p>}
              <p className="text-[11px] text-gray-400 mb-3">
                A reference photo is optional — with one, generation is grounded on your photo&apos;s
                likeness but always re-illustrated in the chosen style, never a lightly-edited copy of
                the photo. Regenerate as many times as you like to refine it — each run replaces the
                current portrait.
              </p>
              <div className="flex justify-center">
                <ImageUploadButton
                  uploadUrl={`/api/culturetoons/characters/${selectedCharacter.id}/image`}
                  currentImageUrl={selectedCharacter.base_image_url}
                  label="Character portrait"
                  extraFields={{ brand_id: brandId }}
                  onUploaded={(data) => {
                    setCharacters((prev) => prev.map((c) => (c.id === selectedCharacter.id ? { ...c, ...data } as Character : c)));
                  }}
                />
              </div>
            </div>
            <div className="space-y-1 mb-3">
              {characterVariants.length === 0 && (
                <p className="text-xs text-gray-400">No variants yet — e.g. &quot;Indian Mom&quot;, &quot;Nigerian Uncle&quot;, &quot;Wife&quot;, &quot;Aunty&quot;.</p>
              )}
              {characterVariants.map((v) => (
                <button
                  key={v.id}
                  onClick={() => setSelectedVariantId(v.id)}
                  className={`w-full text-left rounded-lg px-3 py-2 text-sm transition-colors flex items-center justify-between gap-2 ${
                    v.id === selectedVariantId ? "bg-blue-50 text-blue-600 font-medium" : "text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  <span>
                    {v.name}
                    {v.culture_tag && <span className="text-gray-400 font-normal"> · {v.culture_tag}</span>}
                  </span>
                  {v.element_status === "ready" && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />}
                  {v.element_status === "pending" && <Loader2 className="h-3.5 w-3.5 text-amber-500 animate-spin shrink-0" />}
                  {v.element_status === "failed" && <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />}
                </button>
              ))}
            </div>
            <form onSubmit={addVariant} className="flex flex-col gap-2">
              <input
                type="text"
                value={newVariantName}
                onChange={(e) => setNewVariantName(e.target.value)}
                placeholder="Variant name, e.g. Wife, Aunty, Indian Mom"
                className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
              <input
                type="text"
                value={newVariantCulture}
                onChange={(e) => setNewVariantCulture(e.target.value)}
                placeholder="Culture tag, e.g. indian (optional)"
                className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
              <textarea
                value={newVariantDescription}
                onChange={(e) => setNewVariantDescription(e.target.value)}
                placeholder="How this variant relates to the base character, e.g. &quot;Kumar's wife — warm, stylish, same cartoon universe&quot; (optional, can add later)"
                rows={2}
                className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
              <button
                type="submit"
                disabled={creatingVariant || !newVariantName.trim()}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60"
              >
                {creatingVariant ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                Add variant
              </button>
            </form>
          </>
        )}
      </div>

      {/* Build variant image + Kling registration + expressions column */}
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Build &amp; register this variant</h3>
        {!selectedVariant ? (
          <p className="text-xs text-gray-400">Select a variant to build its image, register it, and add expressions.</p>
        ) : (
          <>
            <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 mb-4">
              <span className="text-xs font-semibold text-gray-700 block mb-2">Build variant image</span>
              <textarea
                value={variantDescriptionDraft}
                onChange={(e) => setVariantDescriptionDraft(e.target.value)}
                placeholder={`How this variant looks/relates to ${selectedCharacter?.name ?? "the base character"}, e.g. "Kumar's wife, warm and stylish" or "Asian look, same personality."`}
                rows={3}
                className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs mb-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
              <div className="flex items-center gap-3 mb-2">
                <ImageUploadButton
                  uploadUrl={`/api/culturetoons/variants/${selectedVariant.id}/reference-image`}
                  currentImageUrl={selectedVariant.reference_image_url}
                  label="Reference photo"
                  size="sm"
                  extraFields={{ brand_id: brandId }}
                  onUploaded={(data) => {
                    setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? { ...v, ...data } as CharacterVariant : v)));
                  }}
                />
                <button
                  onClick={generateVariantImage}
                  disabled={generatingVariantImage || !variantDescriptionDraft.trim()}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60 shrink-0"
                >
                  {generatingVariantImage ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
                  {selectedVariant.image_url ? "Regenerate image" : "Generate image"}
                </button>
              </div>
              {variantImageGenError && <p className="text-[11px] text-red-500 mb-2">{variantImageGenError}</p>}
              <p className="text-[11px] text-gray-400 mb-3">
                {selectedVariant.reference_image_url
                  ? "Grounded on this variant's own reference photo."
                  : `No reference photo of its own — generation grounds on ${selectedCharacter?.name ?? "the base character"}'s portrait instead, so this variant stays visually consistent with the rest of the roster.`}{" "}
                Regenerate as many times as you like to refine it.
              </p>
              <div className="flex justify-center">
                <ImageUploadButton
                  uploadUrl={`/api/culturetoons/variants/${selectedVariant.id}/image`}
                  currentImageUrl={selectedVariant.image_url}
                  label="Variant portrait"
                  extraFields={{ brand_id: brandId }}
                  onUploaded={(data) => {
                    setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? { ...v, ...data } as CharacterVariant : v)));
                  }}
                />
              </div>
            </div>

            <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 mb-4">
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
                  <option value="kling">Kling native voice</option>
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
              {!selectedVariant.image_url && (
                <p className="text-[11px] text-gray-400 mt-1.5">Build or upload a variant image above first.</p>
              )}
            </div>

            <ExpressionUploadGrid key={selectedVariant.id} brandId={brandId} variantId={selectedVariant.id} />
          </>
        )}
      </div>
    </div>
  );
}
