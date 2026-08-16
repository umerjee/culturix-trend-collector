// Single source of truth for the superadmin gate. Zero framework imports —
// safe to import from both edge middleware and Node route handlers.
export const SUPERADMIN_EMAIL = "umer.ali79@gmail.com";

export function isSuperAdminEmail(email?: string | null): boolean {
  return !!email && email === SUPERADMIN_EMAIL;
}
