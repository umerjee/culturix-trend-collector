// Thin wrapper around the OneSignal Web SDK, loaded globally in layout.tsx
// via window.OneSignalDeferred (see culturix-web/src/app/layout.tsx). Ties a
// browser's push subscription to the Culturix user id (OneSignal's
// "external_id" alias) so the backend can target notifications by user —
// see app/notifications/onesignal.py's send_stage_ready_push.

declare global {
  interface Window {
    OneSignalDeferred?: Array<(OneSignal: any) => void>;
  }
}

// 8s timeout — if the OneSignal SDK script never loads (blocked by an ad
// blocker/Brave Shields, network issue, etc.) window.OneSignalDeferred stays
// a plain array forever and our queued callback would otherwise never run,
// leaving the caller's promise pending indefinitely with no feedback to the
// user (this is exactly what caused the "Enable notifications" button to
// spin forever before this was added).
const ONESIGNAL_TIMEOUT_MS = 8000;

function withOneSignal<T>(fn: (OneSignal: any) => Promise<T>): Promise<T | null> {
  if (typeof window === "undefined" || !window.OneSignalDeferred) return Promise.resolve(null);
  const queued = new Promise<T | null>((resolve) => {
    window.OneSignalDeferred!.push(async (OneSignal) => {
      try {
        resolve(await fn(OneSignal));
      } catch {
        resolve(null);
      }
    });
  });
  const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), ONESIGNAL_TIMEOUT_MS));
  return Promise.race([queued, timeout]);
}

// iOS Safari only supports web push once the site has been "Added to Home
// Screen" as a PWA (iOS 16.4+) — Apple's rule, not something we control.
// Detects the common case (iOS + not running as a standalone PWA) so the UI
// can show "Add to Home Screen first" instead of a permission prompt that'd
// silently do nothing.
export function isIosNonStandalone(): boolean {
  if (typeof window === "undefined" || typeof navigator === "undefined") return false;
  const isIos = /iPad|iPhone|iPod/.test(navigator.userAgent) && !("MSStream" in window);
  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as any).standalone === true;
  return isIos && !isStandalone;
}

export function isPushSupported(): boolean {
  if (typeof window === "undefined") return false;
  return "serviceWorker" in navigator && "PushManager" in window && !isIosNonStandalone();
}

// Opts the current user into push: ties their OneSignal subscription to
// their Culturix user id and requests browser notification permission.
// `reason` is set only on failure, so callers can show a useful message
// instead of a bare "didn't work" — "blocked" covers both a real timeout
// and the SDK script never loading, since from here they're indistinguishable.
export async function optIntoPush(
  userId: string
): Promise<{ ok: boolean; reason?: "unsupported" | "blocked" | "permission_denied" }> {
  if (!isPushSupported()) return { ok: false, reason: "unsupported" };
  if (typeof window === "undefined" || !window.OneSignalDeferred) {
    return { ok: false, reason: "blocked" };
  }
  const result = await withOneSignal(async (OneSignal) => {
    await OneSignal.login(userId);
    await OneSignal.Notifications.requestPermission();
    return OneSignal.Notifications.permission === true;
  });
  if (result === true) return { ok: true };
  if (result === null) return { ok: false, reason: "blocked" };
  return { ok: false, reason: "permission_denied" };
}

export async function optOutOfPush(): Promise<void> {
  await withOneSignal(async (OneSignal) => {
    await OneSignal.User.PushSubscription.optOut();
  });
}
