import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Search, MessageSquare, Phone, Bot } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/history")({ component: HistoryPage });

export type ConversationMessage = {
  role: string;
  content: string;
  created_at: string;
  source?: string;
};

export type Conversation = {
  id: string;
  title: string;
  preview: string;
  type: "chat" | "call";
  date: string; // ISO
  messages?: ConversationMessage[];
};

const defaults: Conversation[] = [
  { id: "1", title: "Trip planning to Kyoto", preview: "Talked about the best temples to visit…", type: "chat", date: new Date().toISOString() },
  { id: "2", title: "Interview practice", preview: "Ran through 5 behavioral questions.", type: "call", date: new Date(Date.now() - 3600e3).toISOString() },
  { id: "3", title: "Late-night thoughts", preview: "Vented about work stress.", type: "chat", date: new Date(Date.now() - 86400e3).toISOString() },
  { id: "4", title: "Spanish practice", preview: "Rolled through 20 phrases.", type: "call", date: new Date(Date.now() - 2 * 86400e3).toISOString() },
];

type BackendConversation = {
  id: number;
  title: string;
  preview: string;
  type: "chat" | "call";
  date: string;
  messages: ConversationMessage[];
};

function groupByDate(items: Conversation[]) {
  const groups: Record<string, Conversation[]> = {};
  for (const c of items) {
    const d = new Date(c.date);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const yest = new Date(today); yest.setDate(yest.getDate() - 1);
    let key: string;
    if (d >= today) key = "Today";
    else if (d >= yest) key = "Yesterday";
    else key = d.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
    (groups[key] ||= []).push(c);
  }
  return groups;
}

function HistoryPage({
  conversations: initialConversations,
  loading: initialLoading = false,
}: { conversations?: Conversation[]; loading?: boolean }) {
  const { token } = useAuth();
  const [conversations, setConversations] = useState<Conversation[]>(initialConversations ?? defaults);
  const [loading, setLoading] = useState(initialLoading);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Conversation | null>(null);

  // Load conversation history from the backend.
  useEffect(() => {
    if (initialConversations) return; // data provided externally — don't fetch
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await apiFetch<{ conversations: BackendConversation[] }>("/history", { token });
        if (!cancelled) {
          setConversations(
            data.conversations.map((c) => ({
              id: String(c.id),
              title: c.title,
              preview: c.preview,
              type: c.type,
              date: c.date,
              messages: c.messages ?? [],
            }))
          );
        }
      } catch (err) {
        if (!cancelled) {
          setConversations([]); // never show mock data as if it were real
          toast.error(err instanceof Error ? err.message : "Could not load history.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialConversations, token]);

  const filtered = useMemo(
    () => conversations.filter((c) => (c.title + c.preview).toLowerCase().includes(q.toLowerCase())),
    [conversations, q]
  );
  const groups = groupByDate(filtered);

  const onOpenConversation = (c: Conversation) => setOpen(c);

  return (
    <AppShell title="History">
      <div className="p-6 sm:p-8 max-w-3xl mx-auto">
        <div className="mb-6">
          <h1 className="font-display text-3xl font-bold">Conversation History</h1>
          <p className="text-muted-foreground mt-1">Everything you've talked about.</p>
        </div>
        <div className="relative mb-6">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search conversations…" className="pl-9 h-11" />
        </div>

        {loading && (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="glass border rounded-xl p-4 flex gap-3 items-center">
                <Skeleton className="h-9 w-9 rounded-lg shrink-0" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-3 w-3/4" />
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && Object.keys(groups).length === 0 && (
          <p className="text-center text-sm text-muted-foreground py-12">No conversations found.</p>
        )}

        <div className="space-y-6">
          {!loading && Object.entries(groups).map(([date, items]) => (
            <div key={date}>
              <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2 px-1">{date}</div>
              <div className="space-y-2">
                {items.map((c) => (
                  <button key={c.id} onClick={() => onOpenConversation(c)}
                    className="w-full text-left glass border rounded-xl p-4 hover:shadow-elegant hover:-translate-y-0.5 transition-all flex gap-3 items-start">
                    <div className={`h-9 w-9 rounded-lg flex items-center justify-center shrink-0 ${
                      c.type === "call" ? "bg-emerald-500/20 text-emerald-500" : "bg-primary/20 text-primary"
                    }`}>
                      {c.type === "call" ? <Phone className="h-4 w-4" /> : <MessageSquare className="h-4 w-4" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-medium truncate">{c.title}</div>
                      <div className="text-sm text-muted-foreground truncate">{c.preview}</div>
                    </div>
                    <div className="text-xs text-muted-foreground shrink-0">
                      {new Date(c.date).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <Dialog open={open !== null} onOpenChange={(v) => { if (!v) setOpen(null); }}>
        <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 pr-8">
              {open?.type === "call" ? <Phone className="h-4 w-4 text-emerald-500" /> : <MessageSquare className="h-4 w-4 text-primary" />}
              <span className="truncate">{open?.title}</span>
            </DialogTitle>
            <DialogDescription className="flex items-center gap-2">
              <Badge variant="secondary" className="text-xs">{open?.type === "call" ? "Voice call" : "Text chat"}</Badge>
              {open && new Date(open.date).toLocaleString(undefined, {
                month: "long", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
              })}
            </DialogDescription>
          </DialogHeader>

          <div className="flex-1 overflow-y-auto space-y-3 pr-1">
            {(open?.messages ?? []).length === 0 ? (
              <p className="text-center text-sm text-muted-foreground py-10">No saved messages for this conversation.</p>
            ) : (
              (open?.messages ?? []).map((m, i) => {
                const isUser = m.role !== "assistant";
                return (
                  <div key={i} className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
                    {!isUser && (
                      <Avatar className="h-7 w-7 shrink-0">
                        <AvatarFallback className="bg-gradient-primary text-primary-foreground">
                          <Bot className="h-3.5 w-3.5" />
                        </AvatarFallback>
                      </Avatar>
                    )}
                    <div
                      className={`max-w-[80%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                        isUser
                          ? "bg-gradient-primary text-primary-foreground rounded-tr-sm shadow-glow"
                          : "bg-card border rounded-tl-sm"
                      }`}
                    >
                      {m.content}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
