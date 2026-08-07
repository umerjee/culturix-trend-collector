"use client";

import { useState } from "react";
import { Plus, Loader2, Trash2, Wand2, MapPin } from "lucide-react";
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
  const [newCountry, setNewCountry] = useState("");
  const [creating, setCreating] = useState(false);

  const [genName, setGenName] = useState("");
  const [genDescription, setGenDescription] = useState("");
  const [genStyle, setGenStyle] = useState<string>(DEFAULT_BACKGROUND_STYLE);
  const [genCountry, setGenCountry] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  // Which location's reference-image gallery is expanded — collapsed by
  // default so the grid stays compact when there are many locations.
  const [expandedId, setExpandedId] = useState<string | null>(null);

  async function addBackground(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const res = await fetch("/api/culturetoons/backgrounds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, name: newName.trim(), country: newCountry.trim() || undefined }),
      });
      if (res.ok) {
        const created = await res.json();
        setBackgrounds((prev) => [...prev, created]);
        setNewName("");
        setNewCountry("");
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
          country: genCountry.trim() || undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setGenError(typeof data.detail === "string" ? data.detail : "Location generation failed");
        return;
      }
      setBackgrounds((prev) => [...prev, data as ToonBackground]);
      setGenName("");
      setGenDescription("");
      setGenCountry("");
    } finally {
      setGenerating(false);
    }
  }

  async function removeBackground(id: string) {
    setBackgrounds((prev) => prev.filter((b) => b.id !== id));
    await fetch(`/api/culturetoons/backgrounds/${id}?brand_id=${brandId}`, { method: "DELETE" });
  }

  async function removeReferenceImage(backgroundId: string, imageUrl: string) {
    setBackgrounds((prev) => prev.map((b) => (
      b.id === backgroundId ? { ...b, reference_image_urls: b.reference_image_urls.filter((u) => u !== imageUrl) } : b
    )));
    await fetch(
      `/api/culturetoons/backgrounds/${backgroundId}/reference-images?brand_id=${brandId}&image_url=${encodeURIComponent(imageUrl)}`,
      { method: "DELETE" },
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-400">
        Reusable locations — build 5-10 and rotate them across characters rather than making a new one every
        time. Click a location to add extra reference angles (e.g. a second room, or a different view of the
        same street) alongside its primary image.
      </p>
      {backgrounds.length === 0 && (
        <p className="text-xs text-gray-400">
          No locations yet — optional. Generate one below, or skip this and toons will just have no
          background set (still fine).
        </p>
      )}
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
                title="Remove location"
                className="absolute -top-1.5 -right-1.5 h-5 w-5 rounded-full bg-white border border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-200 flex items-center justify-center transition-colors"
              >
                <Trash2 className="h-2.5 w-2.5" />
              </button>
            </div>
            <button
              type="button"
              onClick={() => setExpandedId((prev) => (prev === bg.id ? null : bg.id))}
              className="text-xs text-gray-600 hover:text-blue-600 text-center truncate max-w-[7rem]"
            >
              {bg.name}
            </button>
            {bg.country && (
              <span className="inline-flex items-center gap-0.5 text-[10px] text-gray-400">
                <MapPin className="h-2.5 w-2.5" /> {bg.country}
              </span>
            )}
          </div>
        ))}
      </div>

      {expandedId && (() => {
        const bg = backgrounds.find((b) => b.id === expandedId);
        if (!bg) return null;
        return (
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 max-w-xl">
            <p className="text-xs font-semibold text-gray-700 mb-2">{bg.name} — reference angles</p>
            <div className="flex flex-wrap gap-3">
              {bg.reference_image_urls.map((url) => (
                <div key={url} className="relative">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={url} alt="Reference angle" className="h-16 w-16 rounded-lg object-cover border border-gray-200" />
                  <button
                    type="button"
                    onClick={() => removeReferenceImage(bg.id, url)}
                    title="Remove this angle"
                    className="absolute -top-1.5 -right-1.5 h-5 w-5 rounded-full bg-white border border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-200 flex items-center justify-center transition-colors"
                  >
                    <Trash2 className="h-2.5 w-2.5" />
                  </button>
                </div>
              ))}
              <ImageUploadButton
                uploadUrl={`/api/culturetoons/backgrounds/${bg.id}/reference-images`}
                currentImageUrl={null}
                size="sm"
                label="Add angle"
                extraFields={{ brand_id: brandId }}
                onUploaded={(data) => {
                  setBackgrounds((prev) => prev.map((b) => (b.id === bg.id ? { ...b, ...data } as ToonBackground : b)));
                }}
              />
            </div>
          </div>
        );
      })()}

      <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 max-w-xl">
        <p className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
          <Wand2 className="h-3.5 w-3.5 text-blue-500" /> Generate a location
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
            <input
              type="text"
              value={genCountry}
              onChange={(e) => setGenCountry(e.target.value)}
              placeholder="Country (optional)"
              className="w-32 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
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
          <p className="text-[11px] text-gray-400">{ART_STYLES.find((s) => s.key === genStyle)?.hint}</p>
          {genError && <p className="text-[11px] text-red-500">{genError}</p>}
        </form>
      </div>

      <form onSubmit={addBackground} className="flex gap-2 max-w-xl">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="Or add a name and upload your own image"
          className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        <input
          type="text"
          value={newCountry}
          onChange={(e) => setNewCountry(e.target.value)}
          placeholder="Country (optional)"
          className="w-32 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
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
