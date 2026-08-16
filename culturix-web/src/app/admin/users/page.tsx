"use client";

import { useEffect, useState } from "react";
import { CheckCircle, XCircle, Clock } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import type { UserRecord } from "@/lib/admin/types";
import { fmt } from "@/lib/admin/types";
import ConfirmDialog from "@/components/ui/ConfirmDialog";

type PendingAction =
  | { kind: "revoke"; userId: string }
  | { kind: "downgrade"; userId: string };

export default function UsersPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [approving, setApproving] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);

  useEffect(() => {
    fetchAdminData<UserRecord[]>("users").then(setUsers).catch(() => setUsers([])).finally(() => setLoading(false));
  }, []);

  async function setApproval(userId: string, approved: boolean) {
    setApproving(userId);
    try {
      const action = approved ? "approve" : "reject";
      const res = await fetch(`/api/admin/users/${userId}/${action}`, { method: "POST" });
      if (res.ok) setUsers((prev) => prev.map((u) => (u.user_id === userId ? { ...u, approved } : u)));
    } finally {
      setApproving(null);
      setPendingAction(null);
    }
  }

  async function setPlan(userId: string, plan: "free" | "pro") {
    const res = await fetch(`/api/admin/users/${userId}/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan }),
    });
    if (res.ok) setUsers((prev) => prev.map((u) => (u.user_id === userId ? { ...u, plan } : u)));
    setPendingAction(null);
  }

  const filtered = users.filter((u) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return u.user_id.toLowerCase().includes(q) ||
      u.content_profiles.some((cp) => cp.name.toLowerCase().includes(q) || (cp.industry_niche ?? "").toLowerCase().includes(q));
  });
  const pendingCount = users.filter((u) => !u.approved).length;

  if (loading) return <p className="text-sm text-gray-400 text-center py-16">Loading…</p>;

  return (
    <div className="space-y-4">
      <h1 className="font-bold text-gray-900 text-xl">Users</h1>

      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by user ID, profile name, or niche…"
        className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
      />

      {pendingCount > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-3 flex items-center gap-2 text-sm text-amber-700">
          <Clock className="h-4 w-4 shrink-0" />
          {pendingCount} user{pendingCount !== 1 ? "s" : ""} waiting for approval
        </div>
      )}

      {filtered.length === 0 && <p className="text-gray-400 text-sm">No users match.</p>}

      {filtered.map((u) => (
        <div key={u.user_id} className={`bg-white rounded-xl border overflow-hidden ${!u.approved ? "border-amber-200" : "border-gray-100"}`}>
          <div className="flex items-center gap-4 px-6 py-4 border-b border-gray-50 flex-wrap">
            <span className="font-mono text-xs text-gray-400 shrink-0">{u.user_id.slice(0, 16)}…</span>

            {u.approved ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs font-medium">
                <CheckCircle className="h-3 w-3" /> Approved
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-100 text-amber-700 rounded text-xs font-medium">
                <Clock className="h-3 w-3" /> Pending
              </span>
            )}

            <span className={`px-2 py-0.5 rounded text-xs font-semibold ${u.plan === "pro" ? "bg-primary-100 text-primary-700" : "bg-gray-100 text-gray-500"}`}>
              {u.plan === "pro" ? "Pro" : "Free"}
            </span>
            <span className="text-xs text-gray-400">{u.content_profiles.length} profile{u.content_profiles.length !== 1 ? "s" : ""}</span>
            <span className="text-xs text-gray-400 ml-auto">{fmt(u.created_at)}</span>

            <div className="flex items-center gap-2">
              {!u.approved ? (
                <button
                  onClick={() => setApproval(u.user_id, true)}
                  disabled={approving === u.user_id}
                  className="inline-flex items-center gap-1 px-3 py-1 bg-green-600 text-white text-xs rounded-lg hover:bg-green-700 disabled:opacity-50 transition"
                >
                  <CheckCircle className="h-3 w-3" />
                  {approving === u.user_id ? "…" : "Approve"}
                </button>
              ) : (
                <button
                  onClick={() => setPendingAction({ kind: "revoke", userId: u.user_id })}
                  disabled={approving === u.user_id}
                  className="inline-flex items-center gap-1 px-3 py-1 border border-red-200 text-red-500 text-xs rounded-lg hover:bg-red-50 disabled:opacity-50 transition"
                >
                  <XCircle className="h-3 w-3" />
                  {approving === u.user_id ? "…" : "Revoke"}
                </button>
              )}
              {u.plan === "free" ? (
                <button
                  onClick={() => setPlan(u.user_id, "pro")}
                  className="px-3 py-1 bg-primary-600 text-white text-xs rounded-lg hover:bg-primary-700 transition"
                >
                  → Pro
                </button>
              ) : (
                <button
                  onClick={() => setPendingAction({ kind: "downgrade", userId: u.user_id })}
                  className="px-3 py-1 border border-gray-200 text-gray-500 text-xs rounded-lg hover:bg-gray-50 transition"
                >
                  → Free
                </button>
              )}
            </div>
          </div>

          {u.content_profiles.length === 0 ? (
            <p className="px-6 py-3 text-xs text-gray-400 italic">No content profiles yet</p>
          ) : (
            <div className="divide-y divide-gray-50">
              {u.content_profiles.map((cp) => (
                <div key={cp.id} className="flex items-center gap-3 px-6 py-3">
                  <div className={`h-2 w-2 rounded-full shrink-0 ${cp.is_active ? "bg-green-400" : "bg-gray-300"}`} />
                  <span className="text-sm font-medium text-gray-800 w-36 truncate">{cp.name}</span>
                  <span className="text-xs text-gray-500">{cp.industry_niche || <span className="italic text-gray-300">no niche</span>}</span>
                  <div className="flex gap-1 ml-2">
                    {cp.target_platforms.slice(0, 4).map((p) => (
                      <span key={p} className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-xs">{p}</span>
                    ))}
                  </div>
                  <span className="ml-auto text-xs text-gray-300">{fmt(cp.created_at)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      <ConfirmDialog
        open={pendingAction?.kind === "revoke"}
        title="Revoke this user's approval?"
        description="They'll immediately lose access until approved again."
        confirmLabel="Revoke"
        destructive
        loading={pendingAction?.kind === "revoke" && approving === pendingAction.userId}
        onConfirm={() => pendingAction && setApproval(pendingAction.userId, false)}
        onCancel={() => setPendingAction(null)}
      />
      <ConfirmDialog
        open={pendingAction?.kind === "downgrade"}
        title="Downgrade this user to Free?"
        description="They'll lose Pro-only features (extra content ideas, AI media generation) immediately."
        confirmLabel="Downgrade"
        destructive
        onConfirm={() => pendingAction && setPlan(pendingAction.userId, "free")}
        onCancel={() => setPendingAction(null)}
      />
    </div>
  );
}
