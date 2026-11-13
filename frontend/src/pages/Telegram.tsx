import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, CircleAlert, ExternalLink, KeyRound, Loader2, LogOut, MessageSquareText, ShieldCheck, Smartphone, Unplug } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, ErrorState, Skeleton } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { api, errorMessage } from "@/lib/api";
import type { TelegramAccount } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEPS = [
  { title: "Identifiants", icon: KeyRound },
  { title: "Code reçu", icon: MessageSquareText },
  { title: "Mot de passe", icon: ShieldCheck },
  { title: "Connecté", icon: CheckCircle2 },
];

function stepIndex(status: TelegramAccount["status"]) {
  if (status === "connected" || status === "connecting") return 3;
  if (status === "password_needed") return 2;
  if (status === "code_sent") return 1;
  return 0;
}

function Stepper({ current, done }: { current: number; done: boolean }) {
  return (
    <ol className="flex items-center">
      {STEPS.map((step, index) => {
        const complete = done || index < current;
        const active = !done && index === current;
        return (
          <li key={step.title} className={cn("flex items-center", index < STEPS.length - 1 && "flex-1")}>
            <div className="flex flex-col items-center gap-2">
              <span
                className={cn(
                  "flex size-9 items-center justify-center rounded-full text-sm font-semibold transition-colors duration-300",
                  complete ? "bg-success-soft text-success" : active ? "bg-accent text-accent-fg" : "bg-surface-3 text-ink-3",
                )}
              >
                {complete ? <Check className="size-4" /> : index + 1}
              </span>
              <span className={cn("text-xs font-medium whitespace-nowrap", active ? "text-ink" : "text-ink-3", "max-sm:hidden")}>{step.title}</span>
            </div>
            {index < STEPS.length - 1 && <div className={cn("mx-2 h-0.5 flex-1 rounded-full transition-colors duration-300 sm:mx-3 sm:mb-6", index < current || done ? "bg-success/50" : "bg-surface-3")} />}
          </li>
        );
      })}
    </ol>
  );
}

function StatusBanner({ account }: { account: TelegramAccount }) {
  const map = {
    connected: { tone: "border-success/30 bg-success-soft", icon: <CheckCircle2 className="text-success" />, title: "Compte connecté", text: `${account.name ?? "Votre compte"}${account.username ? ` (@${account.username})` : ""} reçoit et envoie des messages via BusinessAI.` },
    connecting: { tone: "border-warning/30 bg-warning-soft", icon: <Loader2 className="animate-spin text-warning" />, title: "Connexion en cours…", text: account.error ?? "Le service se connecte à Telegram." },
    error: { tone: "border-danger/30 bg-danger-soft", icon: <CircleAlert className="text-danger" />, title: "Problème de connexion", text: account.error ?? "La connexion à Telegram a échoué. Une nouvelle tentative est faite automatiquement." },
    code_sent: { tone: "border-accent/30 bg-accent-soft", icon: <MessageSquareText className="text-accent" />, title: "Code envoyé", text: "Saisissez le code que Telegram vient de vous envoyer." },
    password_needed: { tone: "border-accent/30 bg-accent-soft", icon: <ShieldCheck className="text-accent" />, title: "Dernière étape", text: "Votre compte est protégé par la validation en deux étapes : saisissez votre mot de passe Telegram." },
    disconnected: { tone: "border-line bg-surface", icon: <Unplug className="text-ink-3" />, title: "Aucun compte connecté", text: account.error ?? "Suivez les étapes ci-dessous pour relier votre compte Telegram personnel." },
  }[account.status];
  return (
    <div className={cn("flex items-start gap-3.5 rounded-2xl border px-5 py-4", map.tone)} role="status">
      <span className="mt-0.5 [&_svg]:size-5">{map.icon}</span>
      <div className="min-w-0">
        <p className="text-[15px] font-semibold">{map.title}</p>
        <p className="mt-0.5 text-[13px] leading-snug text-ink-2">{map.text}</p>
      </div>
    </div>
  );
}

function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-[13px] leading-snug text-ink">
      {errorMessage(error)}
    </div>
  );
}

export function TelegramPage() {
  const qc = useQueryClient();
  const account = useQuery({ queryKey: ["telegram"], queryFn: () => api.get<TelegramAccount>("/api/telegram"), refetchInterval: 15_000 });
  const [creds, setCreds] = React.useState({ api_id: "", api_hash: "", phone: "" });
  const [code, setCode] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirmLogout, setConfirmLogout] = React.useState(false);
  const prefilled = React.useRef(false);

  React.useEffect(() => {
    if (account.data && !prefilled.current) {
      prefilled.current = true;
      setCreds((c) => ({ ...c, api_id: account.data.api_id ? String(account.data.api_id) : "" }));
    }
  }, [account.data]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["telegram"] });
    qc.invalidateQueries({ queryKey: ["status"] });
  };
  const sendCode = useMutation({
    mutationFn: () => api.post<{ delivery: string }>("/api/telegram/send-code", { api_id: Number(creds.api_id), api_hash: creds.api_hash.trim(), phone: creds.phone }),
    onSuccess: (data) => {
      toast.success(data.delivery === "app" ? "Code envoyé dans votre application Telegram" : "Code envoyé par SMS");
      setCode("");
      refresh();
    },
  });
  const signIn = useMutation({
    mutationFn: () => api.post<{ status: string }>("/api/telegram/sign-in", { code }),
    onSuccess: (data) => {
      if (data.status === "connected") toast.success("Compte Telegram connecté");
      refresh();
    },
    onError: refresh,
  });
  const checkPassword = useMutation({
    mutationFn: () => api.post("/api/telegram/password", { password }),
    onSuccess: () => {
      toast.success("Compte Telegram connecté");
      setPassword("");
      refresh();
    },
  });
  const logout = useMutation({
    mutationFn: () => api.post("/api/telegram/logout"),
    onSuccess: () => {
      toast.success("Compte Telegram déconnecté et session révoquée");
      setConfirmLogout(false);
      sendCode.reset();
      signIn.reset();
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (account.isError) return <ErrorState message={errorMessage(account.error)} onRetry={() => account.refetch()} />;
  if (!account.data) return <Skeleton className="mx-auto h-[480px] max-w-2xl rounded-2xl" />;
  const a = account.data;
  const step = stepIndex(a.status);
  const linked = a.status === "connected" || a.status === "connecting" || a.status === "error";

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <StatusBanner account={a} />
      <Card>
        <CardBody className="space-y-7 sm:p-7">
          <Stepper current={linked ? 3 : step} done={a.status === "connected"} />

          {linked ? (
            <div className="space-y-5">
              <dl className="divide-y divide-line rounded-2xl border border-line">
                {[
                  ["Compte", a.name ?? "—"],
                  ["Nom d'utilisateur", a.username ? `@${a.username}` : "—"],
                  ["Téléphone", a.phone ?? "—"],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
                    <dt className="text-ink-3">{label}</dt>
                    <dd className="tabular truncate font-medium">{value}</dd>
                  </div>
                ))}
              </dl>
              <p className="text-[13px] leading-relaxed text-ink-3">
                La session est conservée chiffrée sur votre serveur. En cas de coupure, la reconnexion est automatique. Vous retrouvez cette session dans Telegram → Paramètres → Appareils, sous le nom « BusinessAI ».
              </p>
              <Button variant="outline" className="border-danger/40 text-danger hover:bg-danger-soft" onClick={() => setConfirmLogout(true)}>
                <LogOut />
                Déconnecter ce compte
              </Button>
            </div>
          ) : step === 0 ? (
            <form
              className="space-y-5"
              onSubmit={(e) => {
                e.preventDefault();
                sendCode.mutate();
              }}
            >
              <div className="rounded-2xl border border-line bg-surface-2/50 p-4 text-[13px] leading-relaxed text-ink-2">
                <p className="mb-1.5 font-semibold text-ink">Où trouver api_id et api_hash ?</p>
                <ol className="list-decimal space-y-1 pl-4">
                  <li>
                    Ouvrez{" "}
                    <a href="https://my.telegram.org" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                      my.telegram.org <ExternalLink className="size-3" />
                    </a>{" "}
                    et connectez-vous avec votre numéro.
                  </li>
                  <li>Cliquez sur « API development tools » et créez une application (le nom est libre).</li>
                  <li>Copiez « App api_id » et « App api_hash » ci-dessous.</li>
                </ol>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="api_id" htmlFor="tg-api-id" hint="Un nombre de 6 à 9 chiffres.">
                  <Input id="tg-api-id" inputMode="numeric" pattern="[0-9]*" required className="tabular" placeholder="1234567" value={creds.api_id} onChange={(e) => setCreds({ ...creds, api_id: e.target.value.replace(/\D/g, "") })} />
                </Field>
                <Field label="api_hash" htmlFor="tg-api-hash" hint={a.has_api_hash ? "Déjà enregistré : laissez vide pour le réutiliser." : "32 caractères. Il sera chiffré."}>
                  <Input id="tg-api-hash" type="password" autoComplete="off" required={!a.has_api_hash} placeholder={a.has_api_hash ? "••••••••••••" : "0123abcd…"} value={creds.api_hash} onChange={(e) => setCreds({ ...creds, api_hash: e.target.value })} />
                </Field>
              </div>
              <Field label="Numéro de téléphone" htmlFor="tg-phone" hint="Au format international, avec l'indicatif du pays. Telegram vous enverra un code de connexion.">
                <div className="relative">
                  <Smartphone className="pointer-events-none absolute top-3 left-3.5 size-4 text-ink-3" />
                  <Input id="tg-phone" type="tel" autoComplete="tel" required className="tabular pl-10" placeholder="+33 6 12 34 56 78" value={creds.phone} onChange={(e) => setCreds({ ...creds, phone: e.target.value })} />
                </div>
              </Field>
              <FormError error={sendCode.error} />
              <Button type="submit" size="lg" loading={sendCode.isPending} className="w-full sm:w-auto">
                Recevoir le code
              </Button>
              {sendCode.isPending && <p className="text-[13px] text-ink-3">Connexion aux serveurs de Telegram… cela peut prendre jusqu'à 30 secondes.</p>}
            </form>
          ) : step === 1 ? (
            <form
              className="space-y-5"
              onSubmit={(e) => {
                e.preventDefault();
                signIn.mutate();
              }}
            >
              <Field label="Code de connexion" htmlFor="tg-code" hint={`Telegram l'a envoyé au ${a.phone ?? "numéro indiqué"}, dans la conversation « Telegram » de votre application (ou par SMS).`}>
                <Input id="tg-code" inputMode="numeric" autoComplete="one-time-code" autoFocus required maxLength={8} className="tabular h-14 text-center text-2xl font-semibold tracking-[0.4em]" placeholder="•••••" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
              </Field>
              <FormError error={signIn.error} />
              <div className="flex flex-wrap gap-2">
                <Button type="submit" size="lg" loading={signIn.isPending} disabled={code.length < 4}>
                  Valider le code
                </Button>
                <Button type="button" size="lg" variant="ghost" disabled={signIn.isPending} onClick={() => setConfirmLogout(true)}>
                  Recommencer
                </Button>
              </div>
            </form>
          ) : (
            <form
              className="space-y-5"
              onSubmit={(e) => {
                e.preventDefault();
                checkPassword.mutate();
              }}
            >
              <Field label="Mot de passe Telegram (validation en deux étapes)" htmlFor="tg-password" hint="C'est le mot de passe que vous avez défini dans Telegram → Paramètres → Confidentialité. Il n'est pas conservé.">
                <Input id="tg-password" type="password" autoComplete="off" autoFocus required value={password} onChange={(e) => setPassword(e.target.value)} />
              </Field>
              <FormError error={checkPassword.error} />
              <div className="flex flex-wrap gap-2">
                <Button type="submit" size="lg" loading={checkPassword.isPending}>
                  Terminer la connexion
                </Button>
                <Button type="button" size="lg" variant="ghost" disabled={checkPassword.isPending} onClick={() => setConfirmLogout(true)}>
                  Recommencer
                </Button>
              </div>
            </form>
          )}
        </CardBody>
      </Card>

      <ConfirmDialog
        open={confirmLogout}
        onOpenChange={setConfirmLogout}
        title={linked ? "Déconnecter le compte Telegram ?" : "Recommencer la connexion ?"}
        description={
          linked
            ? "La session sera révoquée auprès de Telegram et effacée du serveur. L'IA ne pourra plus répondre et les packs payés ne seront plus livrés tant que vous n'aurez pas reconnecté un compte."
            : "La demande en cours est annulée ; vous pourrez saisir à nouveau vos identifiants."
        }
        confirmLabel={linked ? "Déconnecter" : "Recommencer"}
        danger={linked}
        loading={logout.isPending}
        onConfirm={() => logout.mutate()}
      />
    </div>
  );
}
