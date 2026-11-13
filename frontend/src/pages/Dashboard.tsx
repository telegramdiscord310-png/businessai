import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  Clock,
  Download,
  MessagesSquare,
  Package,
  Percent,
  RotateCcw,
  Send,
  ShoppingBag,
  Sparkles,
  TriangleAlert,
  Undo2,
  Users,
  Zap,
} from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, EmptyState, ErrorState, Skeleton } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Segmented } from "@/components/ui/segmented";
import { Tooltip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { chartDay, dateTime, euros, eurosRound, longDate, number, percent, stars } from "@/lib/format";
import { useStatus, useToggleAI } from "@/lib/hooks";
import type { Amount, Dashboard, Sale, Status } from "@/lib/types";
import { cn } from "@/lib/utils";

// ------------------------------------------------------------------ parcours guidé

function OnboardingChecklist({ status }: { status: Status }) {
  const toggle = useToggleAI();
  const o = status.onboarding;
  const steps = [
    { done: o.telegram, title: "Connecter Telegram", text: "Reliez votre compte personnel pour recevoir et envoyer les messages.", to: "/telegram", cta: "Connecter", icon: Send },
    { done: o.ai, title: "Configurer l'IA", text: "Indiquez votre clé API et décrivez la personnalité de votre assistant.", to: "/ia", cta: "Configurer", icon: Sparkles },
    { done: o.pack, title: "Créer un premier pack", text: "Ajoutez un contenu à vendre, avec son prix en Stars.", to: "/packs?nouveau=1", cta: "Créer un pack", icon: Package },
    { done: o.enabled, title: "Activer les réponses", text: "L'IA commence à répondre aux nouveaux messages privés.", cta: "Activer", icon: Zap },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  const current = steps.findIndex((s) => !s.done);
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-4 px-5 pt-5 sm:px-6 sm:pt-6">
        <div>
          <h2 className="text-[17px] font-semibold">Mise en route</h2>
          <p className="mt-0.5 text-[13px] text-ink-3">4 étapes pour que votre assistant réponde et vende à votre place.</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="tabular text-[13px] font-medium text-ink-2">{doneCount} sur 4</span>
          <div className="h-1.5 w-28 overflow-hidden rounded-full bg-surface-3">
            <div className="h-full rounded-full bg-accent transition-all duration-500" style={{ width: `${(doneCount / 4) * 100}%` }} />
          </div>
        </div>
      </div>
      <ol className="grid gap-3 p-5 sm:grid-cols-2 sm:p-6 xl:grid-cols-4">
        {steps.map((step, index) => {
          const isCurrent = index === current;
          const locked = index === 3 && !(o.telegram && o.ai);
          return (
            <li
              key={step.title}
              className={cn(
                "flex flex-col rounded-2xl border p-4 transition-colors",
                step.done ? "border-line bg-surface-2/50" : isCurrent ? "border-accent/50 bg-accent-soft" : "border-line bg-surface-2/50",
              )}
            >
              <div className="mb-3 flex items-center justify-between">
                <span
                  className={cn(
                    "flex size-8 items-center justify-center rounded-full text-[13px] font-semibold",
                    step.done ? "bg-success-soft text-success" : isCurrent ? "bg-accent text-accent-fg" : "bg-surface-3 text-ink-3",
                  )}
                >
                  {step.done ? <Check className="size-4" /> : index + 1}
                </span>
                {step.done && <span className="text-xs font-medium text-success">Terminé</span>}
              </div>
              <p className={cn("text-sm font-semibold", step.done && "text-ink-2")}>{step.title}</p>
              <p className="mt-1 flex-1 text-[13px] leading-snug text-ink-3">{step.text}</p>
              {!step.done &&
                (step.to ? (
                  <Button asChild size="sm" variant={isCurrent ? "primary" : "secondary"} className="mt-4 self-start">
                    <Link to={step.to}>
                      {step.cta}
                      <ArrowRight />
                    </Link>
                  </Button>
                ) : (
                  <Tooltip label={locked ? "Terminez d'abord les étapes 1 et 2." : "Vous pourrez mettre l'IA en pause à tout moment."}>
                    <span className="mt-4 self-start">
                      <Button size="sm" variant={isCurrent ? "primary" : "secondary"} disabled={locked} loading={toggle.isPending} onClick={() => toggle.mutate(true)}>
                        {step.cta}
                      </Button>
                    </span>
                  </Tooltip>
                ))}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

// ------------------------------------------------------------------ chiffres clés

function Delta({ current, previous, versus }: { current: number; previous: number; versus: string }) {
  if (current === 0 && previous === 0) return <span className="text-xs text-ink-3">Pas encore de vente</span>;
  if (previous === 0) return <span className="text-xs text-ink-3">Rien {versus}</span>;
  const change = ((current - previous) / previous) * 100;
  const up = change >= 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className="flex items-center gap-1 text-xs text-ink-3">
      <span className={cn("flex items-center gap-0.5 font-medium", up ? "text-success" : "text-danger")}>
        <Icon className="size-3.5" />
        {up ? "+" : "−"}
        {percent(Math.abs(change))}
      </span>
      {versus}
    </span>
  );
}

function RevenueCard({ label, amount, footer, highlight }: { label: string; amount: Amount; footer: React.ReactNode; highlight?: boolean }) {
  return (
    <Card className={cn("p-5", highlight && "border-accent/40 bg-gradient-to-br from-accent-soft to-transparent")}>
      <p className="text-[13px] font-medium text-ink-2">{label}</p>
      <p className="tabular mt-2 text-[28px] leading-none font-semibold tracking-tight sm:text-[30px]">{euros(amount.eur)}</p>
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="tabular text-[13px] text-ink-2">{stars(amount.stars)}</span>
        {footer}
      </div>
    </Card>
  );
}

function MiniStat({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-center gap-3.5 px-5 py-4">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-surface-2 text-ink-2 [&_svg]:size-[18px]">{icon}</span>
      <div className="min-w-0">
        <p className="text-[13px] text-ink-3">{label}</p>
        <p className="tabular text-lg leading-tight font-semibold">{value}</p>
        {hint && <p className="truncate text-xs text-ink-3">{hint}</p>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ graphique

function ChartTip({ active, payload }: { active?: boolean; payload?: { payload: Dashboard["series"][number] }[] }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-xl border border-line-strong bg-surface-3 px-3 py-2.5 shadow-pop">
      <p className="text-xs text-ink-2">{longDate(point.date + "T12:00:00")}</p>
      <p className="tabular mt-1 text-[15px] font-semibold text-ink">{euros(point.eur)}</p>
      <p className="tabular text-xs text-ink-2">
        {stars(point.stars)} · {point.count} {point.count > 1 ? "ventes" : "vente"}
      </p>
    </div>
  );
}

function RevenueChart({ series }: { series: Dashboard["series"] }) {
  const max = Math.max(...series.map((p) => p.eur));
  // Une étiquette de date tous les n jours pour que l'axe reste lisible.
  const step = series.length <= 7 ? 1 : series.length <= 30 ? 5 : 15;
  const ticks = series.filter((_, i) => (series.length - 1 - i) % step === 0).map((p) => p.date);
  return (
    <div className="h-64 w-full sm:h-72" role="img" aria-label="Revenus estimés par jour, en euros">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={series} margin={{ top: 8, right: 4, bottom: 0, left: 0 }} barCategoryGap="22%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis
            dataKey="date"
            ticks={ticks}
            tickFormatter={chartDay}
            tickLine={false}
            axisLine={{ stroke: "var(--grid)" }}
            tick={{ fill: "var(--text-3)", fontSize: 12 }}
            tickMargin={8}
            interval={0}
          />
          <YAxis
            width={56}
            tickLine={false}
            axisLine={false}
            tick={{ fill: "var(--text-3)", fontSize: 12 }}
            tickFormatter={(v: number) => eurosRound(v)}
            allowDecimals={false}
            domain={[0, max > 0 ? "auto" : 10]}
            tickCount={5}
          />
          <ChartTooltip content={<ChartTip />} cursor={{ fill: "var(--surface-2)" }} isAnimationActive={false} />
          <Bar dataKey="eur" fill="var(--chart)" radius={[4, 4, 0, 0]} maxBarSize={24} minPointSize={0} animationDuration={500} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ------------------------------------------------------------------ ventes

const DELIVERY: Record<Sale["delivery_status"], { label: string; tone: "success" | "warning" | "danger" | "neutral"; icon: React.ReactNode }> = {
  delivered: { label: "Livrée", tone: "success", icon: <CheckCircle2 /> },
  pending: { label: "En attente", tone: "warning", icon: <Clock /> },
  delivering: { label: "En cours", tone: "warning", icon: <Clock /> },
  failed: { label: "Échec de livraison", tone: "danger", icon: <TriangleAlert /> },
};

function SaleStatus({ sale }: { sale: Sale }) {
  if (sale.refunded_at) {
    return (
      <Badge tone="neutral">
        <Undo2 />
        Remboursée
      </Badge>
    );
  }
  const d = DELIVERY[sale.delivery_status];
  const badge = (
    <Badge tone={d.tone}>
      {d.icon}
      {d.label}
    </Badge>
  );
  return sale.delivery_error ? <Tooltip label={sale.delivery_error}>{badge}</Tooltip> : badge;
}

function SalesSection({ rate }: { rate: number }) {
  const qc = useQueryClient();
  const [limit, setLimit] = React.useState(8);
  const [toRefund, setToRefund] = React.useState<Sale | null>(null);
  const sales = useQuery({
    queryKey: ["sales", limit],
    queryFn: () => api.get<{ sales: Sale[]; total: number }>(`/api/sales?limit=${limit}`),
    placeholderData: (previous) => previous,
  });
  const refund = useMutation({
    mutationFn: (sale: Sale) => api.post(`/api/sales/${sale.id}/refund`),
    onSuccess: (_data, sale) => {
      toast.success(`Vente remboursée : ${stars(sale.stars)} rendues à ${sale.client_name}`);
      setToRefund(null);
      qc.invalidateQueries({ queryKey: ["sales"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const redeliver = useMutation({
    mutationFn: (sale: Sale) => api.post(`/api/sales/${sale.id}/deliver`),
    onSuccess: () => {
      toast.success("Pack livré");
      qc.invalidateQueries({ queryKey: ["sales"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const rows = sales.data?.sales ?? [];
  const total = sales.data?.total ?? 0;

  const actions = (sale: Sale) => (
    <div className="flex items-center justify-end gap-1">
      {sale.delivery_status === "failed" && !sale.refunded_at && sale.pack_id && (
        <Tooltip label="Relancer la livraison (ce qui a déjà été envoyé ne l'est pas une seconde fois)">
          <Button variant="ghost" size="icon-sm" aria-label="Relancer la livraison" loading={redeliver.isPending && redeliver.variables?.id === sale.id} onClick={() => redeliver.mutate(sale)}>
            <RotateCcw />
          </Button>
        </Tooltip>
      )}
      {!sale.refunded_at && (
        <Button variant="ghost" size="sm" className="text-ink-2" onClick={() => setToRefund(sale)}>
          Rembourser
        </Button>
      )}
    </div>
  );

  return (
    <Card>
      <CardHeader
        title="Dernières ventes"
        description={total > 0 ? `${number(total)} ${total > 1 ? "ventes enregistrées" : "vente enregistrée"}` : undefined}
        action={
          total > 0 && (
            <Button asChild variant="secondary" size="sm">
              <a href="/api/sales/export.csv" download>
                <Download />
                Exporter en CSV
              </a>
            </Button>
          )
        }
      />
      {sales.isPending ? (
        <div className="space-y-3 p-6">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : sales.isError ? (
        <div className="p-6">
          <ErrorState message={errorMessage(sales.error)} onRetry={() => sales.refetch()} />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<ShoppingBag />}
          title="Aucune vente pour l'instant"
          description="Dès qu'un client paie un pack en Stars, la vente apparaît ici et le contenu lui est livré automatiquement."
          action={
            <Button asChild variant="secondary">
              <Link to="/packs">
                <Package />
                Voir mes packs
              </Link>
            </Button>
          }
        />
      ) : (
        <>
          {/* Ordinateur : tableau */}
          <div className="mt-3 hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs font-medium text-ink-3">
                  <th className="py-2.5 pr-3 pl-6 font-medium">Client</th>
                  <th className="px-3 py-2.5 font-medium">Pack</th>
                  <th className="px-3 py-2.5 font-medium">Date</th>
                  <th className="px-3 py-2.5 text-right font-medium">Montant</th>
                  <th className="px-3 py-2.5 font-medium">État</th>
                  <th className="py-2.5 pr-6 pl-3" />
                </tr>
              </thead>
              <tbody>
                {rows.map((sale) => (
                  <tr key={sale.id} className="border-b border-line/60 transition-colors last:border-0 hover:bg-surface-2/50">
                    <td className="py-3 pr-3 pl-6">
                      {sale.chat_id ? (
                        <Link to={`/conversations/${sale.chat_id}`} className="group flex items-center gap-3">
                          <Avatar id={sale.chat_id} name={sale.client_name} hasPhoto={sale.client_has_photo} size={32} />
                          <span className="font-medium group-hover:text-accent">{sale.client_name}</span>
                        </Link>
                      ) : (
                        <span className="font-medium">{sale.client_name}</span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-ink-2">{sale.pack_name}</td>
                    <td className="tabular px-3 py-3 whitespace-nowrap text-ink-2">{dateTime(sale.paid_at)}</td>
                    <td className="tabular px-3 py-3 text-right whitespace-nowrap">
                      <span className={cn("font-semibold", sale.refunded_at && "text-ink-3 line-through")}>{euros(sale.eur)}</span>
                      <span className="ml-2 text-xs text-ink-3">{stars(sale.stars)}</span>
                    </td>
                    <td className="px-3 py-3">
                      <SaleStatus sale={sale} />
                    </td>
                    <td className="py-3 pr-4 pl-3">{actions(sale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Mobile : cartes */}
          <ul className="mt-2 divide-y divide-line/60 md:hidden">
            {rows.map((sale) => (
              <li key={sale.id} className="px-5 py-3.5">
                <div className="flex items-center gap-3">
                  <Avatar id={sale.chat_id ?? sale.buyer_tg_id} name={sale.client_name} hasPhoto={sale.client_has_photo} size={36} />
                  <div className="min-w-0 flex-1">
                    {sale.chat_id ? (
                      <Link to={`/conversations/${sale.chat_id}`} className="block truncate font-medium">
                        {sale.client_name}
                      </Link>
                    ) : (
                      <p className="truncate font-medium">{sale.client_name}</p>
                    )}
                    <p className="truncate text-[13px] text-ink-3">
                      {sale.pack_name} · {dateTime(sale.paid_at)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className={cn("tabular font-semibold", sale.refunded_at && "text-ink-3 line-through")}>{euros(sale.eur)}</p>
                    <p className="tabular text-xs text-ink-3">{stars(sale.stars)}</p>
                  </div>
                </div>
                <div className="mt-2 flex items-center justify-between pl-12">
                  <SaleStatus sale={sale} />
                  {actions(sale)}
                </div>
              </li>
            ))}
          </ul>
          {total > rows.length && (
            <div className="border-t border-line p-3 text-center">
              <Button variant="ghost" size="sm" loading={sales.isFetching} onClick={() => setLimit((l) => l + 20)}>
                Afficher plus de ventes
              </Button>
            </div>
          )}
        </>
      )}
      <ConfirmDialog
        open={!!toRefund}
        onOpenChange={(open) => !open && setToRefund(null)}
        title="Rembourser cette vente ?"
        description={
          toRefund && (
            <>
              <strong className="text-ink">{stars(toRefund.stars)}</strong> (≈ {euros(toRefund.stars * rate)}) seront rendues à <strong className="text-ink">{toRefund.client_name}</strong> pour le
              pack « {toRefund.pack_name} ». Cette action est définitive, et le contenu déjà livré reste en sa possession.
            </>
          )
        }
        confirmLabel="Rembourser"
        loading={refund.isPending}
        onConfirm={() => toRefund && refund.mutate(toRefund)}
      />
    </Card>
  );
}

// ------------------------------------------------------------------ page

export function DashboardPage() {
  const [days, setDays] = React.useState(30);
  const { data: status } = useStatus();
  const dash = useQuery({
    queryKey: ["dashboard", days],
    queryFn: () => api.get<Dashboard>(`/api/dashboard?days=${days}`),
    placeholderData: (previous) => previous,
  });

  if (dash.isError) return <ErrorState message={errorMessage(dash.error)} onRetry={() => dash.refetch()} />;
  const d = dash.data;
  const maxPack = d ? Math.max(1, ...d.by_pack.map((p) => p.stars)) : 1;
  const periodTotal = d ? d.series.reduce((sum, p) => sum + p.eur, 0) : 0;

  return (
    <div className="space-y-5 lg:space-y-6">
      {status && !status.onboarding.done && <OnboardingChecklist status={status} />}

      {/* Chiffres clés */}
      <section aria-label="Chiffre d'affaires" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {!d ? (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[126px] rounded-2xl" />)
        ) : (
          <>
            <RevenueCard label="Aujourd'hui" amount={d.revenue.today} highlight footer={<Delta current={d.revenue.today.stars} previous={d.revenue.yesterday.stars} versus="vs hier" />} />
            <RevenueCard label="7 derniers jours" amount={d.revenue.d7} footer={<Delta current={d.revenue.d7.stars} previous={d.revenue.prev_d7.stars} versus="vs 7 j. avant" />} />
            <RevenueCard label="30 derniers jours" amount={d.revenue.d30} footer={<Delta current={d.revenue.d30.stars} previous={d.revenue.prev_d30.stars} versus="vs 30 j. avant" />} />
            <RevenueCard
              label="Depuis le début"
              amount={d.revenue.total}
              footer={
                <span className="text-xs text-ink-3">
                  {number(d.sales_count)} {d.sales_count > 1 ? "ventes" : "vente"}
                </span>
              }
            />
          </>
        )}
      </section>
      {d && (
        <p className="-mt-2 text-xs text-ink-3">
          Montants en euros estimés : 1 ⭐ ≈ {new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 4 }).format(d.rate)} €.{" "}
          <Link to="/parametres#ventes" className="text-ink-2 underline decoration-line-strong underline-offset-2 hover:text-ink">
            Modifier le taux
          </Link>
        </p>
      )}

      {/* Graphique + répartition */}
      <section className="grid gap-4 lg:gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title="Revenus par jour"
            description={d ? `${euros(periodTotal)} estimés sur la période` : undefined}
            action={
              <Segmented
                label="Période affichée"
                value={days}
                onChange={setDays}
                options={[
                  { value: 7, label: "7 jours" },
                  { value: 30, label: "30 jours" },
                  { value: 90, label: "90 jours" },
                ]}
              />
            }
          />
          <CardBody className="pt-4">
            {!d ? (
              <Skeleton className="h-64 sm:h-72" />
            ) : d.sales_count === 0 ? (
              <EmptyState
                className="h-64 sm:h-72"
                icon={<ShoppingBag />}
                title="Aucune vente pour l'instant"
                description="Le graphique se remplira dès votre première vente."
              />
            ) : (
              <RevenueChart series={d.series} />
            )}
          </CardBody>
        </Card>

        <div className="grid gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-1">
          <Card>
            <CardHeader title="Ventes par pack" />
            <CardBody className="pt-4">
              {!d ? (
                <Skeleton className="h-28" />
              ) : d.by_pack.length === 0 ? (
                <p className="py-4 text-[13px] text-ink-3">
                  Aucune vente pour l'instant.{" "}
                  <Link to="/packs" className="font-medium text-accent hover:underline">
                    Gérer mes packs
                  </Link>
                </p>
              ) : (
                <ul className="space-y-4">
                  {d.by_pack.slice(0, 5).map((pack) => (
                    <li key={pack.pack_id ?? "inconnu"}>
                      <div className="flex items-baseline justify-between gap-3 text-[13px]">
                        <span className="truncate font-medium">{pack.name}</span>
                        <span className="tabular shrink-0 text-ink-2">
                          <span className="font-semibold text-ink">{euros(pack.eur)}</span> · {pack.count} {pack.count > 1 ? "ventes" : "vente"}
                        </span>
                      </div>
                      <div className="mt-2 h-2 rounded-full bg-surface-2">
                        <div className="h-full rounded-full bg-accent transition-all duration-500" style={{ width: `${Math.max(2, (pack.stars / maxPack) * 100)}%` }} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Meilleurs clients" />
            <CardBody className="px-3 pt-3 sm:px-4">
              {!d ? (
                <Skeleton className="mx-2 h-28" />
              ) : d.top_customers.length === 0 ? (
                <p className="px-2 py-4 text-[13px] text-ink-3">Vos meilleurs acheteurs apparaîtront ici.</p>
              ) : (
                <ul>
                  {d.top_customers.map((customer) => (
                    <li key={customer.chat_id}>
                      <Link to={`/conversations/${customer.chat_id}`} className="flex items-center gap-3 rounded-xl px-2 py-2 transition-colors hover:bg-surface-2">
                        <Avatar id={customer.chat_id} name={customer.name} hasPhoto={customer.has_photo} size={34} />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{customer.name}</p>
                          <p className="text-xs text-ink-3">
                            {customer.count} {customer.count > 1 ? "achats" : "achat"}
                          </p>
                        </div>
                        <span className="tabular text-sm font-semibold">{euros(customer.eur)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>
      </section>

      {/* Activité */}
      <Card className="grid divide-y divide-line sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        {!d ? (
          <Skeleton className="m-4 h-12 sm:col-span-3" />
        ) : (
          <>
            <MiniStat icon={<MessagesSquare />} label="Conversations" value={number(d.conversations)} hint="personnes qui vous ont écrit" />
            <MiniStat icon={<Users />} label="Acheteurs" value={number(d.buyers)} hint="au moins un achat" />
            <MiniStat icon={<Percent />} label="Taux de conversion" value={percent(d.conversion)} hint="acheteurs ÷ conversations" />
          </>
        )}
      </Card>

      <SalesSection rate={d?.rate ?? 0} />
    </div>
  );
}
