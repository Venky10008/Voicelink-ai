import { useEffect, useRef, useState } from "react";
import { Mic, MicOff } from "lucide-react";
import type { StoredSelection } from "@/lib/selection";
import {
  personalityStyle,
  voiceTone,
  companionKey,
  TONE_SHAPE,
  TONE_ACCENT,
} from "@/lib/companion-style";

type Props = {
  voice?: StoredSelection | null;
  personality?: StoredSelection | null;
  /** Pixel size of the avatar. */
  size?: number;
  /** Show the mic glyph badge (voice-input affordance). */
  showMic?: boolean;
  listening?: boolean;
  className?: string;
};

/**
 * Avatar that reflects the active personality (icon + hue) and voice (shape + accent).
 * Purely presentational — animates smoothly whenever the passed selection changes.
 */
export function CompanionAvatar({
  voice,
  personality,
  size = 176,
  showMic = true,
  listening = false,
  className = "",
}: Props) {
  const style = personalityStyle(personality);
  const tone = voiceTone(voice);
  const Icon = style.icon;
  const iconSize = Math.round(size * 0.34);
  const micSize = Math.round(size * 0.16);

  // Re-trigger a short "morph" animation whenever the companion changes.
  const key = companionKey(voice, personality);
  const first = useRef(true);
  const [morph, setMorph] = useState(false);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    setMorph(true);
    const t = setTimeout(() => setMorph(false), 420);
    return () => clearTimeout(t);
  }, [key]);

  const label = `${personality?.name ?? "Default"} personality with ${voice?.name ?? "no"} voice`;

  return (
    <div
      role="img"
      aria-label={label}
      className={`relative flex items-center justify-center bg-gradient-to-br ${style.gradient} ${TONE_SHAPE[tone]} ${TONE_ACCENT[tone]} ring-2 ${style.ring} transition-[background,box-shadow,border-radius,transform] duration-500 ease-out ${morph ? "animate-companion-morph" : ""} ${className}`}
      style={{ width: size, height: size }}
    >
      <div
        className={`absolute inset-[6%] ${TONE_SHAPE[tone]} bg-background/10 backdrop-blur-[1px] transition-all duration-500`}
      />
      <Icon
        key={key}
        aria-hidden="true"
        className="relative text-primary-foreground drop-shadow transition-all duration-500 motion-safe:animate-scale-in"
        style={{ width: iconSize, height: iconSize }}
      />
      {showMic && (
        <span
          aria-hidden="true"
          className="absolute bottom-[6%] flex items-center justify-center rounded-full bg-background/85 text-foreground shadow-md transition-all duration-500"
          style={{ width: micSize * 1.7, height: micSize * 1.7 }}
        >
          {listening ? (
            <MicOff style={{ width: micSize, height: micSize }} />
          ) : (
            <Mic style={{ width: micSize, height: micSize }} />
          )}
        </span>
      )}
    </div>
  );
}
