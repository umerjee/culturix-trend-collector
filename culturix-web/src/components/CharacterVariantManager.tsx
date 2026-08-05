"use client";

import { useState } from "react";
import { Plus, Loader2 } from "lucide-react";
import type { Character, CharacterVariant } from "@/lib/types";
import ImageUploadButton from "@/components/ImageUploadButton";
import ExpressionUploadGrid from "@/components/ExpressionUploadGrid";

interface Props {
  initialCharacters: Character[];
  initialVariants: CharacterVariant[];
}

export default function CharacterVariantManager({ initialCharacters, initialVariants }: Props) {
  const [characters, setCharacters] = useState(initialCharacters);
  const [variants, setVariants] = useState(initialVariants);
  const [selectedCharacterId, setSelectedCharacterId] = useState<string | null>(characters[0]?.id ?? null);
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(null);

  const [newCharacterName, setNewCharacterName] = useState("");
  const [creatingCharacter, setCreatingCharacter] = useState(false);
  const [newVariantName, setNewVariantName] = useState("");
  const [newVariantCulture, setNewVariantCulture] = useState("");
  const [creatingVariant, setCreatingVariant] = useState(false);

  const selectedCharacter = characters.find((c) => c.id === selectedCharacterId) ?? null;
  const characterVariants = variants.filter((v) => v.character_id === selectedCharacterId);
  const selectedVariant = variants.find((v) => v.id === selectedVariantId) ?? null;

  async function addCharacter(e: React.FormEvent) {
    e.preventDefault();
    if (!newCharacterName.trim()) return;
    setCreatingCharacter(true);
    try {
      const res = await fetch("/api/culturetoons/characters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newCharacterName.trim() }),
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
          character_id: selectedCharacterId,
          name: newVariantName.trim(),
          culture_tag: newVariantCulture.trim() || undefined,
        }),
      });
      if (res.ok) {
        const variant = await res.json();
        setVariants((prev) => [...prev, variant]);
        setSelectedVariantId(variant.id);
        setNewVariantName("");
        setNewVariantCulture("");
      }
    } finally {
      setCreatingVariant(false);
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
      </div>

      {/* Variants column */}
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Cultural variants</h3>
        {!selectedCharacter ? (
          <p className="text-xs text-gray-400">Select a base character to see its variants.</p>
        ) : (
          <>
            <div className="flex justify-center mb-3">
              <ImageUploadButton
                uploadUrl={`/api/culturetoons/characters/${selectedCharacter.id}/image`}
                currentImageUrl={selectedCharacter.base_image_url}
                label="Base image"
                onUploaded={(data) => {
                  setCharacters((prev) => prev.map((c) => (c.id === selectedCharacter.id ? { ...c, ...data } as Character : c)));
                }}
              />
            </div>
            <div className="space-y-1 mb-3">
              {characterVariants.length === 0 && (
                <p className="text-xs text-gray-400">No variants yet — e.g. &quot;Indian Mom&quot;, &quot;Nigerian Uncle&quot;.</p>
              )}
              {characterVariants.map((v) => (
                <button
                  key={v.id}
                  onClick={() => setSelectedVariantId(v.id)}
                  className={`w-full text-left rounded-lg px-3 py-2 text-sm transition-colors ${
                    v.id === selectedVariantId ? "bg-blue-50 text-blue-600 font-medium" : "text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  {v.name}
                  {v.culture_tag && <span className="text-gray-400 font-normal"> · {v.culture_tag}</span>}
                </button>
              ))}
            </div>
            <form onSubmit={addVariant} className="flex flex-col gap-2">
              <input
                type="text"
                value={newVariantName}
                onChange={(e) => setNewVariantName(e.target.value)}
                placeholder="Variant name, e.g. Indian Mom"
                className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newVariantCulture}
                  onChange={(e) => setNewVariantCulture(e.target.value)}
                  placeholder="Culture tag, e.g. indian"
                  className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
                />
                <button
                  type="submit"
                  disabled={creatingVariant || !newVariantName.trim()}
                  className="rounded-lg bg-blue-600 text-white px-2.5 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60 shrink-0"
                >
                  {creatingVariant ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                </button>
              </div>
            </form>
          </>
        )}
      </div>

      {/* Expressions column */}
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Expressions</h3>
        {!selectedVariant ? (
          <p className="text-xs text-gray-400">Select a variant to upload its 10 reusable expressions.</p>
        ) : (
          <>
            <div className="flex justify-center mb-4">
              <ImageUploadButton
                uploadUrl={`/api/culturetoons/variants/${selectedVariant.id}/image`}
                currentImageUrl={selectedVariant.image_url}
                label="Variant image"
                onUploaded={(data) => {
                  setVariants((prev) => prev.map((v) => (v.id === selectedVariant.id ? { ...v, ...data } as CharacterVariant : v)));
                }}
              />
            </div>
            <ExpressionUploadGrid key={selectedVariant.id} variantId={selectedVariant.id} />
          </>
        )}
      </div>
    </div>
  );
}
