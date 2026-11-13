import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Bot,
  BotOff,
  CalendarDays,
  Check,
  ChevronUp,
  Download,
  FileText,
  History,
  ImageIcon,
  MessagesSquare,
  Mic,
  Package,
  Paperclip,
  Pencil,
  Play,
  Search,
  Send,
  SendHorizontal,
  ShoppingBag,
  Sparkles,
  Star,
  Trash2,
  User,
  UserRound,
  X,
} from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/ui/button";
import { Badge, EmptyState, ErrorState, Skeleton } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input, Switch, Textarea } from "@/components/ui/form";
import { Tooltip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { dateTime, daySeparator, euros, listStamp, longDate, number, sameDay, stars, time } from "@/lib/format";
import { useMediaQuery, useStatus } from "@/lib/hooks";
import type { Chat, ChatDetail, Message } from "@/lib/types";
import { cn } from "@/lib/utils";

// ------------------------------------------------------------------ liste des conversations

function aiState(chat: Chat): { on: boolean; label: string } {
  if (!chat.ai_enabled) return { on: false, label: "IA désactivée" };
  if (chat.ai_paused) return { on: false, label: "IA en pause" };
  return { on: true, label: "IA active" };
}

function ChatRow({ chat, active }: { chat: Chat; active: boolean }) {
  const ai = aiState(chat);
  const prefix = chat.last_message_sender === "owner" ? "Vous : " : chat.last_message_sender === "ai" ? "IA : " : chat.last_message_sender === "system" ? "Livraison : " : "";
  return (
    <Link
      to={`/conversations/${chat.id}`}
      className={cn("flex items-center gap-3 rounded-2xl px-3 py-2.5 transition-colors duration-150", active ? "bg-accent-soft" : "hover:bg-surface-2")}
    >
      <div className="relative">
        <Avatar id={chat.id} name={chat.name} hasPhoto={chat.has_photo} version={chat.photo_version} size={46} />
        <Tooltip label={ai.label}>
          <span
            className={cn(
              "absolute -right-0.5 -bottom-0.5 flex size-[18px] items-center justify-center rounded-full ring-2",
              active ? "ring-[color-mix(in_srgb,var(--accent)_14%,var(--surface))]" : "ring-surface",
              ai.on ? "bg-accent text-accent-fg" : "bg-surface-3 text-ink-3",
            )}
          >
            {ai.on ? <Bot className="size-3" /> : <BotOff className="size-3" />}
          </span>
        </Tooltip>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className={cn("truncate text-[14.5px]", chat.unread_count ? "font-semibold" : "font-medium")}>{chat.name}</p>
          <span className={cn("tabular shrink-0 text-xs", chat.unread_count ? "font-medium text-accent" : "text-ink-3")}>{listStamp(chat.last_message_at)}</span>
        </div>
        <div className="mt-0.5 flex items-center justify-between gap-2">
          <p className={cn("truncate text-[13px]", chat.unread_count ? "text-ink-2" : "text-ink-3")}>
            {chat.has_draft ? (
              <span className="font-medium text-accent">Brouillon à valider</span>
            ) : (
              <>
                {prefix && <span className="text-ink-2">{prefix}</span>}
                {chat.last_message_text || "…"}
              </>
            )}
          </p>
          <div className="flex shrink-0 items-center gap-1.5">
            {chat.is_buyer && (
              <Tooltip label="A déjà acheté">
                <Star className="size-3.5 fill-warning text-warning" />
              </Tooltip>
            )}
            {chat.unread_count > 0 && (
              <span className="tabular flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-[11px] font-semibold text-accent-fg">
                {chat.unread_count > 99 ? "99+" : chat.unread_count}
              </span>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}

function ChatList({ activeId }: { activeId?: string }) {
  const [search, setSearch] = React.useState("");
  const [term, setTerm] = React.useState("");
  const { data: status } = useStatus();
  React.useEffect(() => {
    const t = setTimeout(() => setTerm(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);
  const chats = useQuery({
    queryKey: ["chats", term],
    queryFn: () => api.get<Chat[]>(`/api/chats?search=${encodeURIComponent(term)}`),
    placeholderData: (previous) => previous,
  });
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="p-3 pb-2">
        <div className="relative">
          <Search className="pointer-events-none absolute top-3 left-3.5 size-4 text-ink-3" />
          <Input type="search" placeholder="Rechercher par nom" aria-label="Rechercher une conversation" className="rounded-full pl-10" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {chats.isPending ? (
          <div className="space-y-2 p-1">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-center gap-3 px-2 py-2">
                <Skeleton className="size-[46px] rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3.5 w-2/5" />
                  <Skeleton className="h-3 w-4/5" />
                </div>
              </div>
            ))}
          </div>
        ) : chats.isError ? (
          <div className="p-2">
            <ErrorState message={errorMessage(chats.error)} onRetry={() => chats.refetch()} />
          </div>
        ) : chats.data.length === 0 ? (
          term ? (
            <EmptyState icon={<Search />} title="Aucun résultat" description={`Personne ne correspond à « ${term} ».`} />
          ) : (
            <EmptyState
              icon={<MessagesSquare />}
              title="Aucune conversation pour l'instant"
              description={
                status?.telegram.status === "connected"
                  ? "Les messages privés que vous recevez sur Telegram apparaîtront ici, en temps réel."
                  : "Connectez votre compte Telegram pour voir vos messages privés ici."
              }
              action={
                status?.telegram.status !== "connected" && (
                  <Button asChild>
                    <Link to="/telegram">
                      <Send />
                      Connecter Telegram
                    </Link>
                  </Button>
                )
              }
            />
          )
        ) : (
          <div className="space-y-0.5">
            {chats.data.map((chat) => (
              <ChatRow key={chat.id} chat={chat} active={chat.id === activeId} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ bulles

const MEDIA_ICON: Record<string, React.ReactNode> = {
  photo: <ImageIcon />,
  voice: <Mic />,
  audio: <Mic />,
  video: <Play />,
  video_note: <Play />,
  gif: <Play />,
  document: <FileText />,
};

function MediaBlock({ message, onDark }: { message: Message; onDark: boolean }) {
  const url = `/api/messages/${message.id}/media`;
  if (message.has_media_file && (message.media_type === "photo" || message.media_type === "sticker")) {
    return (
      <a href={url} target="_blank" rel="noreferrer" className="mb-1 block">
        <img src={url} alt={message.media_desc ?? "Photo"} loading="lazy" className={cn("max-h-72 rounded-xl object-cover", message.media_type === "sticker" && "max-h-32")} />
      </a>
    );
  }
  if (message.has_media_file && (message.media_type === "voice" || message.media_type === "audio")) {
    return (
      <div className="mb-1">
        <p className={cn("mb-1.5 flex items-center gap-1.5 text-xs", onDark ? "text-white/80" : "text-ink-2")}>
          <Mic className="size-3.5" />
          {message.media_desc}
        </p>
        <audio controls preload="none" src={url} className="h-9 w-56 max-w-full" />
      </div>
    );
  }
  return (
    <div className={cn("mb-1 flex items-center gap-2.5 rounded-xl px-2.5 py-2", onDark ? "bg-white/15" : "bg-surface-3/70")}>
      <span className={cn("flex size-8 items-center justify-center rounded-lg [&_svg]:size-4", onDark ? "bg-white/20" : "bg-surface text-ink-2")}>
        {MEDIA_ICON[message.media_type ?? ""] ?? <Paperclip />}
      </span>
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{message.media_desc ?? "Pièce jointe"}</span>
      {message.has_media_file && (
        <a href={url} download aria-label="Télécharger" className={cn("rounded-lg p-1.5", onDark ? "hover:bg-white/20" : "text-ink-2 hover:bg-surface")}>
          <Download className="size-4" />
        </a>
      )}
    </div>
  );
}

function DraftBubble({ message }: { message: Message }) {
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState(false);
  const [text, setText] = React.useState(message.text);
  React.useEffect(() => setText(message.text), [message.text]);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["messages", message.chat_id] });
    qc.invalidateQueries({ queryKey: ["chats"] });
    qc.invalidateQueries({ queryKey: ["status"] });
  };
  const approve = useMutation({
    mutationFn: () => api.post(`/api/drafts/${message.id}/approve`, { text: editing ? text : null }),
    onSuccess: () => {
      toast.success("Réponse envoyée");
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const discard = useMutation({
    mutationFn: () => api.post(`/api/drafts/${message.id}/discard`),
    onSuccess: () => {
      toast.success("Brouillon supprimé");
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <div className="mt-3 flex animate-in justify-end">
      <div className="w-full max-w-[min(34rem,88%)] rounded-2xl rounded-br-md border border-dashed border-accent/60 bg-accent-soft p-3.5">
        <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-accent">
          <Sparkles className="size-3.5" />
          Brouillon de l'IA · pas encore envoyé
        </p>
        {editing ? (
          <Textarea autoFocus value={text} onChange={(e) => setText(e.target.value)} rows={Math.min(8, Math.max(3, text.split("\n").length + 1))} className="bg-surface" maxLength={4096} />
        ) : (
          <p className="text-[14.5px] leading-relaxed break-words whitespace-pre-wrap">{message.text || <span className="text-ink-3">(pas de texte)</span>}</p>
        )}
        {message.pack_names.length > 0 && (
          <p className="mt-2 flex items-center gap-1.5 text-[13px] text-ink-2">
            <Star className="size-3.5 text-warning" />
            Suivi du lien de paiement : {message.pack_names.join(", ")}
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm" loading={approve.isPending} disabled={discard.isPending || (editing && !text.trim() && message.pack_names.length === 0)} onClick={() => approve.mutate()}>
            <Check />
            {editing ? "Envoyer ma version" : "Valider et envoyer"}
          </Button>
          {editing ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setEditing(false);
                setText(message.text);
              }}
            >
              Annuler
            </Button>
          ) : (
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
              <Pencil />
              Modifier
            </Button>
          )}
          <Button size="sm" variant="ghost" loading={discard.isPending} disabled={approve.isPending} onClick={() => discard.mutate()}>
            <Trash2 />
            Supprimer
          </Button>
        </div>
      </div>
    </div>
  );
}

const SENDER_META: Record<string, { label: string; icon: React.ReactNode }> = {
  ai: { label: "IA", icon: <Sparkles /> },
  owner: { label: "Vous", icon: <User /> },
  system: { label: "Livraison automatique", icon: <Package /> },
};

function Bubble({ message, grouped }: { message: Message; grouped: boolean }) {
  if (message.status === "draft") return <DraftBubble message={message} />;
  const incoming = message.direction === "in";
  const owner = message.sender === "owner";
  const meta = SENDER_META[message.sender];
  const isLink = message.kind === "payment_link";
  const [title, ...rest] = isLink ? message.text.split("\n") : [];
  return (
    <div className={cn("flex animate-in", incoming ? "justify-start" : "justify-end", grouped ? "mt-1" : "mt-3")}>
      <div
        className={cn(
          "relative max-w-[min(34rem,84%)] px-3.5 py-2 text-[14.5px] leading-relaxed",
          "rounded-[18px]",
          incoming && "rounded-bl-md bg-surface-2 text-ink",
          // Mes réponses : couleur d'accent pleine. Réponses de l'IA : accent en teinte légère. Livraisons : neutre.
          owner && "rounded-br-md bg-accent text-accent-fg",
          message.sender === "ai" && "rounded-br-md border border-accent/25 bg-accent-soft text-ink",
          message.sender === "system" && "rounded-br-md border border-line-strong bg-surface-2 text-ink",
        )}
      >
        {!incoming && !grouped && meta && (
          <p className={cn("mb-0.5 flex items-center gap-1 text-[11.5px] font-semibold [&_svg]:size-3", owner ? "text-white/85" : message.sender === "ai" ? "text-accent" : "text-ink-2")}>
            {meta.icon}
            {meta.label}
          </p>
        )}
        {message.media_type && <MediaBlock message={message} onDark={owner} />}
        {isLink ? (
          <div className="flex items-center gap-3 py-0.5">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-warning-soft text-warning">
              <Star className="size-4 fill-current" />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium text-ink-2">Lien de paiement envoyé</p>
              <p className="truncate font-semibold">{title}</p>
              <p className="truncate text-xs text-ink-3">{rest.join(" ")}</p>
            </div>
          </div>
        ) : (
          message.text && <span className="break-words whitespace-pre-wrap">{message.text}</span>
        )}
        <span className={cn("tabular float-right mt-1.5 ml-3 text-[11px] leading-none select-none", owner ? "text-white/70" : "text-ink-3")}>
          {message.imported && (
            <Tooltip label="Message importé depuis l'historique Telegram">
              <History className="mr-1 inline size-3 -translate-y-px" />
            </Tooltip>
          )}
          {time(message.created_at)}
        </span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ fiche client

function CustomerCard({ chat, onImport, importing }: { chat: ChatDetail; onImport: () => void; importing: boolean }) {
  const qc = useQueryClient();
  const patch = useMutation({
    mutationFn: (body: { ai_enabled?: boolean; ai_paused?: boolean }) => api.patch<Chat>(`/api/chats/${chat.id}`, body),
    onSuccess: (_data, body) => {
      qc.invalidateQueries({ queryKey: ["chat", chat.id] });
      qc.invalidateQueries({ queryKey: ["chats"] });
      toast.success(body.ai_enabled === false ? "IA désactivée pour cette conversation" : "IA activée pour cette conversation");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const c = chat.customer;
  return (
    <div className="space-y-6">
      <div className="flex flex-col items-center text-center">
        <Avatar id={chat.id} name={chat.name} hasPhoto={chat.has_photo} version={chat.photo_version} size={76} />
        <p className="mt-3 text-[17px] font-semibold">{chat.name}</p>
        {chat.username && (
          <a href={`https://t.me/${chat.username}`} target="_blank" rel="noreferrer" className="text-[13px] text-accent hover:underline">
            @{chat.username}
          </a>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        <div className="rounded-2xl bg-surface-2 p-3.5">
          <p className="text-xs text-ink-3">Total dépensé</p>
          <p className="tabular mt-1 text-lg leading-tight font-semibold">{euros(c.total_eur)}</p>
          <p className="tabular text-xs text-ink-2">{stars(c.total_stars)}</p>
        </div>
        <div className="rounded-2xl bg-surface-2 p-3.5">
          <p className="text-xs text-ink-3">Packs achetés</p>
          <p className="tabular mt-1 text-lg leading-tight font-semibold">{c.purchases.filter((p) => !p.refunded_at).length}</p>
          <p className="text-xs text-ink-2">{number(c.messages_count)} messages</p>
        </div>
      </div>

      <div className="flex items-center gap-3 text-[13px] text-ink-2">
        <CalendarDays className="size-4 shrink-0 text-ink-3" />
        {c.first_message_at ? <>Premier message le {longDate(c.first_message_at)}</> : "N'a pas encore écrit"}
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold tracking-wide text-ink-3 uppercase">Achats</p>
        {c.purchases.length === 0 ? (
          <p className="text-[13px] text-ink-3">Aucun achat pour l'instant.</p>
        ) : (
          <ul className="space-y-2">
            {c.purchases.map((sale) => (
              <li key={sale.id} className="flex items-center gap-3 rounded-xl border border-line px-3 py-2.5">
                <ShoppingBag className="size-4 shrink-0 text-ink-3" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium">{sale.pack_name}</p>
                  <p className="text-xs text-ink-3">{dateTime(sale.paid_at)}</p>
                </div>
                {sale.refunded_at ? <Badge>Remboursé</Badge> : <span className="tabular text-[13px] font-semibold">{stars(sale.stars)}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-3 border-t border-line pt-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium">Réponses de l'IA</p>
            <p className="text-[13px] leading-snug text-ink-3">Désactivez pour que l'IA ne réponde jamais à cette personne.</p>
          </div>
          <Switch checked={chat.ai_enabled} disabled={patch.isPending} onCheckedChange={(v) => patch.mutate({ ai_enabled: v })} aria-label="Réponses de l'IA pour cette conversation" />
        </div>
        <Button variant="secondary" className="w-full" onClick={onImport} loading={importing}>
          <History />
          Importer l'historique Telegram
        </Button>
        <p className="text-xs leading-snug text-ink-3">
          Récupère les anciens messages de cette conversation. Rien n'est envoyé à la personne.
          {chat.history_imported_at && <> Dernier import le {dateTime(chat.history_imported_at)}.</>}
        </p>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ fil de messages

function Composer({ chat, disabledReason }: { chat: ChatDetail; disabledReason: string | null }) {
  const qc = useQueryClient();
  const [text, setText] = React.useState("");
  const ref = React.useRef<HTMLTextAreaElement>(null);
  const desktop = useMediaQuery("(min-width: 1024px)");
  const send = useMutation({
    mutationFn: (body: string) => api.post(`/api/chats/${chat.id}/messages`, { text: body }),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: ["messages", chat.id] });
      qc.invalidateQueries({ queryKey: ["chat", chat.id] });
      qc.invalidateQueries({ queryKey: ["chats"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  React.useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);
  const submit = () => {
    const body = text.trim();
    if (body && !send.isPending) send.mutate(body);
  };
  const willPause = chat.ai_enabled && !chat.ai_paused;
  return (
    <div className="pb-safe-3 border-t border-line bg-surface px-3 pt-3 sm:px-4">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <textarea
          ref={ref}
          rows={1}
          value={text}
          maxLength={4096}
          disabled={!!disabledReason}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && desktop && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={disabledReason ?? "Écrire un message…"}
          aria-label="Votre message"
          className="scroll-thin min-h-11 flex-1 resize-none rounded-3xl border border-line bg-surface-2 px-4 py-2.5 text-[14.5px] leading-relaxed text-ink placeholder:text-ink-3 focus:border-accent focus:ring-2 focus:ring-accent/25 focus:outline-none disabled:opacity-60"
        />
        <Button size="icon" className="size-11 rounded-full" aria-label="Envoyer" disabled={!text.trim() || !!disabledReason} loading={send.isPending} onClick={submit}>
          {!send.isPending && <SendHorizontal className="size-[18px]" />}
        </Button>
      </div>
      {willPause && !disabledReason && (
        <p className="mx-auto mt-1.5 max-w-3xl px-2 text-xs text-ink-3 max-sm:hidden">En répondant vous-même, vous mettez l'IA en pause sur cette conversation.</p>
      )}
    </div>
  );
}

function Thread({ chatId }: { chatId: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: status } = useStatus();
  const wide = useMediaQuery("(min-width: 1280px)");
  const [limit, setLimit] = React.useState(80);
  const [panelOpen, setPanelOpen] = React.useState(false);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const atBottom = React.useRef(true);
  const restore = React.useRef<number | null>(null);

  React.useEffect(() => {
    setLimit(80);
    atBottom.current = true;
  }, [chatId]);

  const chat = useQuery({ queryKey: ["chat", chatId], queryFn: () => api.get<ChatDetail>(`/api/chats/${chatId}`) });
  const messages = useQuery({
    queryKey: ["messages", chatId, limit],
    queryFn: () => api.get<{ messages: Message[]; has_more: boolean }>(`/api/chats/${chatId}/messages?limit=${limit}`),
    placeholderData: (previous, previousQuery) => (previousQuery?.queryKey[1] === chatId ? previous : undefined),
  });
  const list = messages.data?.messages ?? [];
  const lastId = list.at(-1)?.id;

  // Reste en bas à l'arrivée d'un message ; garde la position quand on charge les plus anciens.
  React.useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (restore.current !== null) {
      el.scrollTop = el.scrollHeight - restore.current;
      restore.current = null;
    } else if (atBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lastId, list.length, chatId]);

  // Ouvrir la conversation la marque comme lue.
  const unread = chat.data?.unread_count ?? 0;
  React.useEffect(() => {
    if (unread > 0 && document.visibilityState === "visible") {
      api.post(`/api/chats/${chatId}/read`).then(() => {
        qc.invalidateQueries({ queryKey: ["chats"] });
        qc.invalidateQueries({ queryKey: ["status"] });
        qc.invalidateQueries({ queryKey: ["chat", chatId] });
      }).catch(() => undefined);
    }
  }, [unread, chatId, lastId, qc]);

  const resume = useMutation({
    mutationFn: (paused: boolean) => api.patch<Chat>(`/api/chats/${chatId}`, { ai_paused: paused }),
    onSuccess: (_data, paused) => {
      qc.invalidateQueries({ queryKey: ["chat", chatId] });
      qc.invalidateQueries({ queryKey: ["chats"] });
      toast.success(paused ? "IA mise en pause sur cette conversation" : "IA réactivée : elle répondra au prochain message reçu");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const importHistory = useMutation({
    mutationFn: () => api.post<{ added: number }>(`/api/chats/${chatId}/import-history`, { limit: 500 }),
    onSuccess: (data) => {
      toast.success(data.added > 0 ? `${number(data.added)} messages importés` : "L'historique est déjà à jour");
      qc.invalidateQueries({ queryKey: ["messages", chatId] });
      qc.invalidateQueries({ queryKey: ["chat", chatId] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (chat.isError) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState
          icon={<MessagesSquare />}
          title="Conversation introuvable"
          description={errorMessage(chat.error)}
          action={
            <Button variant="secondary" onClick={() => navigate("/conversations")}>
              Retour aux conversations
            </Button>
          }
        />
      </div>
    );
  }
  const c = chat.data;
  const ai = c ? aiState(c) : null;
  const connected = status?.telegram.status === "connected";
  const customer = c && <CustomerCard chat={c} onImport={() => importHistory.mutate()} importing={importHistory.isPending} />;

  return (
    <div className="flex h-full min-w-0 flex-1">
      <div className="flex h-full min-w-0 flex-1 flex-col">
        {/* En-tête de la conversation */}
        <div className="flex h-[60px] shrink-0 items-center gap-2 border-b border-line bg-surface px-2 sm:px-4">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Retour aux conversations" onClick={() => navigate("/conversations")}>
            <ArrowLeft className="size-5" />
          </Button>
          {c ? (
            <button className="flex min-w-0 flex-1 items-center gap-3 rounded-xl py-1 pr-2 text-left" onClick={() => setPanelOpen((v) => !v)} aria-label="Afficher la fiche client">
              <Avatar id={c.id} name={c.name} hasPhoto={c.has_photo} version={c.photo_version} size={38} />
              <div className="min-w-0">
                <p className="truncate text-[15px] leading-tight font-semibold">{c.name}</p>
                <p className={cn("flex items-center gap-1 truncate text-xs", ai?.on ? "text-accent" : "text-ink-3")}>
                  {ai?.on ? <Bot className="size-3.5" /> : <BotOff className="size-3.5" />}
                  {ai?.label}
                </p>
              </div>
            </button>
          ) : (
            <div className="flex flex-1 items-center gap-3">
              <Skeleton className="size-[38px] rounded-full" />
              <Skeleton className="h-4 w-32" />
            </div>
          )}
          {c && c.ai_enabled && (
            <Button variant="secondary" size="sm" loading={resume.isPending} onClick={() => resume.mutate(!c.ai_paused)} className="max-sm:px-2.5">
              {c.ai_paused ? <Bot /> : <BotOff />}
              <span className="max-sm:hidden">{c.ai_paused ? "Réactiver l'IA" : "Mettre l'IA en pause"}</span>
              <span className="sm:hidden">{c.ai_paused ? "Réactiver" : "Pause"}</span>
            </Button>
          )}
          <Tooltip label="Fiche client">
            <Button variant={panelOpen ? "secondary" : "ghost"} size="icon" aria-label="Fiche client" onClick={() => setPanelOpen((v) => !v)}>
              <UserRound className="size-[18px]" />
            </Button>
          </Tooltip>
        </div>

        {/* Messages */}
        <div
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
          className="scroll-thin min-h-0 flex-1 overflow-y-auto bg-bg px-3 py-4 sm:px-6"
        >
          <div className="mx-auto max-w-3xl">
            {messages.isPending ? (
              <div className="space-y-3 pt-4">
                <Skeleton className="h-10 w-48 rounded-2xl" />
                <Skeleton className="ml-auto h-14 w-64 rounded-2xl" />
                <Skeleton className="h-10 w-56 rounded-2xl" />
              </div>
            ) : messages.isError ? (
              <ErrorState message={errorMessage(messages.error)} onRetry={() => messages.refetch()} />
            ) : list.length === 0 ? (
              <EmptyState
                icon={<History />}
                title="Aucun message enregistré"
                description="Importez l'historique pour retrouver vos anciens échanges avec cette personne."
                action={
                  <Button variant="secondary" loading={importHistory.isPending} onClick={() => importHistory.mutate()}>
                    <History />
                    Importer l'historique
                  </Button>
                }
              />
            ) : (
              <>
                {messages.data?.has_more && (
                  <div className="mb-2 flex justify-center">
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={messages.isFetching}
                      onClick={() => {
                        const el = scrollRef.current;
                        if (el) restore.current = el.scrollHeight - el.scrollTop;
                        setLimit((l) => l + 120);
                      }}
                    >
                      <ChevronUp />
                      Messages précédents
                    </Button>
                  </div>
                )}
                {list.map((message, index) => {
                  const previous = list[index - 1];
                  const newDay = !previous || !sameDay(previous.created_at, message.created_at);
                  const grouped =
                    !newDay && !!previous && previous.sender === message.sender && previous.status === message.status &&
                    new Date(message.created_at).getTime() - new Date(previous.created_at).getTime() < 5 * 60_000;
                  return (
                    <React.Fragment key={message.id}>
                      {newDay && (
                        <div className="my-4 flex justify-center">
                          <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-2">{daySeparator(message.created_at)}</span>
                        </div>
                      )}
                      <Bubble message={message} grouped={grouped} />
                    </React.Fragment>
                  );
                })}
              </>
            )}
          </div>
        </div>

        {/* Bandeau de pause + zone de saisie */}
        {c && c.ai_enabled && c.ai_paused && (
          <div className="flex items-center justify-between gap-3 border-t border-line bg-warning-soft px-4 py-2.5 text-[13px]">
            <span className="flex items-center gap-2 text-ink">
              <BotOff className="size-4 shrink-0 text-warning" />
              L'IA est en pause ici : c'est vous qui répondez.
            </span>
            <button className="shrink-0 font-semibold text-accent hover:underline" onClick={() => resume.mutate(false)}>
              Réactiver l'IA
            </button>
          </div>
        )}
        {c && <Composer chat={c} disabledReason={connected ? null : "Connectez Telegram pour pouvoir répondre"} />}
      </div>

      {/* Fiche client : colonne sur grand écran, fenêtre sinon */}
      {wide
        ? panelOpen && (
            <aside className="scroll-thin hidden w-[320px] shrink-0 animate-fade overflow-y-auto border-l border-line bg-surface p-5 xl:block">
              <div className="mb-4 flex items-center justify-between">
                <p className="text-[15px] font-semibold">Fiche client</p>
                <Button variant="ghost" size="icon-sm" aria-label="Fermer la fiche client" onClick={() => setPanelOpen(false)}>
                  <X />
                </Button>
              </div>
              {customer ?? <Skeleton className="h-64" />}
            </aside>
          )
        : (
            <Dialog open={panelOpen} onOpenChange={setPanelOpen} title="Fiche client">
              {customer ?? <Skeleton className="h-64" />}
            </Dialog>
          )}
    </div>
  );
}

// ------------------------------------------------------------------ page

export function ConversationsPage() {
  const { chatId } = useParams();
  return (
    <div className="flex h-full">
      <div className={cn("h-full w-full shrink-0 border-line bg-surface lg:w-[360px] lg:border-r xl:w-[380px]", chatId && "max-lg:hidden")}>
        <ChatList activeId={chatId} />
      </div>
      <div className={cn("h-full min-w-0 flex-1", !chatId && "max-lg:hidden")}>
        {chatId ? (
          <Thread key={chatId} chatId={chatId} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <EmptyState icon={<MessagesSquare />} title="Choisissez une conversation" description="Sélectionnez une personne dans la liste pour lire ses messages et lui répondre." />
          </div>
        )}
      </div>
    </div>
  );
}
