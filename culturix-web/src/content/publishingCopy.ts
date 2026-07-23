// Single source of truth for the "why we don't post for you, and here's how
// it works instead" copy — previously duplicated separately across
// PublishingWizard.tsx, SettingsForm.tsx, and PublishLaunchCard.tsx. Also
// used by the public /how-it-works page. Edit wording here, not in any of
// the consumers below.

export const PUBLISH_MODE_DESCRIPTIONS: Record<"manual" | "review" | "auto", string> = {
  manual: "You post it yourself, then paste the link to track it.",
  review: "Click Stage & notify me — Culturix preps it and pings you when it's ready to launch.",
  auto: "Culturix preps the best idea and notifies you, once a day — you do the final tap to post.",
};

export const PUBLISH_MODE_LABELS: Record<"manual" | "review" | "auto", string> = {
  manual: "Manual", review: "Review", auto: "Auto",
};

export const WHY_NOT_DIRECT_PUBLISH =
  "Most platforms only let apps like ours post automatically through a Business account — and Business accounts lose access to the trending-audio library that makes videos actually take off. We'd rather you keep your Personal or Creator account, use whatever song is blowing up this week, and get the full reach that comes with it.";

export const IOS_PUSH_NOTE =
  "Notifications are sent via web push — on iPhone, add Culturix to your Home Screen first (Share → Add to Home Screen) for them to come through. That's an Apple rule for web apps, not something we control.";

export const HOW_IT_WORKS_STEPS: { title: string; desc: string }[] = [
  {
    title: "We do the prep",
    desc: "Our AI spots the trend, builds your video, and writes a caption that fits it — all before you lift a finger.",
  },
  {
    title: "You get a nudge",
    desc: "Right at peak posting time, you'll get a notification: “Your content is ready to post.”",
  },
  {
    title: "You launch it",
    desc: "Tap the notification. Your video saves to your phone, your caption copies to your clipboard, and the app opens right up. Paste the caption, pick your favorite trending sound, hit Post. Done.",
  },
];

export const LAUNCH_DISCLAIMER =
  "No platform lets an app drop a video straight into its composer with the caption pre-filled — so that one paste-and-post tap inside the app is still yours to make. Everything else, we've done for you.";
