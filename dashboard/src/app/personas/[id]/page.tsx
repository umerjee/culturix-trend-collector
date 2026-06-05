"use client";

import { use } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetcher, api, type PersonaDetail } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PlatformBadge } from "@/components/ui/badge";
import { ArrowLeft, ExternalLink, Lightbulb, Heart, Star } from "lucide-react";

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
    <div className={`h-16 w-16 rounded-full bg-gradient-to-br ${color} flex items-center justify-center text-white font-bold text-2xl shrink-0`}>
      {name[0]}
    </div>
  );
}

const FORMAT_COLORS: Record<string, string> = {
  "short video": "bg-pink-50 text-pink-700 border-pink-200",
  carousel: "bg-blue-50 text-blue-700 border-blue-200",
  "blog post": "bg-green-50 text-green-700 border-green-200",
  poll: "bg-orange-50 text-orange-700 border-orange-200",
  thread: "bg-purple-50 text-purple-700 border-purple-200",
};

export default function PersonaDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: persona, isLoading, error } = useSWR<PersonaDetail>(api.persona(Number(id)), fetcher);

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <Link href="/personas">
        <Button variant="ghost" size="sm" className="mb-4 -ml-2">
          <ArrowLeft className="h-4 w-4 mr-1" /> Personas
        </Button>
      </Link>

      {isLoading && <div className="h-40 rounded-lg bg-gray-100 animate-pulse" />}
      {error && <p className="text-red-600 text-sm">Failed to load persona.</p>}

      {persona && (
        <div className="space-y-6">
          {/* Header */}
          <div className="flex items-start gap-4">
            <Avatar name={persona.name} />
            <div>
              <h1 className="text-2xl font-bold">{persona.name}</h1>
              <p className="text-muted-foreground mt-1 max-w-xl">{persona.description}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Motivations */}
            {persona.motivations && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Heart className="h-4 w-4 text-rose-500" /> Motivations
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1.5">
                    {persona.motivations.split(",").map((m) => (
                      <span key={m} className="rounded-full bg-rose-50 text-rose-700 px-2.5 py-0.5 text-xs border border-rose-200">
                        {m.trim()}
                      </span>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Interests */}
            {persona.interests && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Star className="h-4 w-4 text-amber-500" /> Interests
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1.5">
                    {persona.interests.split(",").map((i) => (
                      <span key={i} className="rounded-full bg-amber-50 text-amber-700 px-2.5 py-0.5 text-xs border border-amber-200">
                        {i.trim()}
                      </span>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Content Suggestions */}
          {persona.content_suggestions && persona.content_suggestions.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Lightbulb className="h-4 w-4 text-yellow-500" /> Content Ideas
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-2">
                {persona.content_suggestions.map((s, i) => {
                  const formatColor = FORMAT_COLORS[s.format?.toLowerCase()] ?? "bg-gray-50 text-gray-700 border-gray-200";
                  return (
                    <div key={i} className="rounded-lg border p-3 space-y-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium leading-snug">{s.title}</p>
                        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs ${formatColor}`}>
                          {s.format}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground">{s.hook}</p>
                      <p className="text-xs font-medium text-blue-600">{s.platform}</p>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          )}

          {/* Sample Trends */}
          {persona.sample_trends && persona.sample_trends.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Linked Trends</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <ul className="divide-y">
                  {persona.sample_trends.map((t) => (
                    <li key={t.id} className="flex items-center gap-3 px-6 py-3">
                      <PlatformBadge platform={t.platform} />
                      <span className="text-sm flex-1 line-clamp-1">{t.title}</span>
                      {t.url && (
                        <a href={t.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:text-blue-800">
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
