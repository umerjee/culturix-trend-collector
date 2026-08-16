// Single source of truth for the Railway backend base URL, replacing the ad
// hoc redeclaration of this fallback across every dashboard/settings/admin
// page and API route.
export const RAILWAY_API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://culturix-trend-collector-production.up.railway.app";
