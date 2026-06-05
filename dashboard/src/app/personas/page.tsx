"use client";

import useSWR from "swr";
import Link from "next/link";
import { fetcher, api, type Persona } from "@/lib/api";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Users } from "lucide-react";

function Avatar({ name }: { name: string }) {
  const colors = [
    "from-blue-400 to-violet-500",
    "from-emerald-400 to-teal-500",
    "from-orange-400 to-pink-500",
    "from-rose-400 to-fuchsia-500",
    "from-amber-400 to-orange-500",
  ];
  const color = colors[name.charCodeAt(0) % colors.length];
  return (
    <div className={`h-12 w-12 rounded-full bg-gradient-to-br ${color} flex items-center justify-center text-white font-bold text-lg shrink-0`}>
      {name[0]}
    </div>
  );
}

export default function PersonasPage() {
  const { data: personas, isLoading, error } = useSWR<Persona[]>(api.personas(), fetcher);

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Personas</h1>
        <p className="text-muted-foreground mt-1">AI-generated audience archetypes from clustered trends</p>
      </div>

      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-44 rounded-lg bg-gray-100 animate-pulse" />
          ))}
        </div>
      )}

      {error && <p className="text-red-600 text-sm">Failed to load personas.</p>}

      {personas && personas.length === 0 && (
        <div className="text-center py-20 text-muted-foreground">
          <Users className="h-10 w-10 mx-auto mb-3 opacity-30" />
          <p>No personas yet. Run <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">POST /process/personas/clustered</code>.</p>
        </div>
      )}

      {personas && personas.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {personas.map((p) => (
            <Link key={p.id} href={`/personas/${p.id}`}>
              <Card className="h-full hover:shadow-md transition-shadow cursor-pointer">
                <CardHeader className="pb-3">
                  <div className="flex items-start gap-3">
                    <Avatar name={p.name} />
                    <div className="min-w-0">
                      <h3 className="font-semibold leading-tight">{p.name}</h3>
                      <p className="text-sm text-muted-foreground mt-0.5 line-clamp-2">{p.description}</p>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {p.interests && (
                    <div className="flex flex-wrap gap-1.5">
                      {p.interests.split(",").slice(0, 4).map((interest) => (
                        <span
                          key={interest}
                          className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700 truncate max-w-[120px]"
                        >
                          {interest.trim()}
                        </span>
                      ))}
                    </div>
                  )}
                  {p.content_suggestions && (
                    <p className="text-xs text-muted-foreground mt-3">
                      {p.content_suggestions.length} content suggestions
                    </p>
                  )}
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
