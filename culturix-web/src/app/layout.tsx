import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://culturixcloud.com";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Culturix — Daily Trend Intelligence for Content Creators & Brands",
    template: "%s · Culturix",
  },
  description:
    "Culturix turns today's cultural signals into tomorrow's content. AI-clustered trends from across the web, matched to your brand, delivered as 10 personalized content ideas every morning — with recurring-trend awareness so you know what's a real pattern versus a one-off spike.",
  keywords: [
    "trend intelligence",
    "content ideas AI",
    "social media trend detection",
    "content calendar AI",
    "TikTok trend tracker",
    "creator content tools",
    "AI content strategist",
    "viral trend analysis",
    "content creator trends",
    "brand content ideas",
  ],
  authors: [{ name: "Culturix" }],
  category: "technology",
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
    },
  },
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "Culturix — Daily Trend Intelligence for Content Creators & Brands",
    description:
      "10 AI-personalized content ideas every morning, built from real-time cultural signals across the web — with recurring-trend awareness baked in.",
    url: SITE_URL,
    siteName: "Culturix",
    type: "website",
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: "Culturix — Daily Trend Intelligence for Content Creators & Brands",
    description:
      "10 AI-personalized content ideas every morning, built from real-time cultural signals across the web.",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "Culturix",
    applicationCategory: "BusinessApplication",
    operatingSystem: "Web",
    description:
      "AI-powered trend intelligence platform that turns real-time cultural signals into personalized daily content ideas for creators and brands.",
    url: SITE_URL,
    offers: [
      {
        "@type": "Offer",
        name: "Free",
        price: "0",
        priceCurrency: "USD",
      },
      {
        "@type": "Offer",
        name: "Pro",
        price: "29",
        priceCurrency: "USD",
        priceSpecification: {
          "@type": "UnitPriceSpecification",
          price: "29",
          priceCurrency: "USD",
          billingDuration: "P1M",
        },
      },
    ],
  };

  return (
    <html lang="en">
      <head>
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <script
          type="application/ld+json"
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body className={inter.className}>{children}</body>
    </html>
  );
}
