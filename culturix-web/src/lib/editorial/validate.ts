// Client-side checks for the editorial workflow forms. They mirror app/routers/editorial.py so an
// operator sees the problem before a request is sent; the backend re-checks everything.

export const PLATFORMS = ["tiktok", "instagram", "youtube"] as const;
export type Platform = (typeof PLATFORMS)[number];

export type FieldErrors = Record<string, string>;

export interface ScriptForm {
  brandId: string;
  castIds: string[];
  format: string;
  language: string;
  tone: string;
  durationSeconds: string;
}

export function validateScriptForm(form: ScriptForm, formats: string[], languages: string[]): FieldErrors {
  const errors: FieldErrors = {};
  if (!form.brandId) errors.brandId = "Choose the brand whose cast will perform it.";
  if (form.castIds.length === 0) errors.castIds = "Pick at least one character.";
  if (form.castIds.length > 4) errors.castIds = "At most 4 characters per video.";
  if (!formats.includes(form.format)) errors.format = "Choose a format.";
  if (!languages.includes(form.language)) errors.language = "Choose a language.";
  if (!form.tone) errors.tone = "Choose a tone.";
  const duration = Number(form.durationSeconds);
  if (!Number.isInteger(duration) || duration < 6 || duration > 60) errors.durationSeconds = "Use a whole number of seconds from 6 to 60.";
  return errors;
}

export function missingChecklistItems(checklist: Record<string, boolean>, required: string[]): string[] {
  return required.filter((key) => checklist[key] !== true);
}

export function validateBlockNote(note: string): string | null {
  return note.trim().length >= 5 ? null : "Say why it is blocked (at least a few words).";
}

export interface MetricsForm {
  views: string; likes: string; comments: string; shares: string;
  saves: string; follows: string; avgWatchSeconds: string; completionRate: string;
}

export interface PostForm extends MetricsForm {
  platform: string;
  postUrl: string;
  postedAt: string;
}

export type MetricsPayload = Partial<Record<"views" | "likes" | "comments" | "shares" | "saves" | "follows" | "avg_watch_seconds" | "completion_rate", number>>;

const COUNT_FIELDS: [keyof MetricsForm, keyof MetricsPayload][] = [
  ["views", "views"], ["likes", "likes"], ["comments", "comments"], ["shares", "shares"],
  ["saves", "saves"], ["follows", "follows"],
];
const CORE: (keyof MetricsForm)[] = ["views", "likes", "comments", "shares"];

// Empty optional fields are left out (not collected), never sent as 0.
export function validateMetrics(form: MetricsForm, requireCore: boolean): { errors: FieldErrors; payload: MetricsPayload } {
  const errors: FieldErrors = {};
  const payload: MetricsPayload = {};
  for (const [field, key] of COUNT_FIELDS) {
    const raw = form[field].trim();
    if (!raw) {
      if (requireCore && CORE.includes(field)) errors[field] = "Required (use 0 if none).";
      continue;
    }
    const value = Number(raw);
    if (!/^\d+$/.test(raw) || !Number.isSafeInteger(value)) errors[field] = "Whole number of 0 or more.";
    else payload[key] = value;
  }
  const watch = form.avgWatchSeconds.trim();
  if (watch) {
    const value = Number(watch);
    if (!Number.isFinite(value) || value < 0) errors.avgWatchSeconds = "Seconds, 0 or more.";
    else payload.avg_watch_seconds = value;
  }
  const completion = form.completionRate.trim();
  if (completion) {
    const percent = Number(completion.replace("%", ""));
    if (!Number.isFinite(percent) || percent < 0 || percent > 100) errors.completionRate = "A percentage from 0 to 100.";
    else payload.completion_rate = Math.round(percent * 10) / 1000;
  }
  if (!requireCore && Object.keys(payload).length === 0 && Object.keys(errors).length === 0) errors.form = "Enter at least one metric.";
  return { errors, payload };
}

export function validatePostForm(form: PostForm): { errors: FieldErrors; payload: Record<string, unknown> } {
  const { errors, payload } = validateMetrics(form, true);
  if (!(PLATFORMS as readonly string[]).includes(form.platform)) errors.platform = "Choose a platform.";
  try {
    const url = new URL(form.postUrl.trim());
    if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error();
  } catch {
    errors.postUrl = "Paste the full link to the post.";
  }
  if (form.postedAt && Number.isNaN(Date.parse(form.postedAt))) errors.postedAt = "Not a valid date.";
  return {
    errors,
    payload: { ...payload, platform: form.platform, post_url: form.postUrl.trim(), ...(form.postedAt ? { posted_at: form.postedAt } : {}) },
  };
}
