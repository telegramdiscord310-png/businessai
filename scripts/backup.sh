#!/bin/sh
# Sauvegarde de la base Postgres (dump compressé), une fois par jour, avec purge des anciennes.
#
#   backup.sh once   une sauvegarde immédiate
#   backup.sh loop   une sauvegarde par jour (mode utilisé par le service « backup » de Docker Compose)
#
# Connexion : variables PGHOST, PGUSER, PGPASSWORD, PGDATABASE. Dossier : /backups.
set -eu

DIR="${BACKUP_DIR:-/backups}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$DIR"

dump() {
    name="businessai-$(date +%Y-%m-%d).sql.gz"
    tmp="$DIR/.$name.partiel"
    if pg_dump --no-owner --no-privileges | gzip -9 > "$tmp" && [ -s "$tmp" ] && gzip -t "$tmp"; then
        mv "$tmp" "$DIR/$name"
        echo "$(date '+%Y-%m-%d %H:%M') sauvegarde créée : $name ($(du -h "$DIR/$name" | cut -f1))"
        # Purge : on ne garde que les $KEEP derniers jours.
        find "$DIR" -name 'businessai-*.sql.gz' -mtime "+$KEEP" -delete
    else
        rm -f "$tmp"
        echo "$(date '+%Y-%m-%d %H:%M') ÉCHEC de la sauvegarde" >&2
        return 1
    fi
}

case "${1:-once}" in
    once)
        dump
        ;;
    loop)
        echo "Sauvegarde quotidienne active (conservation : $KEEP jours)."
        sleep 120  # laisse à l'application le temps de démarrer et d'appliquer ses migrations
        while true; do
            # Une sauvegarde par jour : dès le démarrage si celle du jour manque, puis chaque nuit.
            if [ ! -f "$DIR/businessai-$(date +%Y-%m-%d).sql.gz" ]; then
                dump || true
            fi
            sleep 3600
        done
        ;;
    *)
        echo "Usage : backup.sh [once|loop]" >&2
        exit 2
        ;;
esac
