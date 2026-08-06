"use client";

import { useState } from "react";
import { Plus, Loader2, Trash2, Wand2 } from "lucide-react";
import type { ToonBackground } from "@/lib/types";
import { ART_STYLES } from "@/lib/types";
import ImageUploadButton from "@/components/ImageUploadButton";

interface Props {
  brandId: string;
  initialBackgrounds: ToonBackground[];
}

const DEFAULT_BACKGROUND_STYLE = "cinematic_cultural";

export default function BackgroundGallery({ brandId, initialBackgrounds }: Props) {
  const [backgrounds, setBackgrounds] = useState(initialBackgrounds);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const [genName, setGenName] = useState("");
  const [genDescription, setGenDescription] = useState("");
  const [genStyle, setGenStyle] = useState<string>(DEFAULT_BACKGROUND_STYLE);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  async function addBackground(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const res = await fetch("/api/culturetoons/backgrounds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, name: newName.trim() }),
      });
      if (res.ok) {
        const created = await res.json();
        setBackgrounds((prev) => [...prev, created]);
        setNewName("");
      }
    } finally {
      setCreating(false);
    }
  }

  async function generateBackground(e: React.FormEvent) {
    e.preventDefault();
    if (!genDescription.trim()) return;
    setGenerating(true);
    setGenError(null);
    try {
      const res = await fetch("/api/culturetoons/backgrounds/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_id: brandId,
          description: genDescription.trim(),
          name: genName.trim() || undefined,
          art_style: genStyle,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setGenError(typeof data.detail === "string" ? data.detail : "Background generation failed");
        return;
      }
      setBackgrounds((prev) => [...prev, data as ToonBackground]);
      setGenName("");
      setGenDescription("");
    } finally {
      setGenerating(false);
    }
  }

  async function removeBackground(id: string) {
    setBackgrounds((prev) => prev.filter((b) => b.id !== id));
    await fetch(`/api/culturetoons/backgrounds/${id}?brand_id=${brandId}`, { method: "DELETE" });
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-400">
        Reusable backgrounds — build 5-10 and rotate them across characters rather than making a new one every time.
      </p>
      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-4">
        {backgrounds.map((bg) => (
          <div key={bg.id} className="flex flex-col items-center gap-1">
            <div className="relative">
              <ImageUploadButton
                uploadUrl={`/api/culturetoons/backgrounds/${bg.id}/image`}
                currentImageUrl={bg.image_url}
                extraFields={{ brand_id: brandId }}
                onUploaded={(data) => {
                  setBackgrounds((prev) => prev.map((b) => (b.id === bg.id ? { ...b, ...data } as ToonBackground : b)));
                }}
              />
              <button
                type="button"
                onClick={() => removeBackground(bg.id)}
                title="Remove background"
                className="absolute -top-1.5 -right-1.5 h-5 w-5 rounded-full bg-white border border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-200 flex items-center justify-center transition-colors"
              >
                <Trash2 className="h-2.5 w-2.5" />
              </button>
            </div>
            <span className="text-xs text-gray-600 text-center truncate max-w-[7rem]">{bg.name}</span>
          </div>
        ))}
      </div>
      <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 max-w-xl">
        <p className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
          <Wand2 className="h-3.5 w-3.5 text-blue-500" /> Generate a background
        </p>
        <form onSubmit={generateBackground} className="flex flex-col gap-2">
          <textarea
            value={genDescription}
            onChange={(e) => setGenDescription(e.target.value)}
            placeholder={`Describe the scene, e.g. "An Indian wedding mandap decorated with marigold garlands and string lights, festive but empty of people"`}
            rows={2}
            className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <div className="flex flex-wrap gap-2 items-center">
            <input
              type="text"
              value={genName}
              onChange={(e) => setGenName(e.target.value)}
              placeholder="Name (optional)"
              className="flex-1 min-w-[8rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
            />
            <select
              value={genStyle}
              onChange={(e) => setGenStyle(e.target.value)}
              className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
            >
              {ART_STYLES.map((style) => (
                <option key={style.key} value={style.key}>{style.label}</option>
              ))}
            </select>
            <button
              type="submit"
              disabled={generating || !genDescription.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60 shrink-0"
            >
              {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
              Generate
            </button>
          </div>
          {genError && <p className="text-[11px] text-red-500">{genError}</p>}
        </form>
      </div>

      <form onSubmit={addBackground} className="flex gap-2 max-w-xs">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="Or add a name and upload your own image"
          className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        <button
          type="submit"
          disabled={creating || !newName.trim()}
          className="rounded-lg bg-blue-600 text-white px-2.5 py-1.5 hover:bg-blue-700 transition-colors disabled:opacity-60 shrink-0"
        >
          {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
        </button>
      </form>
    </div>
  );
}
