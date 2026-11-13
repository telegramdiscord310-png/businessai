// Formats français : montants (1 234,56 €), nombres, dates et heures.
const eurFmt = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });
const eurCompactFmt = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const numFmt = new Intl.NumberFormat("fr-FR");
const pctFmt = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const timeFmt = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });
const shortDayFmt = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
const weekdayFmt = new Intl.DateTimeFormat("fr-FR", { weekday: "long" });
const dayMonthFmt = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });
const fullFmt = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

export const euros = (v: number) => eurFmt.format(v);
export const eurosRound = (v: number) => eurCompactFmt.format(v);
export const number = (v: number) => numFmt.format(v);
export const percent = (v: number) => `${pctFmt.format(v)} %`;
export const stars = (v: number) => `${numFmt.format(v)} ⭐`;

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
const daysAgo = (d: Date) => Math.round((startOfDay(new Date()) - startOfDay(d)) / 86_400_000);

export function time(iso: string) {
  return timeFmt.format(new Date(iso));
}

export function dateTime(iso: string) {
  return fullFmt.format(new Date(iso)).replace(" ", " à ").replace(",", "");
}

export function longDate(iso: string) {
  return dayFmt.format(new Date(iso));
}

/** Heure si aujourd'hui, « Hier », jour de la semaine, sinon date courte (liste des conversations). */
export function listStamp(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  const ago = daysAgo(d);
  if (ago <= 0) return timeFmt.format(d);
  if (ago === 1) return "Hier";
  if (ago < 7) return weekdayFmt.format(d).replace(/^./, (c) => c.toUpperCase());
  return shortDayFmt.format(d);
}

/** Séparateur de jour dans un fil de messages. */
export function daySeparator(iso: string) {
  const d = new Date(iso);
  const ago = daysAgo(d);
  if (ago <= 0) return "Aujourd'hui";
  if (ago === 1) return "Hier";
  return dayFmt.format(d);
}

export function sameDay(a: string, b: string) {
  return startOfDay(new Date(a)) === startOfDay(new Date(b));
}

export function chartDay(isoDate: string) {
  return dayMonthFmt.format(new Date(isoDate + "T12:00:00"));
}

export function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${numFmt.format(Math.round(bytes / 1024))} Ko`;
  return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 }).format(bytes / 1024 / 1024)} Mo`;
}

export function initials(name: string) {
  const parts = name.replace(/^@/, "").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}
