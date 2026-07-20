import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://culturixcloud.com";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Authenticated/internal app routes — nothing indexable behind these anyway,
      // but keep crawlers from wasting budget attempting them.
      disallow: [
        "/dashboard",
        "/admin",
        "/onboarding",
        "/settings",
        "/pending",
        "/auth",
        "/api",
        "/reset-password",
        "/forgot-password",
      ],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
