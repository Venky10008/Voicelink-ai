export type EmotionId =
  | "happy"
  | "sad"
  | "angry"
  | "anxious"
  | "excited"
  | "tired"
  | "neutral";

export const EMOTION_META: Record<EmotionId, { label: string; emoji: string; color: string }> = {
  happy: { label: "Happy", emoji: "😊", color: "text-amber-400 border-amber-400/40 bg-amber-400/10" },
  sad: { label: "Sad", emoji: "😔", color: "text-sky-400 border-sky-400/40 bg-sky-400/10" },
  angry: { label: "Frustrated", emoji: "😠", color: "text-red-400 border-red-400/40 bg-red-400/10" },
  anxious: { label: "Anxious", emoji: "😟", color: "text-orange-400 border-orange-400/40 bg-orange-400/10" },
  excited: { label: "Excited", emoji: "🤩", color: "text-fuchsia-400 border-fuchsia-400/40 bg-fuchsia-400/10" },
  tired: { label: "Tired", emoji: "😴", color: "text-violet-400 border-violet-400/40 bg-violet-400/10" },
  neutral: { label: "Neutral", emoji: "😐", color: "text-muted-foreground border-border/60 bg-muted/40" },
};

/** Meta for an arbitrary emotion string, defaulting to neutral. */
export function emotionMeta(emotion: string | null | undefined): {
  label: string;
  emoji: string;
  color: string;
} {
  if (!emotion) return EMOTION_META.neutral;
  return EMOTION_META[emotion as EmotionId] ?? EMOTION_META.neutral;
}
