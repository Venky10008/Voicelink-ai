import { Link } from "@tanstack/react-router";
import { Mic2, Sparkles } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { CompanionAvatar } from "@/components/companion-avatar";
import { useActiveSelection } from "@/hooks/use-active-selection";

/** Small header strip showing the currently active voice + personality. */
export function ActiveSelectionBanner({ className = "" }: { className?: string }) {
  const { voice, personality, loading } = useActiveSelection();

  return (
    <div
      className={`flex flex-wrap items-center justify-center gap-2 text-xs text-muted-foreground ${className}`}
    >
      {loading ? (
        <>
          <Skeleton className="h-6 w-28 rounded-full" />
          <Skeleton className="h-6 w-32 rounded-full" />
        </>
      ) : (
        <>
          {(voice || personality) && (
            <CompanionAvatar
              voice={voice}
              personality={personality}
              size={28}
              showMic={false}
            />
          )}
          {voice ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/50 bg-primary/10 px-3 py-1 text-foreground">
              <Mic2 className="h-3 w-3 text-primary" /> Voice · {voice.name}
            </span>
          ) : (
            <Link
              to="/voices"
              className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 hover:text-foreground transition-colors"
            >
              <Mic2 className="h-3 w-3" /> No voice selected
            </Link>
          )}
          {personality ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1">
              <Sparkles className="h-3 w-3 text-primary" /> Personality · {personality.name}
            </span>
          ) : (
            <Link
              to="/personalities"
              className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 hover:text-foreground transition-colors"
            >
              <Sparkles className="h-3 w-3" /> No personality selected
            </Link>
          )}
        </>
      )}
    </div>
  );
}
