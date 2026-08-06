"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, CheckCircle2, XCircle, Sparkles, ChevronDown, ChevronRight } from "lucide-react";
import type { Character, CharacterVariant, VoiceProvider } from "@/lib/types";
import CharacterImageBuilder from "@/components/CharacterImageBuilder";
import ExpressionUploadGrid from "@/components/ExpressionUploadGrid";

interface Props {
  brandId: string;
  hasElevenLabsKey: boolean;
  initialCharacters: Character[];
  initialVariants: CharacterVariant[];
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

export default function CharacterVariantManager({ brandId, hasElevenLabsKey, initialCharacters, initialVariants, focusVariantId }: Props) {
  const [characters, setCharacters] = useState(initialCharacters);
  const [variants, setVariants] = useState(initialVariants);
  const focusedVariant = focusVariantId ? initialVariants.find((v) => v.id === focusVariantId) : null;
  const [selectedCharacterId, setSelectedCharacterId] = useState<string | null>(
    focusedVariant?.character_id ?? characters[0]?.id ?? null
  );
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(focusedVariant?.id ?? null);

  useEffect(() => {
    if (!focusVariantId) return;
    const variant = variants.find((v) => v.id === focusVariantId);
    if (!variant) return;
    setSelectedCharacterId(variant.character_id);
    setSelectedVariantId(variant.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusVariantId]);

  const [newCharacterName, setNewCharacterName] = useState("");
  const [creatingCharacter, setCreatingCharacter] = useState(false);
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [artStyleDraft, setArtStyleDraft] = useState<Character["art_style"]>("cartoon_3d");
  const [generatingImage, setGeneratingImage] = useState(false);
  const [imageGenError, setImageGenError] = useState<string | null>(null);

  const [newVariantName, setNewVariantName] = useState("");
  const [creatingVariant, setCreatingVariant] = useState(false);
  const [voiceProvider, setVoiceProvider] = useState<VoiceProvider>("kling");
  const [registering, setRegistering] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const [variantDescriptionDraft, setVariantDescriptionDraft] = useState("");
  const [variantCultureTagDraft, setVariantCultureTagDraft] = useState("");
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
    setVariantCultureTagDraft(selectedVariant?.culture_tag ?? "");
    setVariantImageGenError(null);
    setAdvancedOpen(!!selectedVariant?.image_url);
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
        const data = await res.json();
        // The backend auto-creates a variant named after the character
        // (default_variant) — without this, a character with zero variants
        // has no "Register for video" step reachable anywhere (that step
        // only exists per-variant), which left a real user stuck with no
        // way to register their base character at all.
        const { default_variant, ...character } = data;
        setCharacters((prev) => [...prev, character as Character]);
        if (default_variant) setVariants((prev) => [...prev, default_variant as CharacterVariant]);
        setSelectedCharacterId(character.id);
        setSelectedVariantId(default_variant?.id ?? null);
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
      setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? (data as CharacterVariant) : v)));
    } finally {
      setGeneratingVariantImage(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Step 1 — base character */}
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Step 1 · Base character</h3>
        <p className="text-xs text-gray-400 mb-3">Name it, describe how it should look, pick an art style, then generate.</p>

        <div className="flex flex-wrap items-center gap-2 mb-4">
          {characters.map((c) => (
            <button
              key={c.id}
              onClick={() => { setSelectedCharacterId(c.id); setSelectedVariantId(null); }}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                c.id === selectedCharacterId ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {c.name}
            </button>
          ))}
          <form onSubmit={addCharacter} className="flex gap-1">
            <input
              type="text"
              value={newCharacterName}
              onChange={(e) => setNewCharacterName(e.target.value)}
              placeholder="New character name"
              className="rounded-full border border-gray-200 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200 w-40"
            />
            <button
              type="submit"
              disabled={creatingCharacter || !newCharacterName.trim()}
              className="inline-flex items-center justify-center rounded-full bg-blue-600 text-white h-7 w-7 hover:bg-blue-700 transition-colors disabled:opacity-60 shrink-0"
            >
              {creatingCharacter ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            </button>
          </form>
        </div>

        {selectedCharacter ? (
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
            onPortraitUploaded={(data) => setCharacters((prev) => prev.map((c) => (c.id === selectedCharacter.id ? { ...c, ...data } as Character : c)))}
            onGenerate={generateCharacterImage}
            generating={generatingImage}
            error={imageGenError}
            helperText="A reference photo is optional — with one, generation is grounded on your photo's likeness but always re-illustrated in the chosen style. Regenerate as many times as you like to refine it."
          />
        ) : (
          <p className="text-xs text-gray-400">Name a character above to get started.</p>
        )}
      </div>

      {/* Step 2 — cultural variants */}
      {selectedCharacter && (
        <div className="rounded-2xl bg-white border border-gray-100 p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-1">Step 2 · Cultural variants of {selectedCharacter.name}</h3>
          <p className="text-xs text-gray-400 mb-3">
            Related characters for different scenarios — e.g. &quot;Wife&quot;, &quot;Aunty&quot;, &quot;Chinese version&quot;. Each one stays
            visually connected to {selectedCharacter.name} unless it has its own reference photo.
          </p>

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
                helperText={
                  selectedVariant.reference_image_url
                    ? "Grounded on this variant's own reference photo."
                    : `No reference photo of its own — generation stays visually connected to ${selectedCharacter.name} while following this description for who the variant actually is (gender, ethnicity, etc.).`
                }
              />

              <div className="rounded-xl border border-gray-100">
                <button
                  onClick={() => setAdvancedOpen((v) => !v)}
                  className="w-full flex items-center justify-between px-3 py-2.5 text-xs font-semibold text-gray-700"
                >
                  <span className="flex items-center gap-1.5">
                    {advancedOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                    Step 3 · Register for video &amp; add expressions
                  </span>
                  <ElementStatusIcon status={selectedVariant.element_status} />
                </button>
                {advancedOpen && (
                  <div className="px-3 pb-3 space-y-4">
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
                        <p className="text-[11px] text-gray-400 mt-1.5">Build a variant image above first.</p>
                      )}
                    </div>

                    <ExpressionUploadGrid
                      key={selectedVariant.id} brandId={brandId} variantId={selectedVariant.id}
                      hasPortrait={!!selectedVariant.image_url}
                    />
                  </div>
                )}
              </div>
            </div>
          ) : (
            <p className="text-xs text-gray-400">Name a variant above, or skip this if {selectedCharacter.name} doesn&apos;t need one.</p>
          )}
        </div>
      )}
    </div>
  );
}
