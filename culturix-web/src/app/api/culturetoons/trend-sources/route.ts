import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RAILWAY =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://culturix-trend-collector-production.up.railway.app";

interface RawPersona { id: number; name: string; description: string | null; status: string | null }
interface RawCluster { id: number; theme: string | null; summary: string | null }

// Aggregates the *existing* /personas and /clusters endpoints (no new
// backend route needed) into the shape the script-suggestion picker wants —
// clusters have theme/summary, not name/description, so this normalizes
// both into {id, name, description}.
export async function GET() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const [personasRes, clustersRes] = await Promise.all([
    fetch(`${RAILWAY}/personas?limit=50`, { cache: "no-store", signal: AbortSignal.timeout(15000) }),
    fetch(`${RAILWAY}/clusters?limit=50`, { cache: "no-store", signal: AbortSignal.timeout(15000) }),
  ]);

  const rawPersonas: RawPersona[] = personasRes.ok ? await personasRes.json().catch(() => []) : [];
  const rawClusters: RawCluster[] = clustersRes.ok ? await clustersRes.json().catch(() => []) : [];

  return NextResponse.json({
    personas: rawPersonas
      .filter((p) => p.status === "active")
      .map((p) => ({ id: p.id, name: p.name, description: p.description })),
    clusters: rawClusters.map((c) => ({ id: c.id, name: c.theme || `Cluster ${c.id}`, description: c.summary })),
  });
}
