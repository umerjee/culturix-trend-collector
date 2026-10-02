import countries from "i18n-iso-countries";
import en from "i18n-iso-countries/langs/en.json";
import fr from "i18n-iso-countries/langs/fr.json";
import de from "i18n-iso-countries/langs/de.json";
import es from "i18n-iso-countries/langs/es.json";

for (const locale of [en, fr, de, es]) countries.registerLocale(locale as any);

export function countryName(code: string | null | undefined, locale = "en"): string | null {
  if (!code) return null;
  return countries.getName(code, locale) || countries.getName(code, "en") || code;
}

// Regional-indicator pair for an ISO 3166-1 alpha-2 code; no flag asset needed.
export function flagEmoji(code: string | null | undefined): string {
  if (!code || !/^[A-Za-z]{2}$/.test(code)) return "";
  return String.fromCodePoint(...code.toUpperCase().split("").map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
}
