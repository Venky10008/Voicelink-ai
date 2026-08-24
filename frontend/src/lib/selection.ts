export type StoredSelection = {
  id: string;
  name: string;
  speed?: number;
  pitch?: number;
  /** Set when the selection is a cloned voice — the call screen sends voice_profile_id. */
  voiceProfileId?: number;
};

export const VOICE_KEY = "voicelink.voice";
export const PERSONALITY_KEY = "voicelink.personality";
export const SELECTION_EVENT = "voicelink:selection";

export function readSelection(key: string): StoredSelection | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredSelection;
    return parsed && typeof parsed.id === "string" ? parsed : null;
  } catch {
    return null;
  }
}

/** Like readSelection, but throws when the stored value is missing/corrupt. */
export function readSelectionStrict(key: string): StoredSelection | null {
  if (typeof window === "undefined") return null;
  let raw: string | null;
  try {
    raw = localStorage.getItem(key);
  } catch {
    throw new Error("Storage is unavailable in this browser.");
  }
  if (!raw) return null;
  let parsed: StoredSelection;
  try {
    parsed = JSON.parse(raw) as StoredSelection;
  } catch {
    throw new Error("Your saved selection is corrupted.");
  }
  if (!parsed || typeof parsed.id !== "string" || typeof parsed.name !== "string") {
    throw new Error("Your saved selection is invalid.");
  }
  return parsed;
}

export function writeSelection(key: string, value: StoredSelection) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(key, JSON.stringify(value));
    window.dispatchEvent(new CustomEvent(SELECTION_EVENT, { detail: { key, value } }));
  } catch {
    /* ignore */
  }
}

/** Routes considered "voice-related" — selecting a voice here continues to the call screen. */
export const VOICE_ROUTES = ["/voices", "/call"];

export function isVoiceRoute(pathname: string) {
  return VOICE_ROUTES.some((r) => pathname === r || pathname.startsWith(`${r}/`));
}
