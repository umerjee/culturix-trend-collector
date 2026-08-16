import type { Config } from "tailwindcss";

// Radius convention (enforced by the ui/ kit, not by Tailwind config —
// documented here so it stays discoverable): rounded-2xl for cards and other
// containers, rounded-lg/rounded-xl for buttons, inputs, and badges.
const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Single site-wide primary/CTA color (indigo) — replaces the old
        // unused `brand` (blue) scale and the blue/indigo drift between the
        // home page and the rest of the app.
        primary: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
        },
        // Reserved for "AI / stat" accent usage (WeekdayBarChart, sparkles,
        // gradient glows) so it stops colliding with the primary CTA color.
        accent: {
          50: "#f5f3ff",
          100: "#ede9fe",
          200: "#ddd6fe",
          300: "#c4b5fd",
          400: "#a78bfa",
          500: "#8b5cf6",
          600: "#7c3aed",
          700: "#6d28d9",
          800: "#5b21b6",
          900: "#4c1d95",
        },
      },
    },
  },
  plugins: [],
};

export default config;
