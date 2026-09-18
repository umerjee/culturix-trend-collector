import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import "./globals.css";

const ONESIGNAL_APP_ID = process.env.NEXT_PUBLIC_ONESIGNAL_APP_ID;

const inter = Inter({ subsets: ["latin"] });

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://culturixcloud.com";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Culturix — Explore the world's culture, one short video at a time",
    template: "%s · Culturix",
  },
  description:
    "Culturix World is an interactive map of history, heritage, technology and humor. Pick a country, slide through time, and watch short fact-checked videos built from real sources like Wikipedia and UNESCO and tied to what is trending there now. Also: daily trend-driven content ideas for creators and brands.",
  keywords: [
    "world culture map",
    "cultural heritage videos",
    "UNESCO World Heritage videos",
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
    title: "Culturix — Explore the world's culture, one short video at a time",
    description:
      "An interactive map of history, heritage, technology and humor. Short fact-checked videos built from real sources like Wikipedia and UNESCO, tied to what is trending in each country.",
    url: SITE_URL,
    siteName: "Culturix",
    type: "website",
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: "Culturix — Explore the world's culture, one short video at a time",
    description:
      "An interactive map of history, heritage, technology and humor. Short fact-checked videos built from real sources, tied to what is trending in each country.",
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
      <body className={inter.className}>
        {children}
        {ONESIGNAL_APP_ID && (
          <>
            <Script
              src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js"
              strategy="afterInteractive"
              defer
            />
            <Script id="onesignal-init" strategy="afterInteractive">
              {`
                window.OneSignalDeferred = window.OneSignalDeferred || [];
                OneSignalDeferred.push(async function(OneSignal) {
                  await OneSignal.init({ appId: "${ONESIGNAL_APP_ID}" });
                });
              `}
            </Script>
          </>
        )}
      </body>
    </html>
  );
}
