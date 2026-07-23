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

function withOneSignal<T>(fn: (OneSignal: any) => Promise<T>): Promise<T | null> {
  if (typeof window === "undefined" || !window.OneSignalDeferred) return Promise.resolve(null);
  return new Promise((resolve) => {
    window.OneSignalDeferred!.push(async (OneSignal) => {
      try {
        resolve(await fn(OneSignal));
      } catch {
        resolve(null);
      }
    });
  });
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
export async function optIntoPush(userId: string): Promise<{ ok: boolean }> {
  if (!isPushSupported()) return { ok: false };
  const result = await withOneSignal(async (OneSignal) => {
    await OneSignal.login(userId);
    await OneSignal.Notifications.requestPermission();
    return OneSignal.Notifications.permission === true;
  });
  return { ok: result === true };
}

export async function optOutOfPush(): Promise<void> {
  await withOneSignal(async (OneSignal) => {
    await OneSignal.User.PushSubscription.optOut();
  });
}
