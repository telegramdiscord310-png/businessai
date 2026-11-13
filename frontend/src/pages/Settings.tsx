import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, Moon, Sun } from "lucide-react";
import * as React from "react";
import { useLocation } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, ErrorState, Skeleton } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input, SwitchRow, Textarea } from "@/components/ui/form";
import { Segmented } from "@/components/ui/segmented";
import { api, errorMessage } from "@/lib/api";
import { euros } from "@/lib/format";
import { useTheme } from "@/lib/hooks";
import type { AppSettings } from "@/lib/types";
import { cn } from "@/lib/utils";

type Editable = Omit<AppSettings, "bot" | "timezone">;
type Draft = { [K in keyof Editable]: Editable[K] extends number ? string : Editable[K] };

const SECTIONS = [
  { id: "reponses", label: "Réponses" },
  { id: "limites", label: "Limites" },
  { id: "ventes", label: "Ventes" },
  { id: "bot", label: "Bot de paiement" },
  { id: "apparence", label: "Apparence" },
  { id: "compte", label: "Compte" },
];

const frNumber = (value: string) => Number(String(value).replace(",", "."));

function toDraft(s: AppSettings): Draft {
  return {
    draft_mode: s.draft_mode,
    mark_as_read: s.mark_as_read,
    delivery_intro: s.delivery_intro,
    batch_delay_seconds: String(s.batch_delay_seconds),
    typing_min_seconds: String(s.typing_min_seconds),
    typing_max_seconds: String(s.typing_max_seconds),
    typing_chars_per_second: String(s.typing_chars_per_second),
    rate_global_per_hour: String(s.rate_global_per_hour),
    rate_chat_per_hour: String(s.rate_chat_per_hour),
    stars_eur_rate: String(s.stars_eur_rate).replace(".", ","),
  };
}

function NumberField({ id, label, hint, value, onChange, suffix, step = "1" }: { id: string; label: string; hint: React.ReactNode; value: string; onChange: (v: string) => void; suffix: string; step?: string }) {
  return (
    <Field label={label} htmlFor={id} hint={hint}>
      <div className="relative">
        <Input id={id} inputMode="decimal" required className="tabular pr-24" value={value} step={step} onChange={(e) => onChange(e.target.value)} />
        <span className="pointer-events-none absolute top-2.5 right-3.5 text-[13px] text-ink-3">{suffix}</span>
      </div>
    </Field>
  );
}

function BotSection({ settings }: { settings: AppSettings }) {
  const qc = useQueryClient();
  const [token, setToken] = React.useState("");
  const [confirmRemove, setConfirmRemove] = React.useState(false);
  const save = useMutation({
    mutationFn: () => api.put<AppSettings>("/api/settings/bot", { token: token.trim() }),
    onSuccess: (data) => {
      toast.success(`Bot de paiement connecté${data.bot.username ? ` (@${data.bot.username})` : ""}`);
      setToken("");
      qc.setQueryData(["settings"], data);
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const remove = useMutation({
    mutationFn: () => api.delete<AppSettings>("/api/settings/bot"),
    onSuccess: (data) => {
      toast.success("Bot de paiement retiré");
      setConfirmRemove(false);
      qc.setQueryData(["settings"], data);
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <Card id="bot" className="scroll-mt-6">
      <CardHeader
        title="Bot de paiement"
        description="Un bot Telegram séparé encaisse les Stars et confirme les paiements. Vos clients ne lui parlent pas : ils reçoivent simplement son lien de paiement."
        action={
          settings.bot.configured ? (
            <Badge tone="success">
              <CheckCircle2 />
              {settings.bot.username ? `@${settings.bot.username}` : "Configuré"}
            </Badge>
          ) : (
            <Badge tone="warning">Non configuré</Badge>
          )
        }
      />
      <CardBody className="space-y-4">
        <div className="rounded-2xl border border-line bg-surface-2/50 p-4 text-[13px] leading-relaxed text-ink-2">
          <p className="mb-1.5 font-semibold text-ink">Créer le bot en 1 minute</p>
          <ol className="list-decimal space-y-1 pl-4">
            <li>
              Dans Telegram, ouvrez{" "}
              <a href="https://t.me/BotFather" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                @BotFather <ExternalLink className="size-3" />
              </a>{" "}
              et envoyez <code className="rounded bg-surface-3 px-1 py-0.5 text-xs text-ink">/newbot</code>.
            </li>
            <li>Choisissez un nom et un nom d'utilisateur (il doit finir par « bot »).</li>
            <li>Copiez le token que BotFather vous donne et collez-le ci-dessous.</li>
          </ol>
        </div>
        <form
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field label="Token du bot" htmlFor="bot-token" className="flex-1" hint={settings.bot.configured ? "Un token est enregistré (chiffré). Saisissez-en un nouveau pour le remplacer." : "Il est chiffré avant d'être enregistré, et vérifié auprès de Telegram."}>
            <Input id="bot-token" type="password" autoComplete="off" required placeholder={settings.bot.token_hint ?? "123456789:AA…"} value={token} onChange={(e) => setToken(e.target.value)} />
          </Field>
          <div className={cn("flex gap-2", "sm:mb-[26px]")}>
            <Button type="submit" loading={save.isPending} disabled={!token.trim()}>
              {settings.bot.configured ? "Remplacer" : "Enregistrer"}
            </Button>
            {settings.bot.configured && (
              <Button type="button" variant="danger-ghost" onClick={() => setConfirmRemove(true)}>
                Retirer
              </Button>
            )}
          </div>
        </form>
      </CardBody>
      <ConfirmDialog
        open={confirmRemove}
        onOpenChange={setConfirmRemove}
        title="Retirer le bot de paiement ?"
        description="Plus aucun lien de paiement ne pourra être créé, et les liens déjà envoyés ne fonctionneront plus tant qu'un bot n'est pas configuré."
        confirmLabel="Retirer le bot"
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </Card>
  );
}

function PasswordSection({ username }: { username: string }) {
  const [form, setForm] = React.useState({ current_password: "", new_password: "", confirm: "" });
  const [error, setError] = React.useState<string | null>(null);
  const change = useMutation({
    mutationFn: () => api.post("/api/auth/password", { current_password: form.current_password, new_password: form.new_password }),
    onSuccess: () => {
      toast.success("Mot de passe modifié. Vos autres sessions ont été fermées.");
      setForm({ current_password: "", new_password: "", confirm: "" });
    },
    onError: (e) => setError(errorMessage(e)),
  });
  return (
    <Card id="compte" className="scroll-mt-6">
      <CardHeader title="Compte" description={`Connecté en tant que ${username}.`} />
      <CardBody>
        <form
          className="grid gap-4 sm:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (form.new_password !== form.confirm) return setError("Les deux nouveaux mots de passe ne sont pas identiques.");
            if (form.new_password.length < 10) return setError("Le nouveau mot de passe doit contenir au moins 10 caractères.");
            setError(null);
            change.mutate();
          }}
        >
          <Field label="Mot de passe actuel" htmlFor="pw-current">
            <Input id="pw-current" type="password" autoComplete="current-password" required value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} />
          </Field>
          <Field label="Nouveau mot de passe" htmlFor="pw-new">
            <Input id="pw-new" type="password" autoComplete="new-password" required value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} />
          </Field>
          <Field label="Confirmation" htmlFor="pw-confirm">
            <Input id="pw-confirm" type="password" autoComplete="new-password" required value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
          </Field>
          {error && (
            <div role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-[13px] sm:col-span-3">
              {error}
            </div>
          )}
          <div className="sm:col-span-3">
            <Button type="submit" variant="secondary" loading={change.isPending}>
              Changer le mot de passe
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

export function SettingsPage({ username }: { username: string }) {
  const qc = useQueryClient();
  const location = useLocation();
  const [theme, setTheme] = useTheme();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<AppSettings>("/api/settings") });
  const [draft, setDraft] = React.useState<Draft | null>(null);
  const [saved, setSaved] = React.useState<Draft | null>(null);

  React.useEffect(() => {
    if (settings.data && !draft) {
      setDraft(toDraft(settings.data));
      setSaved(toDraft(settings.data));
    }
  }, [settings.data, draft]);
  // Lien direct vers une section (ex. /parametres#ventes).
  React.useEffect(() => {
    if (draft && location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [location.hash, !!draft]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (d: Draft) =>
      api.put<AppSettings>("/api/settings", {
        ...d,
        batch_delay_seconds: frNumber(d.batch_delay_seconds),
        typing_min_seconds: frNumber(d.typing_min_seconds),
        typing_max_seconds: frNumber(d.typing_max_seconds),
        typing_chars_per_second: frNumber(d.typing_chars_per_second),
        rate_global_per_hour: Math.round(frNumber(d.rate_global_per_hour)),
        rate_chat_per_hour: Math.round(frNumber(d.rate_chat_per_hour)),
        stars_eur_rate: frNumber(d.stars_eur_rate),
      }),
    onSuccess: (data) => {
      toast.success("Paramètres enregistrés");
      qc.setQueryData(["settings"], data);
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setDraft(toDraft(data));
      setSaved(toDraft(data));
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (settings.isError) return <ErrorState message={errorMessage(settings.error)} onRetry={() => settings.refetch()} />;
  if (!draft || !settings.data) {
    return (
      <div className="mx-auto max-w-3xl space-y-5">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-56 rounded-2xl" />
        ))}
      </div>
    );
  }
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => (d ? { ...d, [key]: value } : d));
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const rate = frNumber(draft.stars_eur_rate);
  const cps = frNumber(draft.typing_chars_per_second) || 1;

  return (
    <div className="mx-auto grid max-w-5xl gap-8 lg:grid-cols-[180px_minmax(0,1fr)]">
      <nav aria-label="Sections des paramètres" className="hidden lg:block">
        <ul className="sticky top-0 space-y-0.5">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`} className="block rounded-lg px-3 py-2 text-[13px] font-medium text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink">
                {s.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="min-w-0 space-y-5">
        <form
          id="settings-form"
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(draft);
          }}
        >
          <Card id="reponses" className="scroll-mt-6">
            <CardHeader title="Réponses automatiques" description="Le rythme auquel l'IA répond, pour que les échanges restent naturels." />
            <CardBody className="space-y-6">
              <SwitchRow
                title="Mode brouillon"
                hint="L'IA rédige ses réponses mais ne les envoie pas : vous les validez une par une dans Conversations. Idéal pour tester."
                checked={draft.draft_mode}
                onCheckedChange={(v) => set("draft_mode", v)}
              />
              <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
                <NumberField
                  id="batch"
                  label="Délai de regroupement"
                  suffix="secondes"
                  value={draft.batch_delay_seconds}
                  onChange={(v) => set("batch_delay_seconds", v)}
                  hint="Si quelqu'un envoie plusieurs messages d'affilée, l'IA attend ce délai après le dernier, puis répond une seule fois à l'ensemble."
                />
                <NumberField
                  id="cps"
                  label="Vitesse d'écriture"
                  suffix="caractères/s"
                  value={draft.typing_chars_per_second}
                  onChange={(v) => set("typing_chars_per_second", v)}
                  hint={`Pendant ce temps, « en train d'écrire… » s'affiche chez la personne. À cette vitesse, une réponse de 100 caractères part après environ ${Math.round(100 / cps)} s (± 25 % d'aléatoire).`}
                />
                <NumberField id="tmin" label="Délai de réponse minimum" suffix="secondes" value={draft.typing_min_seconds} onChange={(v) => set("typing_min_seconds", v)} hint="Même une réponse très courte attend au moins ce délai." />
                <NumberField id="tmax" label="Délai de réponse maximum" suffix="secondes" value={draft.typing_max_seconds} onChange={(v) => set("typing_max_seconds", v)} hint="Même une réponse très longue ne fait jamais attendre plus longtemps." />
              </div>
              <div className="border-t border-line pt-6">
                <SwitchRow title="Marquer les messages comme lus" hint="Juste avant de répondre, les messages reçus passent en « lu » chez la personne, comme si vous aviez ouvert la conversation." checked={draft.mark_as_read} onCheckedChange={(v) => set("mark_as_read", v)} />
              </div>
            </CardBody>
          </Card>

          <Card id="limites" className="scroll-mt-6">
            <CardHeader title="Limites de débit" description="Un garde-fou contre les abus et les blocages de Telegram : au-delà, l'IA cesse de répondre jusqu'à l'heure suivante." />
            <CardBody className="grid gap-5 sm:grid-cols-2">
              <NumberField id="rate-chat" label="Par conversation" suffix="réponses/heure" value={draft.rate_chat_per_hour} onChange={(v) => set("rate_chat_per_hour", v)} hint="Nombre maximum de réponses de l'IA à une même personne en une heure. Évite qu'un bavard ne consomme tout votre crédit." />
              <NumberField id="rate-global" label="Toutes conversations confondues" suffix="réponses/heure" value={draft.rate_global_per_hour} onChange={(v) => set("rate_global_per_hour", v)} hint="Nombre maximum de réponses de l'IA par heure, au total. Protège votre compte Telegram d'un envoi trop intense." />
            </CardBody>
          </Card>

          <Card id="ventes" className="scroll-mt-6">
            <CardHeader title="Ventes" />
            <CardBody className="space-y-5">
              <NumberField
                id="rate"
                label="Taux Stars → euros"
                suffix="€ par Star"
                value={draft.stars_eur_rate}
                onChange={(v) => set("stars_eur_rate", v)}
                hint={
                  <>
                    Sert uniquement à estimer vos revenus en euros dans le tableau de bord : Telegram vous verse des Stars, dont la valeur réelle dépend de votre mode de retrait.
                    {rate > 0 && rate <= 1 && <> Avec ce taux, 1 000 ⭐ ≈ {euros(1000 * rate)}.</>}
                  </>
                }
              />
              <Field label="Message de livraison" htmlFor="delivery-intro" optional hint="Envoyé juste avant le contenu du pack, une fois le paiement confirmé.">
                <Textarea id="delivery-intro" rows={2} maxLength={500} className="min-h-0" value={draft.delivery_intro} onChange={(e) => set("delivery_intro", e.target.value)} />
              </Field>
            </CardBody>
          </Card>
        </form>

        <BotSection settings={settings.data} />

        <Card id="apparence" className="scroll-mt-6">
          <CardHeader
            title="Apparence"
            description="Choix enregistré sur cet appareil."
            action={
              <Segmented
                label="Thème"
                value={theme}
                onChange={setTheme}
                options={[
                  { value: "dark", label: "Sombre" },
                  { value: "light", label: "Clair" },
                ]}
              />
            }
          />
          <CardBody className="flex items-center gap-3 pt-3 text-[13px] text-ink-3">
            {theme === "dark" ? <Moon className="size-4" /> : <Sun className="size-4" />}
            Thème {theme === "dark" ? "sombre" : "clair"} actif.
          </CardBody>
        </Card>

        <PasswordSection username={username} />
        <p className="pb-20 text-xs text-ink-3">Fuseau horaire des statistiques : {settings.data.timezone}.</p>
      </div>

      {/* Barre d'enregistrement : visible dès qu'un réglage a changé */}
      <div
        className={cn(
          "fixed inset-x-0 bottom-20 z-20 flex justify-center px-4 transition-all duration-300 lg:bottom-6 lg:left-60",
          dirty ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-4 opacity-0",
        )}
      >
        <div className="flex items-center gap-3 rounded-2xl border border-line-strong bg-surface-3 py-2 pr-2 pl-4 shadow-pop">
          <span className="text-[13px] font-medium">Modifications non enregistrées</span>
          <Button type="button" variant="ghost" size="sm" disabled={save.isPending} onClick={() => setDraft(saved)}>
            Annuler
          </Button>
          <Button type="submit" form="settings-form" size="sm" loading={save.isPending}>
            Enregistrer
          </Button>
        </div>
      </div>
    </div>
  );
}
