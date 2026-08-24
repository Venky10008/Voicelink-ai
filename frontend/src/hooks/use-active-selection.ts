import { useCallback, useEffect, useState } from "react";
import {
  PERSONALITY_KEY,
  SELECTION_EVENT,
  VOICE_KEY,
  readSelectionStrict,
  type StoredSelection,
} from "@/lib/selection";

export type ActiveSelection = {
  voice: StoredSelection | null;
  personality: StoredSelection | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
};

/**
 * Loads the active voice/personality. Exposes loading + error states so screens
 * can show a skeleton while resolving and a retry banner when it fails.
 */
export function useActiveSelection(): ActiveSelection {
  const [voice, setVoice] = useState<StoredSelection | null>(null);
  const [personality, setPersonality] = useState<StoredSelection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    try {
      setVoice(readSelectionStrict(VOICE_KEY));
      setPersonality(readSelectionStrict(PERSONALITY_KEY));
    } catch (e) {
      setVoice(null);
      setPersonality(null);
      setError(e instanceof Error ? e.message : "Could not load your selection.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    window.addEventListener(SELECTION_EVENT, load);
    window.addEventListener("storage", load);
    return () => {
      window.removeEventListener(SELECTION_EVENT, load);
      window.removeEventListener("storage", load);
    };
  }, [load]);

  return { voice, personality, loading, error, retry: load };
}
