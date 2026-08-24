import { emotionMeta } from "@/lib/emotion";

/** Small pill showing the AI-detected mood of the user. Renders nothing for neutral. */
export function EmotionPill({
  emotion,
  className = "",
}: {
  emotion: string | null | undefined;
  className?: string;
}) {
  if (!emotion || emotion === "neutral") return null;
  const meta = emotionMeta(emotion);
  return (
    <span
      role="status"
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium animate-in fade-in slide-in-from-top-1 duration-300 ${meta.color} ${className}`}
    >
      <span aria-hidden="true">{meta.emoji}</span>
      {meta.label}
    </span>
  );
}
