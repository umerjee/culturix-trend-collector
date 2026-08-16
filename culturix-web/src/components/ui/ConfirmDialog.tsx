"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";
import Button from "./Button";

interface Props {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  destructive?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

// No confirmation dialog primitive existed anywhere in the codebase before
// this — admin actions like revoking a user or triggering a full collector
// run fired immediately on click. Simple focus-trap-free modal (no Radix
// dependency in this codebase); Escape cancels.
export default function ConfirmDialog({
  open, title, description, confirmLabel = "Confirm", destructive, loading, onConfirm, onCancel,
}: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          {destructive && (
            <span className="shrink-0 flex h-9 w-9 items-center justify-center rounded-full bg-red-50">
              <AlertTriangle className="h-4 w-4 text-red-500" />
            </span>
          )}
          <div>
            <h3 className="font-semibold text-gray-900">{title}</h3>
            <p className="text-sm text-gray-500 mt-1">{description}</p>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button variant={destructive ? "destructive" : "primary"} size="sm" onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
