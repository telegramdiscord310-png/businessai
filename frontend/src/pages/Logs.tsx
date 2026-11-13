import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, CircleAlert, Info, RefreshCw, ScrollText, Search, Trash2, TriangleAlert } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";
import { Segmented } from "@/components/ui/segmented";
import { api, errorMessage } from "@/lib/api";
import { daySeparator, sameDay, time } from "@/lib/format";
import type { LogEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

const LEVEL: Record<string, { icon: React.ReactNode; tone: string; label: string }> = {
  ERROR: { icon: <CircleAlert />, tone: "text-danger bg-danger-soft", label: "Erreur" },
  CRITICAL: { icon: <CircleAlert />, tone: "text-danger bg-danger-soft", label: "Erreur grave" },
  WARNING: { icon: <TriangleAlert />, tone: "text-warning bg-warning-soft", label: "Avertissement" },
  INFO: { icon: <Info />, tone: "text-ink-3 bg-surface-2", label: "Information" },
};

function LogRow({ entry }: { entry: LogEntry }) {
  const [open, setOpen] = React.useState(false);
  const level = LEVEL[entry.level] ?? LEVEL.INFO;
  return (
    <li className="border-b border-line/60 last:border-0">
      <button
        className={cn("flex w-full items-start gap-3 px-4 py-3 text-left transition-colors sm:px-5", entry.details ? "hover:bg-surface-2/50" : "cursor-default!")}
        onClick={() => entry.details && setOpen((v) => !v)}
        aria-expanded={entry.details ? open : undefined}
      >
        <span className={cn("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg [&_svg]:size-4", level.tone)} title={level.label}>
          {level.icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] leading-snug break-words">{entry.message}</p>
          <p className="tabular mt-0.5 text-xs text-ink-3">
            {time(entry.created_at)} · {entry.source === "telegram" ? "Service Telegram" : "Site"} · {level.label}
          </p>
        </div>
        {entry.details && <ChevronDown className={cn("mt-1 size-4 shrink-0 text-ink-3 transition-transform duration-200", open && "rotate-180")} />}
      </button>
      {open && entry.details && (
        <pre className="scroll-thin mx-4 mb-3 max-h-80 animate-fade overflow-auto rounded-xl border border-line bg-bg p-3 font-mono text-xs leading-relaxed text-ink-2 sm:mx-5 sm:ml-[60px]">{entry.details}</pre>
      )}
    </li>
  );
}

export function LogsPage() {
  const qc = useQueryClient();
  const [level, setLevel] = React.useState<"" | "warning" | "error">("");
  const [search, setSearch] = React.useState("");
  const [term, setTerm] = React.useState("");
  const [limit, setLimit] = React.useState(100);
  const [confirmClear, setConfirmClear] = React.useState(false);
  React.useEffect(() => {
    const t = setTimeout(() => setTerm(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);
  const logs = useQuery({
    queryKey: ["logs", level, term, limit],
    queryFn: () => api.get<{ logs: LogEntry[]; has_more: boolean }>(`/api/logs?level=${level}&q=${encodeURIComponent(term)}&limit=${limit}`),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  });
  const clear = useMutation({
    mutationFn: () => api.delete("/api/logs"),
    onSuccess: () => {
      toast.success("Journal vidé");
      setConfirmClear(false);
      qc.invalidateQueries({ queryKey: ["logs"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const rows = logs.data?.logs ?? [];

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <p className="text-sm text-ink-2">Ce qui se passe en coulisses : erreurs, avertissements et événements importants. Les secrets (clés, tokens, session) n'y figurent jamais.</p>
      <div className="flex flex-wrap items-center gap-3">
        <Segmented
          label="Filtrer par gravité"
          value={level}
          onChange={setLevel}
          options={[
            { value: "", label: "Tout" },
            { value: "warning", label: "Avertissements" },
            { value: "error", label: "Erreurs" },
          ]}
        />
        <div className="relative min-w-40 flex-1">
          <Search className="pointer-events-none absolute top-3 left-3.5 size-4 text-ink-3" />
          <Input type="search" placeholder="Rechercher dans le journal" aria-label="Rechercher dans le journal" className="pl-10" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Button variant="secondary" size="icon" aria-label="Actualiser" onClick={() => logs.refetch()}>
          <RefreshCw className={cn(logs.isFetching && "animate-spin")} />
        </Button>
        <Button variant="secondary" onClick={() => setConfirmClear(true)} disabled={rows.length === 0}>
          <Trash2 />
          <span className="max-sm:hidden">Vider le journal</span>
        </Button>
      </div>

      {logs.isPending ? (
        <Card className="space-y-3 p-5">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-11" />
          ))}
        </Card>
      ) : logs.isError ? (
        <ErrorState message={errorMessage(logs.error)} onRetry={() => logs.refetch()} />
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            className="py-16"
            icon={<ScrollText />}
            title={level || term ? "Rien ne correspond à ce filtre" : "Le journal est vide"}
            description={level || term ? "Essayez un autre filtre ou une autre recherche." : "Bonne nouvelle : aucune erreur à signaler. Les événements apparaîtront ici au fil de l'eau."}
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <ul>
            {rows.map((entry, index) => {
              const previous = rows[index - 1];
              const newDay = !previous || !sameDay(previous.created_at, entry.created_at);
              return (
                <React.Fragment key={entry.id}>
                  {newDay && <li className="border-b border-line/60 bg-surface-2/60 px-4 py-1.5 text-xs font-semibold text-ink-2 sm:px-5">{daySeparator(entry.created_at)}</li>}
                  <LogRow entry={entry} />
                </React.Fragment>
              );
            })}
          </ul>
          {logs.data?.has_more && (
            <div className="border-t border-line p-3 text-center">
              <Button variant="ghost" size="sm" loading={logs.isFetching} onClick={() => setLimit((l) => l + 100)}>
                Afficher les entrées plus anciennes
              </Button>
            </div>
          )}
        </Card>
      )}
      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        title="Vider le journal ?"
        description="Toutes les entrées seront effacées définitivement. Cela n'a aucun effet sur vos conversations ni sur vos ventes."
        confirmLabel="Vider le journal"
        loading={clear.isPending}
        onConfirm={() => clear.mutate()}
      />
    </div>
  );
}
