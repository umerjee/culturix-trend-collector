"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, Trash2, BookOpen } from "lucide-react";
import type { CharacterMemory } from "@/lib/types";
import { MEMORY_TYPES } from "@/lib/types";

interface Props {
  brandId: string;
  variantId: string;
}

export default function MemoryManager({ brandId, variantId }: Props) {
  const [memories, setMemories] = useState<CharacterMemory[]>([]);
  const [loading, setLoading] = useState(true);
  const [memoryType, setMemoryType] = useState<(typeof MEMORY_TYPES)[number]>("running_gag");
  const [content, setContent] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(`/api/culturetoons/variants/${variantId}/memories?brand_id=${brandId}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => { if (!cancelled) setMemories(data); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [variantId, brandId]);

  async function addMemory(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;
    setCreating(true);
    try {
      const res = await fetch(`/api/culturetoons/variants/${variantId}/memories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, memory_type: memoryType, content: content.trim() }),
      });
      if (res.ok) {
        const data = await res.json();
        setMemories((prev) => [data as CharacterMemory, ...prev]);
        setContent("");
      }
    } finally {
      setCreating(false);
    }
  }

  async function removeMemory(id: string) {
    setMemories((prev) => prev.filter((m) => m.id !== id));
    await fetch(`/api/culturetoons/memories/${id}?brand_id=${brandId}`, { method: "DELETE" });
  }

  return (
    <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
      <p className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
        <BookOpen className="h-3.5 w-3.5 text-gray-400" /> Memory
      </p>
      <p className="text-[11px] text-gray-400 mb-2">
        Persistent facts/running jokes for this variant — automatically retrieved and referenced in
        future script generation when relevant.
      </p>

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : memories.length === 0 ? (
        <p className="text-xs text-gray-400 mb-2">No memories yet.</p>
      ) : (
        <div className="space-y-1 mb-2">
          {memories.map((m) => (
            <div key={m.id} className="flex items-start gap-1.5 text-xs text-gray-600 bg-white rounded-lg px-2 py-1.5 border border-gray-100">
              <div className="flex-1">
                <span className="text-[10px] uppercase tracking-wide text-gray-400">{m.memory_type.replace(/_/g, " ")}</span>
                <p>{m.content}</p>
              </div>
              <button onClick={() => removeMemory(m.id)} className="text-gray-300 hover:text-red-500 shrink-0">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      <form onSubmit={addMemory} className="flex flex-wrap gap-1.5">
        <select
          value={memoryType} onChange={(e) => setMemoryType(e.target.value as (typeof MEMORY_TYPES)[number])}
          className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs"
        >
          {MEMORY_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
        </select>
        <input
          type="text" value={content} onChange={(e) => setContent(e.target.value)}
          placeholder='e.g. "Once tried to negotiate a Swiss train ticket."'
          className="flex-1 min-w-[10rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
        />
        <button
          type="submit"
          disabled={creating || !content.trim()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
        >
          {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
        </button>
      </form>
    </div>
  );
}
