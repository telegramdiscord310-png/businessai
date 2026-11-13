#!/bin/sh
# Crée le fichier .env avec des secrets aléatoires. Usage : ./scripts/init-env.sh app.mondomaine.fr
set -eu

DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then
    echo "Usage : ./scripts/init-env.sh app.mondomaine.fr" >&2
    exit 2
fi
if [ -f .env ]; then
    echo "Un fichier .env existe déjà : il n'a pas été modifié." >&2
    exit 1
fi

rand() { openssl rand -base64 "$1" | tr '+/' '-_' | tr -d '=\n'; }

umask 077
cat > .env <<ENV
# Fichier généré le $(date +%Y-%m-%d). Gardez-en une copie en lieu sûr : sans FERNET_KEY,
# la session Telegram et les clés enregistrées ne peuvent plus être déchiffrées.
DOMAIN=$DOMAIN
POSTGRES_PASSWORD=$(rand 24)
FERNET_KEY=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')
INTERNAL_TOKEN=$(rand 32)
SETUP_TOKEN=$(rand 12)
TZ=Europe/Paris
BACKUP_KEEP_DAYS=14
ENV

echo "Fichier .env créé."
echo "Code d'installation (à saisir à la première ouverture du site) : $(grep '^SETUP_TOKEN=' .env | cut -d= -f2)"
