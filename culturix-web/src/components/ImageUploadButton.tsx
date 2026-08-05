"use client";

import { useRef, useState } from "react";
import { Upload, Loader2 } from "lucide-react";

interface Props {
  uploadUrl: string;
  currentImageUrl?: string | null;
  onUploaded: (data: Record<string, unknown>) => void;
  label?: string;
  size?: "sm" | "md";
  extraFields?: Record<string, string>;
}

export default function ImageUploadButton({ uploadUrl, currentImageUrl, onUploaded, label, size = "md", extraFields }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dims = size === "sm" ? "h-16 w-16" : "h-28 w-28";

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      for (const [key, value] of Object.entries(extraFields ?? {})) {
        formData.set(key, value);
      }
      formData.set("file", file);
      const res = await fetch(uploadUrl, { method: "POST", body: formData });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Upload failed");
        return;
      }
      onUploaded(data);
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        className={`relative ${dims} rounded-lg border-2 border-dashed border-gray-200 hover:border-blue-300 transition-colors overflow-hidden bg-gray-50 flex items-center justify-center shrink-0`}
      >
        {currentImageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={currentImageUrl} alt={label ?? "uploaded"} className="h-full w-full object-cover" />
        ) : uploading ? (
          <Loader2 className="h-5 w-5 text-gray-400 animate-spin" />
        ) : (
          <Upload className="h-5 w-5 text-gray-300" />
        )}
        {uploading && currentImageUrl && (
          <div className="absolute inset-0 bg-white/70 flex items-center justify-center">
            <Loader2 className="h-5 w-5 text-gray-500 animate-spin" />
          </div>
        )}
      </button>
      {label && <span className="text-[10px] text-gray-500 text-center leading-tight max-w-[4.5rem]">{label}</span>}
      {error && <span className="text-[10px] text-red-500 text-center max-w-[4.5rem]">{error}</span>}
      <input ref={inputRef} type="file" accept="image/png,image/webp" onChange={handleFile} className="hidden" />
    </div>
  );
}
