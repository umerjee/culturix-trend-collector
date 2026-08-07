"use client";

import { Loader2, Wand2 } from "lucide-react";
import { ART_STYLES } from "@/lib/types";
import ImageUploadButton from "@/components/ImageUploadButton";

interface Props {
  description: string;
  onDescriptionChange: (v: string) => void;
  descriptionPlaceholder: string;
  // Only the base character sets an art style; variants inherit it.
  artStyle?: { value: (typeof ART_STYLES)[number]["key"]; onChange: (v: (typeof ART_STYLES)[number]["key"]) => void };
  // Only variants have a culture tag.
  cultureTag?: { value: string; onChange: (v: string) => void };
  referencePhotoUrl: string | null;
  referenceUploadUrl: string;
  portraitUrl: string | null;
  portraitUploadUrl: string;
  extraFields: Record<string, string>;
  onReferenceUploaded: (data: Record<string, unknown>) => void;
  onPortraitUploaded: (data: Record<string, unknown>) => void;
  onGenerate: () => void;
  generating: boolean;
  error: string | null;
  warning?: string | null;
  helperText: string;
}

export default function CharacterImageBuilder({
  description, onDescriptionChange, descriptionPlaceholder, artStyle, cultureTag,
  referencePhotoUrl, referenceUploadUrl, portraitUrl, portraitUploadUrl, extraFields,
  onReferenceUploaded, onPortraitUploaded, onGenerate, generating, error, warning, helperText,
}: Props) {
  return (
    <div className="rounded-xl border border-gray-100 bg-gray-50 p-4">
      <textarea
        value={description}
        onChange={(e) => onDescriptionChange(e.target.value)}
        placeholder={descriptionPlaceholder}
        rows={3}
        className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs mb-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-200"
      />

      {artStyle && (
        <>
          <label className="block text-[11px] font-medium text-gray-500 mb-1">Character type / art style</label>
          <select
            value={artStyle.value}
            onChange={(e) => artStyle.onChange(e.target.value as (typeof ART_STYLES)[number]["key"])}
            className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
          >
            {ART_STYLES.map((s) => (
              <option key={s.key} value={s.key}>{s.label}</option>
            ))}
          </select>
          <p className="text-[11px] text-gray-400 mb-2 mt-1">
            {ART_STYLES.find((s) => s.key === artStyle.value)?.hint}
          </p>
        </>
      )}

      {cultureTag && (
        <>
          <label className="block text-[11px] font-medium text-gray-500 mb-1">
            Ethnicity / cultural look <span className="text-gray-400 font-normal">(drives appearance, e.g. &quot;chinese&quot;, &quot;nigerian&quot;)</span>
          </label>
          <input
            type="text"
            value={cultureTag.value}
            onChange={(e) => cultureTag.onChange(e.target.value)}
            placeholder="e.g. indian, chinese, nigerian (optional)"
            className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs mb-2"
          />
        </>
      )}

      <div className="flex items-center gap-3 mb-2">
        <ImageUploadButton
          uploadUrl={referenceUploadUrl}
          currentImageUrl={referencePhotoUrl}
          label="Reference photo"
          size="sm"
          extraFields={extraFields}
          onUploaded={onReferenceUploaded}
        />
        <button
          onClick={onGenerate}
          disabled={generating || !description.trim()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60 shrink-0"
        >
          {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
          {portraitUrl ? "Regenerate image" : "Generate image"}
        </button>
      </div>
      {error && <p className="text-[11px] text-red-500 mb-2">{error}</p>}
      {warning && <p className="text-[11px] text-amber-600 mb-2">{warning}</p>}
      <p className="text-[11px] text-gray-400 mb-3">{helperText}</p>

      <div className="flex justify-center">
        <ImageUploadButton
          uploadUrl={portraitUploadUrl}
          currentImageUrl={portraitUrl}
          label="Portrait"
          extraFields={extraFields}
          onUploaded={onPortraitUploaded}
        />
      </div>
    </div>
  );
}
