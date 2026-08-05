"use client";

import { useState } from "react";
import { Drama, Loader2 } from "lucide-react";
import type { CharacterBrand } from "@/lib/types";

interface Props {
  onCreated: (brand: CharacterBrand) => void;
}

export default function CultureToonBrandForm({ onCreated }: Props) {
  const [name, setName] = useState("My CultureToons Brand");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/culturetoons/brands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Failed to create brand");
        return;
      }
      onCreated(data);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-2xl border-2 border-dashed border-gray-200 py-16 px-6 text-center">
      <Drama className="h-10 w-10 text-gray-300 mx-auto mb-4" />
      <h3 className="font-semibold text-gray-700 mb-2">Create a CultureToons brand</h3>
      <p className="text-sm text-gray-400 max-w-sm mx-auto mb-5">
        A brand is one "toon account" — e.g. Funny Clips, Baby Videos, Tech Updates. You can
        create several and manage them all from here; each gets its own characters, backgrounds,
        scripts, and connected social accounts.
      </p>
      <form onSubmit={create} className="flex flex-col gap-2 max-w-sm mx-auto text-left">
        <label className="text-xs font-medium text-gray-500">Brand name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        <label className="text-xs font-medium text-gray-500 mt-2">Description (optional)</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        {error && <p className="text-xs text-red-500">{error}</p>}
        <button
          type="submit"
          disabled={submitting || !name.trim()}
          className="mt-3 rounded-lg bg-blue-600 text-white text-sm font-medium px-4 py-2 hover:bg-blue-700 transition-colors disabled:opacity-60 inline-flex items-center justify-center gap-1.5"
        >
          {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Create brand
        </button>
      </form>
    </div>
  );
}
