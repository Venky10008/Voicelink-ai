import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { Send, Bot, Loader2, Info, X } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { PERSONALITY_KEY, SELECTION_EVENT, readSelection } from "@/lib/selection";
import { ActiveSelectionBanner } from "@/components/active-selection-banner";
import { EmotionPill } from "@/components/emotion-pill";
import { API_BASE_URL, ApiError, apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/chat")({ component: ChatPage });

export type Message = { id: string; role: "user" | "ai"; text: string };

function ChatPage({ initialMessages = [] as Message[] }: { initialMessages?: Message[] }) {
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [emotion, setEmotion] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [personality, setPersonality] = useState<string | null>(null);
  const { token } = useAuth();
  const initialMessagesRef = useRef(initialMessages);
  const abortRef = useRef<AbortController | null>(null);

  // Cancel any in-flight stream when leaving the chat screen.
  useEffect(() => () => abortRef.current?.abort(), []);

  // Fade the detected mood chip out a few seconds after it appears.
  useEffect(() => {
    if (!emotion || emotion === "neutral") return;
    const timer = setTimeout(() => setEmotion(null), 6000);
    return () => clearTimeout(timer);
  }, [emotion]);

  useEffect(() => {
    const sync = () => setPersonality(readSelection(PERSONALITY_KEY)?.name ?? null);
    sync();
    window.addEventListener(SELECTION_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(SELECTION_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, typing]);

  // Load the last saved chat from the backend so conversations survive refreshes.
  useEffect(() => {
    if (initialMessagesRef.current.length > 0) return; // data provided externally
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch<{
          messages: { role: string; content: string; created_at: string; source?: string }[];
        }>("/messages", { token });
        if (cancelled) return;
        const loaded: Message[] = data.messages
          .filter((m) => m.source !== "call") // keep the text chat clean
          .map((m) => ({
            id: `hist-${m.created_at}`,
            role: m.role === "assistant" ? ("ai" as const) : ("user" as const),
            text: m.content,
          }));
        if (loaded.length > 0) setMessages(loaded);
      } catch {
        /* best-effort — start with an empty chat if loading fails */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);


  // Stream tokens from POST /chat/stream (SSE). Falls back to POST /chat.
  const streamMessage = async (text: string, personalityId: string | null, aiId: string): Promise<string> => {
    const controller = new AbortController();
    abortRef.current = controller;
    const res = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message: text, personality: personalityId }),
      signal: controller.signal,
    });

    if (!res.ok || !res.body) {
      let detail = `Request failed (${res.status})`;
      try {
        const data = (await res.json()) as { detail?: unknown };
        if (typeof data?.detail === "string") detail = data.detail;
      } catch {
        /* keep the generic message */
      }
      throw new ApiError(detail, res.status);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let full = "";
    let firstToken = true;

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const payload = trimmed.slice(5).trim();
        if (!payload) continue;
        let data: { type?: string; content?: string; emotion?: string; detail?: string; notice?: string };
        try {
          data = JSON.parse(payload);
        } catch {
          continue;
        }
        if (data.type === "emotion" && data.emotion) {
          setEmotion(data.emotion);
        } else if (data.type === "fresh_start") {
          // The 100-conversation prototype quota was reached: the backend wiped
          // this account's history + memories. Clear the chat and tell the user.
          if (abortRef.current === controller) abortRef.current = null;
          setNotice(data.notice ?? "Your chat history was reset for a fresh start.");
          setMessages([]);
          controller.abort(); // release the half-consumed SSE stream
          return "";
        } else if (data.type === "token" && data.content) {
          full += data.content;
          const chunk = data.content;
          // Once the first token arrives, hide the typing indicator — the
          // streaming text itself is now the activity signal.
          if (firstToken) {
            firstToken = false;
            setTyping(false);
          }
          setMessages((m) => m.map((msg) => (msg.id === aiId ? { ...msg, text: msg.text + chunk } : msg)));
        } else if (data.type === "error" && data.detail) {
          throw new ApiError(data.detail, 502);
        }
      }
    }
    if (abortRef.current === controller) abortRef.current = null;
    return full;
  };

  // Wire to POST /chat/stream with a POST /chat fallback.
  const onSendMessage = async (text: string) => {
    const userMsg: Message = { id: crypto.randomUUID(), role: "user", text };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setTyping(true);

    const aiId = crypto.randomUUID();
    setMessages((m) => [...m, { id: aiId, role: "ai", text: "" }]);

    try {
      const personalityId = readSelection(PERSONALITY_KEY)?.id ?? null;
      let replyText = "";
      try {
        replyText = await streamMessage(text, personalityId, aiId);
      } catch (err) {
        // The component unmounted mid-stream — stop without side effects.
        if (err instanceof DOMException && err.name === "AbortError") return;
        // Streaming failed — fall back to the classic endpoint.
        const data = await apiFetch<{
          reply: string;
          emotion?: string;
          fresh_start?: boolean;
          notice?: string | null;
        }>("/chat", {
          method: "POST",
          body: { message: text, personality: personalityId },
          token,
        });
        if (data.emotion) setEmotion(data.emotion);
        replyText = data.reply;
        if (data.fresh_start) {
          setNotice(data.notice ?? "Your chat history was reset for a fresh start.");
          setMessages([]);
        }
      }
      const finalText = replyText.trim();
      setMessages((m) => m.map((msg) => (msg.id === aiId ? { ...msg, text: finalText || "…" } : msg)));
    } catch (err) {
      // Remove the failed exchange so the user can retry.
      setMessages((m) => m.filter((msg) => msg.id !== aiId && msg.id !== userMsg.id));
      toast.error(err instanceof Error ? err.message : "Failed to send message.");
    } finally {
      setTyping(false);
    }
  };

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const t = input.trim();
    if (!t || typing) return; // ignore Enter while a reply is streaming
    onSendMessage(t);
  };

  return (
    <AppShell title="Text Chat">
      <div className="flex flex-col h-[calc(100vh-4rem)]">
        <div className="border-b border-border/50 px-4 sm:px-6 py-2">
          <ActiveSelectionBanner />
        </div>

        {notice && (
          <div className="border-b border-amber-500/30 bg-amber-500/10 px-4 sm:px-6 py-3">
            <div className="max-w-3xl mx-auto flex items-start gap-2.5 text-sm text-amber-700 dark:text-amber-300 animate-in fade-in slide-in-from-top-1">
              <Info className="h-4 w-4 mt-0.5 shrink-0" />
              <span className="flex-1">{notice}</span>
              <button
                type="button"
                onClick={() => setNotice(null)}
                className="shrink-0 rounded-md p-1 hover:bg-amber-500/20 transition-colors"
                aria-label="Dismiss notice"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 sm:p-6">

          <div className="max-w-3xl mx-auto space-y-4">
            {messages.length === 0 && (
              <div className="text-center py-16 animate-in fade-in duration-500">
                <div className="h-16 w-16 rounded-2xl bg-gradient-primary shadow-glow mx-auto flex items-center justify-center mb-4 animate-float-slow">
                  <Bot className="h-8 w-8 text-primary-foreground" />
                </div>
                <h2 className="font-display text-xl font-semibold">Start a conversation</h2>
                <p className="text-sm text-muted-foreground mt-1">Ask anything. I'm listening.</p>
              </div>
            )}
            {messages.map((m) => {
              // Hide the placeholder AI bubble until the first token streams in;
              // the typing indicator covers that brief window instead.
              if (m.role === "ai" && !m.text) return null;
              return (
              <div
                key={m.id}
                className={`flex gap-3 animate-in fade-in slide-in-from-bottom-2 duration-300 ${
                  m.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                {m.role === "ai" && (
                  <Avatar className="h-8 w-8 shrink-0">
                    <AvatarFallback className="bg-gradient-primary text-primary-foreground">
                      <Bot className="h-4 w-4" />
                    </AvatarFallback>
                  </Avatar>
                )}
                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                    m.role === "user"
                      ? "bg-gradient-primary text-primary-foreground rounded-tr-sm shadow-glow"
                      : "bg-card border rounded-tl-sm"
                  }`}
                >
                  {m.text}
                </div>
                {m.role === "user" && (
                  <Avatar className="h-8 w-8 shrink-0">
                    <AvatarFallback className="bg-accent text-accent-foreground">Me</AvatarFallback>
                  </Avatar>
                )}
              </div>
              );
            })}

            {typing && (
              <div className="flex gap-3 justify-start animate-in fade-in">
                <Avatar className="h-8 w-8">
                  <AvatarFallback className="bg-gradient-primary text-primary-foreground">
                    <Bot className="h-4 w-4" />
                  </AvatarFallback>
                </Avatar>
                <div className="bg-card border rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-1">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="h-2 w-2 rounded-full bg-muted-foreground/70 inline-block"
                      style={{ animation: `typing-dot 1.2s ease-in-out ${i * 0.15}s infinite` }}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {emotion && emotion !== "neutral" && (
          <div className="pointer-events-none fixed bottom-24 left-1/2 z-30 -translate-x-1/2">
            <EmotionPill emotion={emotion} />
          </div>
        )}

        <form onSubmit={submit} className="border-t border-border/50 glass p-4">
          <div className="max-w-3xl mx-auto flex gap-2 items-end">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
              placeholder="Type a message…"
              rows={1}
              className="min-h-11 resize-none rounded-xl"
            />
            <Button type="submit" disabled={!input.trim() || typing}
              className="h-11 w-11 shrink-0 rounded-xl bg-gradient-primary text-primary-foreground shadow-glow p-0">
              {typing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </div>
        </form>
      </div>
    </AppShell>
  );
}
