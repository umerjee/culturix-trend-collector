"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type Locale = "en" | "fr" | "de" | "es";

const MESSAGES = {
  en: { dashboard: "Dashboard", performance: "Performance", calendar: "Calendar", settings: "Settings", help: "How it works", admin: "Admin", signOut: "Sign out", products: "Culturix products", posting: "Posting Ideation", postingDesc: "Trend-driven content ideas & publishing", shopify: "Shopify Reel Building", shopifyDesc: "AI reels grounded in your real product catalog", culturetoons: "Character-Based Posting", culturetoonsDesc: "Cartoon characters riffing on cultural trends" },
  fr: { dashboard: "Tableau de bord", performance: "Performance", calendar: "Calendrier", settings: "Réglages", help: "Comment ça marche", admin: "Admin", signOut: "Se déconnecter", products: "Produits Culturix", posting: "Idées de publication", postingDesc: "Idées fondées sur les tendances et publication", shopify: "Reels Shopify", shopifyDesc: "Reels IA basés sur votre catalogue", culturetoons: "Personnages animés", culturetoonsDesc: "Des personnages qui jouent avec les tendances" },
  de: { dashboard: "Dashboard", performance: "Leistung", calendar: "Kalender", settings: "Einstellungen", help: "So funktioniert es", admin: "Admin", signOut: "Abmelden", products: "Culturix-Produkte", posting: "Posting-Ideen", postingDesc: "Trendbasierte Ideen und Veröffentlichung", shopify: "Shopify-Reels", shopifyDesc: "KI-Reels aus Ihrem Produktkatalog", culturetoons: "Figuren-Posting", culturetoonsDesc: "Cartoonfiguren greifen kulturelle Trends auf" },
  es: { dashboard: "Panel", performance: "Rendimiento", calendar: "Calendario", settings: "Configuración", help: "Cómo funciona", admin: "Admin", signOut: "Cerrar sesión", products: "Productos Culturix", posting: "Ideas para publicar", postingDesc: "Ideas basadas en tendencias y publicación", shopify: "Reels para Shopify", shopifyDesc: "Reels de IA basados en tu catálogo", culturetoons: "Personajes animados", culturetoonsDesc: "Personajes que juegan con las tendencias culturales" },
} as const;

type Messages = { [Key in keyof typeof MESSAGES.en]: string };
const LocaleContext = createContext<{ locale: Locale; messages: Messages }>({ locale: "en", messages: MESSAGES.en });

function validLocale(value: string | null): Locale {
  return value === "fr" || value === "de" || value === "es" ? value : "en";
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocale] = useState<Locale>("en");

  useEffect(() => {
    const read = () => setLocale(validLocale(document.cookie.match(/(?:^|; )culturix_language=([^;]+)/)?.[1] ?? null));
    read();
    window.addEventListener("culturix-language-change", read);
    return () => window.removeEventListener("culturix-language-change", read);
  }, []);

  return <LocaleContext.Provider value={{ locale, messages: MESSAGES[locale] }}>{children}</LocaleContext.Provider>;
}

export function useLocale() {
  return useContext(LocaleContext);
}
