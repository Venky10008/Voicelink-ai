import {
  Heart,
  GraduationCap,
  BookOpen,
  Briefcase,
  Users,
  Map,
  Languages,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

export type PersonalityStyle = {
  icon: LucideIcon;
  /** Tailwind gradient stops — same art style, different hue per personality. */
  gradient: string;
  ring: string;
};

const PERSONALITY_STYLES: Record<string, PersonalityStyle> = {
  girlfriend: { icon: Heart, gradient: "from-rose-500 to-pink-600", ring: "ring-rose-400/50" },
  friend: { icon: Heart, gradient: "from-pink-500 to-rose-500", ring: "ring-rose-400/50" },
  mentor: { icon: GraduationCap, gradient: "from-violet-500 to-indigo-500", ring: "ring-indigo-400/50" },
  teacher: { icon: BookOpen, gradient: "from-sky-500 to-cyan-500", ring: "ring-cyan-400/50" },
  coach: { icon: Briefcase, gradient: "from-amber-500 to-orange-500", ring: "ring-amber-400/50" },
  study: { icon: Users, gradient: "from-emerald-500 to-teal-500", ring: "ring-emerald-400/50" },
  travel: { icon: Map, gradient: "from-fuchsia-500 to-pink-500", ring: "ring-fuchsia-400/50" },
  language: { icon: Languages, gradient: "from-red-500 to-orange-500", ring: "ring-orange-400/50" },
};

const DEFAULT_STYLE: PersonalityStyle = {
  icon: Sparkles,
  gradient: "from-primary to-accent",
  ring: "ring-primary/50",
};

/** Resolve by personality id ("teacher") or display name ("Interview Coach"). */
export function personalityStyle(personality?: { id?: string; name?: string } | null): PersonalityStyle {
  if (!personality) return DEFAULT_STYLE;
  const key = (personality.id ?? "").toLowerCase();
  if (PERSONALITY_STYLES[key]) return PERSONALITY_STYLES[key];
  const name = (personality.name ?? "").toLowerCase();
  const byName = Object.keys(PERSONALITY_STYLES).find((k) => name.includes(k));
  if (byName) return PERSONALITY_STYLES[byName]!;
  if (name.includes("interview")) return PERSONALITY_STYLES.coach!;
  return DEFAULT_STYLE;
}

export type VoiceTone = "soft" | "grounded" | "neutral";

const SOFT_VOICES = ["aria", "luna", "nova"];
const GROUNDED_VOICES = ["kai", "rex", "orin"];

/** Subtle tone cue per voice — a shape/accent difference, nothing stereotyped. */
export function voiceTone(voice?: { name?: string } | null): VoiceTone {
  const name = (voice?.name ?? "").toLowerCase();
  if (SOFT_VOICES.includes(name)) return "soft";
  if (GROUNDED_VOICES.includes(name)) return "grounded";
  return "neutral";
}

/** Corner rounding: rounder + airier for soft voices, squarer for grounded ones. */
export const TONE_SHAPE: Record<VoiceTone, string> = {
  soft: "rounded-full",
  grounded: "rounded-[38%]",
  neutral: "rounded-[45%]",
};

export const TONE_ACCENT: Record<VoiceTone, string> = {
  soft: "shadow-[0_0_40px_-8px_hsl(320_90%_65%/0.55)]",
  grounded: "shadow-[0_0_40px_-8px_hsl(210_90%_60%/0.55)]",
  neutral: "shadow-glow",
};

/** Waveform bar rounding/width cue per voice tone — keeps the call UI consistent. */
export const TONE_BAR: Record<VoiceTone, string> = {
  soft: "w-1.5 rounded-full",
  grounded: "w-2 rounded-sm",
  neutral: "w-1.5 rounded-md",
};

/** A stable key that changes whenever the active companion changes. */
export function companionKey(
  voice?: { id?: string; name?: string } | null,
  personality?: { id?: string; name?: string } | null,
) {
  return `${voice?.id ?? voice?.name ?? "none"}::${personality?.id ?? personality?.name ?? "none"}`;
}
