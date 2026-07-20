import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Culturix — Daily Trend Intelligence for Content Creators & Brands";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#020617",
          backgroundImage:
            "radial-gradient(circle at 30% 25%, rgba(79,70,229,0.35), transparent 55%), radial-gradient(circle at 75% 75%, rgba(168,85,247,0.25), transparent 55%)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 28 }}>
          <div
            style={{
              display: "flex",
              width: 64,
              height: 64,
              borderRadius: 16,
              background: "linear-gradient(135deg, #6366f1, #a855f7)",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 40,
              color: "white",
            }}
          >
            ⚡
          </div>
          <div style={{ display: "flex", fontSize: 64, fontWeight: 800, color: "white" }}>
            Culturix
          </div>
        </div>
        <div
          style={{
            display: "flex",
            fontSize: 32,
            fontWeight: 500,
            color: "#cbd5e1",
            maxWidth: 860,
            textAlign: "center",
            lineHeight: 1.4,
          }}
        >
          Daily trend intelligence — 10 AI-personalized content ideas every morning
        </div>
      </div>
    ),
    { ...size }
  );
}
