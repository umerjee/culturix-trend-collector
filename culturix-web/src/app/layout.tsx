import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Culturix — Daily Trend Intelligence",
  description:
    "Turn today's cultural signals into tomorrow's content. 10 personalized ideas delivered every morning.",
  openGraph: {
    title: "Culturix — Daily Trend Intelligence",
    description: "Personalized content ideas from AI-analyzed trends across 5 platforms.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>{children}</body>
    </html>
  );
}
