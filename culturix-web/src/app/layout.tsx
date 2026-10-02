import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { LocaleProvider } from "@/components/i18n/LocaleProvider";

const ONESIGNAL_APP_ID = process.env.NEXT_PUBLIC_ONESIGNAL_APP_ID;
const inter = Inter({ subsets: ["latin"] });
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://culturixcloud.com";
const SITE_TITLE = "Culturix — The world's video encyclopedia, with a sense of humour";
const SITE_DESCRIPTION = "Culturix is an AI-generated video encyclopedia of the world with a sense of humour. Explore short, source-linked stories about history, heritage, science, technology, and culture.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: SITE_TITLE, template: "%s · Culturix" },
  description: SITE_DESCRIPTION,
  keywords: ["AI video encyclopedia", "Wikipedia videos", "fact-checked culture videos", "world history videos", "funny educational videos", "interactive world atlas"],
  authors: [{ name: "Culturix" }],
  category: "education",
  robots: { index: true, follow: true, googleBot: { index: true, follow: true, "max-image-preview": "large" } },
  openGraph: { title: SITE_TITLE, description: SITE_DESCRIPTION, url: SITE_URL, siteName: "Culturix", type: "website", locale: "en_US" },
  twitter: { card: "summary_large_image", title: SITE_TITLE, description: SITE_DESCRIPTION },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "WebApplication",
    name: "Culturix",
    applicationCategory: "EducationalApplication",
    operatingSystem: "Web",
    description: SITE_DESCRIPTION,
    url: SITE_URL,
  };

  return (
    <html lang="en">
      <head>
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      </head>
      <body className={inter.className}>
        <LocaleProvider>{children}</LocaleProvider>
        {ONESIGNAL_APP_ID && (
          <>
            <Script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" strategy="afterInteractive" defer />
            <Script id="onesignal-init" strategy="afterInteractive">
              {`window.OneSignalDeferred = window.OneSignalDeferred || []; OneSignalDeferred.push(async function(OneSignal) { await OneSignal.init({ appId: "${ONESIGNAL_APP_ID}" }); });`}
            </Script>
          </>
        )}
      </body>
    </html>
  );
}
