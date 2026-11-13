import * as React from "react";
import { initials } from "@/lib/format";
import { cn } from "@/lib/utils";

// Teintes sobres dérivées de l'identifiant : chaque personne garde toujours la même.
const tints = ["#3987e5", "#199e70", "#c98500", "#d55181", "#9085e9", "#d95926", "#2aa5b8"];

export function Avatar({
  id,
  name,
  hasPhoto,
  version = 0,
  size = 44,
  className,
}: {
  id: string | number;
  name: string;
  hasPhoto?: boolean;
  version?: number;
  size?: number;
  className?: string;
}) {
  const [failed, setFailed] = React.useState(false);
  const tint = tints[Number(BigInt(String(id).replace(/\D/g, "") || "0") % BigInt(tints.length))];
  const style = { width: size, height: size, fontSize: Math.round(size * 0.36) };
  if (hasPhoto && !failed) {
    return (
      <img
        src={`/api/chats/${id}/avatar?v=${version}`}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        style={style}
        className={cn("shrink-0 rounded-full bg-surface-3 object-cover", className)}
      />
    );
  }
  return (
    <div
      aria-hidden
      style={{ ...style, background: `color-mix(in srgb, ${tint} 22%, var(--surface-2))`, color: tint }}
      className={cn("flex shrink-0 items-center justify-center rounded-full font-semibold select-none", className)}
    >
      {initials(name)}
    </div>
  );
}
