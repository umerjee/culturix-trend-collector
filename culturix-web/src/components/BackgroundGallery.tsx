"use client";

import { useState } from "react";
import { Plus, Loader2, Trash2 } from "lucide-react";
import type { ToonBackground } from "@/lib/types";
import ImageUploadButton from "@/components/ImageUploadButton";

interface Props {
  initialBackgrounds: ToonBackground[];
}

export default function BackgroundGallery({ initialBackgrounds }: Props) {
  const [backgrounds, setBackgrounds] = useState(initialBackgrounds);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  async function addBackground(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const res = await fetch("/api/culturetoons/backgrounds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim() }),
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

  async function removeBackground(id: string) {
    setBackgrounds((prev) => prev.filter((b) => b.id !== id));
    await fetch(`/api/culturetoons/backgrounds/${id}`, { method: "DELETE" });
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
      <form onSubmit={addBackground} className="flex gap-2 max-w-xs">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="New background name"
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
