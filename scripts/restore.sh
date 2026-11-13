#!/bin/sh
# Restaure une sauvegarde de la base. À lancer depuis le dossier du projet :
#
#   ./scripts/restore.sh backups/businessai-2026-01-31.sql.gz
#
# ATTENTION : le contenu actuel de la base est remplacé par celui de la sauvegarde.
set -eu

FILE="${1:-}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
    echo "Usage : ./scripts/restore.sh backups/businessai-AAAA-MM-JJ.sql.gz" >&2
    exit 2
fi

printf "La base actuelle va être remplacée par %s. Continuer ? [oui/non] " "$FILE"
read -r answer
[ "$answer" = "oui" ] || { echo "Annulé."; exit 1; }

echo "Arrêt de l'application…"
docker compose stop backend worker
echo "Restauration…"
docker compose exec -T db sh -c 'psql -q -U businessai -d postgres -c "DROP DATABASE IF EXISTS businessai WITH (FORCE)" -c "CREATE DATABASE businessai OWNER businessai"'
gunzip -c "$FILE" | docker compose exec -T db psql -q -U businessai -d businessai
echo "Redémarrage…"
docker compose start backend worker
echo "Restauration terminée."
