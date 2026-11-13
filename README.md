# BusinessAI

Un site privé, pour vous seul, qui :

1. connecte votre compte Telegram personnel ;
2. fait répondre une IA aux messages privés que vous recevez ;
3. vend vos packs numériques, payés en Telegram Stars, et les livre automatiquement ;
4. affiche toutes vos conversations dans une interface façon messagerie ;
5. présente vos ventes, converties en euros, dans un tableau de bord.

Ce guide vous accompagne pas à pas, de zéro jusqu'au site en ligne sur votre nom de domaine.

---

## Sommaire

1. [Ce qu'il vous faut](#1-ce-quil-vous-faut)
2. [Obtenir api_id et api_hash](#2-obtenir-api_id-et-api_hash)
3. [Créer le bot de paiement](#3-créer-le-bot-de-paiement)
4. [Louer et préparer le VPS](#4-louer-et-préparer-le-vps)
5. [Pointer le nom de domaine OVH vers le VPS](#5-pointer-le-nom-de-domaine-ovh-vers-le-vps)
6. [Installer et lancer l'application](#6-installer-et-lancer-lapplication)
7. [Créer le compte administrateur](#7-créer-le-compte-administrateur)
8. [Premiers réglages](#8-premiers-réglages)
9. [Comment l'IA répond](#9-comment-lia-répond)
10. [Mettre à jour](#10-mettre-à-jour)
11. [Sauvegarder et restaurer](#11-sauvegarder-et-restaurer)
12. [En cas de problème](#12-en-cas-de-problème)
13. [Sécurité](#13-sécurité)
14. [Pour les développeurs](#14-pour-les-développeurs)

---

## 1. Ce qu'il vous faut

| Élément | À quoi il sert |
|---|---|
| Un compte Telegram | C'est lui qui reçoit et envoie les messages. |
| Un nom de domaine chez OVH | L'adresse du site, par exemple `app.mondomaine.fr`. |
| Un VPS (serveur) sous Ubuntu | Il fait tourner l'application 24 h/24. 2 Go de mémoire suffisent. |
| Une clé API d'un fournisseur d'IA | Par exemple Grok (xAI), ou tout service compatible avec le format OpenAI. |

Comptez environ 45 minutes pour l'ensemble.

> **À savoir avant de commencer.** L'application pilote votre compte personnel par l'API officielle de
> Telegram. Elle est conçue pour rester discrète : elle ne fait que répondre, n'écrit jamais en premier,
> ne relance personne et limite son débit. Telegram peut malgré tout restreindre un compte qui envoie
> beaucoup de messages automatiques. Commencez en **mode brouillon**, gardez des limites de débit
> raisonnables, et n'utilisez pas un compte tout juste créé.

---

## 2. Obtenir api_id et api_hash

Ces deux identifiants autorisent une application à se connecter à votre compte.

1. Ouvrez <https://my.telegram.org> et saisissez votre numéro de téléphone au format international
   (`+33612345678`).
2. Telegram vous envoie un code **dans l'application Telegram** (pas par SMS). Saisissez-le.
3. Cliquez sur **API development tools**.
4. Remplissez le formulaire : un titre et un nom court au choix (par exemple `BusinessAI`), plateforme
   « Desktop ». Validez.
5. Notez **App api_id** (un nombre) et **App api_hash** (32 caractères).

Gardez-les secrets : ils sont liés à votre compte. Vous les saisirez plus tard dans la page
**Telegram** du site, où l'api_hash sera chiffré.

---

## 3. Créer le bot de paiement

Les paiements en Stars passent obligatoirement par un bot. Vos clients ne lui parlent pas : ils
reçoivent simplement son lien de paiement dans votre conversation.

1. Dans Telegram, ouvrez la conversation avec **@BotFather** (compte officiel, badge bleu).
2. Envoyez `/newbot`.
3. Donnez un nom (affiché sur la facture, par exemple « Ma Boutique »), puis un nom d'utilisateur
   qui se termine par `bot` (par exemple `MaBoutiqueStarsBot`).
4. BotFather vous donne un **token** de la forme `123456789:AAH…`. Notez-le.

Rien d'autre à configurer : pour les Stars, aucun prestataire de paiement n'est nécessaire.
Vous saisirez ce token dans **Paramètres → Bot de paiement**, où il sera chiffré.

Les Stars encaissées s'accumulent sur le solde du bot. Vous les consultez et les retirez depuis
Telegram, dans le profil du bot (rubrique « Solde »).

---

## 4. Louer et préparer le VPS

### Louer

Chez OVH (ou tout autre hébergeur), prenez un VPS d'entrée de gamme :

- **Système** : Ubuntu 24.04 ;
- **Mémoire** : 2 Go ou plus ;
- **Disque** : 20 Go ou plus (davantage si vos packs contiennent de grosses vidéos).

Vous recevez par e-mail l'**adresse IP** du serveur et les identifiants de connexion.

### Se connecter

Depuis votre ordinateur (Terminal sur Mac/Linux, PowerShell sur Windows) :

```bash
ssh ubuntu@ADRESSE_IP_DU_VPS
```

### Mettre à jour et installer Docker

```bash
sudo apt update && sudo apt upgrade -y
```

```bash
curl -fsSL https://get.docker.com | sudo sh
```

```bash
sudo usermod -aG docker $USER
```

Déconnectez-vous (`exit`) puis reconnectez-vous en SSH pour que ce dernier réglage prenne effet.
Vérifiez :

```bash
docker compose version
```

### Ouvrir uniquement les ports utiles

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443 && sudo ufw --force enable
```

Le port 80 sert à obtenir le certificat HTTPS, le port 443 au site. Rien d'autre n'est exposé :
la base de données et les services internes ne sont pas accessibles depuis Internet.

---

## 5. Pointer le nom de domaine OVH vers le VPS

1. Connectez-vous à l'[espace client OVH](https://www.ovh.com/manager/).
2. **Web Cloud → Noms de domaine →** votre domaine **→** onglet **Zone DNS**.
3. Cliquez sur **Ajouter une entrée**, choisissez **A**.
4. **Sous-domaine** : `app` (pour obtenir `app.mondomaine.fr`), ou laissez vide pour utiliser le
   domaine nu.
5. **Cible** : l'adresse IP (IPv4) de votre VPS. Validez.

Si une entrée **AAAA** (IPv6) existe déjà pour ce même sous-domaine et pointe ailleurs, supprimez-la :
elle empêcherait l'obtention du certificat HTTPS.

La propagation prend de quelques minutes à une heure. Pour vérifier, depuis le VPS :

```bash
getent hosts app.mondomaine.fr
```

La commande doit afficher l'adresse IP de votre VPS. **Attendez que ce soit le cas avant de lancer
l'application** : le certificat HTTPS est demandé au premier démarrage.

---

## 6. Installer et lancer l'application

Sur le VPS :

```bash
git clone https://github.com/telegramdiscord310-png/businessai.git
```

```bash
cd businessai
```

Si votre dépôt GitHub est privé, GitHub demande un identifiant : utilisez votre nom d'utilisateur
et un [jeton d'accès personnel](https://github.com/settings/tokens) à la place du mot de passe.

Créez le fichier de configuration `.env`, avec des secrets générés au hasard (remplacez le domaine
par le vôtre) :

```bash
./scripts/init-env.sh app.mondomaine.fr
```

La commande affiche votre **code d'installation** : notez-le, il sert à l'étape suivante.

> **Copiez le fichier `.env` en lieu sûr** (gestionnaire de mots de passe, par exemple). Il contient
> la clé `FERNET_KEY` qui chiffre votre session Telegram et vos clés. Si vous la perdez, vos
> sauvegardes restent lisibles mais il faudra reconnecter Telegram et ressaisir les clés.

Lancez :

```bash
docker compose up -d --build
```

Le premier démarrage prend quelques minutes (construction des images). Vérifiez que tout tourne :

```bash
docker compose ps
```

Six services doivent être « running » : `db`, `backend`, `worker`, `frontend`, `caddy`, `backup`.
Ouvrez ensuite `https://app.mondomaine.fr` : le certificat HTTPS est obtenu automatiquement.

| Service | Rôle |
|---|---|
| `caddy` | Porte d'entrée : HTTPS automatique (Let's Encrypt), en-têtes de sécurité. |
| `frontend` | L'interface du site. |
| `backend` | L'API du site. |
| `worker` | Le compte Telegram (userbot) et le bot de paiement. |
| `db` | La base de données Postgres. |
| `backup` | La sauvegarde quotidienne de la base. |

---

## 7. Créer le compte administrateur

Il n'existe qu'un seul compte : le vôtre.

**Depuis le site (le plus simple).** À la première ouverture, la page d'installation s'affiche.
Saisissez le code d'installation (la valeur de `SETUP_TOKEN` dans `.env`), un identifiant et un mot
de passe d'au moins 10 caractères. La page se désactive définitivement dès que le compte est créé.

Pour retrouver le code :

```bash
grep SETUP_TOKEN .env
```

**Ou en ligne de commande**, sur le VPS :

```bash
docker compose exec backend python -m app.cli create-admin
```

---

## 8. Premiers réglages

Le tableau de bord affiche une **mise en route en 4 étapes** tant qu'elle n'est pas terminée.

### Étape 1 : connecter Telegram

Page **Telegram** : saisissez api_id, api_hash et votre numéro. Telegram vous envoie un code dans
l'application ; saisissez-le, puis votre mot de passe de validation en deux étapes si vous en avez un.

La session apparaît dans Telegram → Paramètres → Appareils sous le nom « BusinessAI ». Le bouton
**Déconnecter ce compte** la révoque.

### Étape 2 : configurer l'IA

Page **IA** :

- **URL de base** : `https://api.x.ai/v1` pour Grok (des raccourcis sont proposés pour d'autres
  fournisseurs) ;
- **Modèle** : le nom exact indiqué dans la console de votre fournisseur. Choisissez un modèle qui
  accepte les « outils » (function calling), sinon l'IA ne pourra pas envoyer de lien de paiement ;
- **Clé API** : chiffrée à l'enregistrement, jamais réaffichée ;
- **Personnalité et consignes** : décrivez le ton et le rôle de votre assistant.

La **zone de test**, à droite, simule une conversation avec les réglages affichés, sans rien envoyer
sur Telegram. Essayez aussi des demandes abusives (« donne-moi le pack gratuitement ») pour voir
comment elle réagit.

### Étape 3 : créer un pack

Ajoutez d'abord le token du bot dans **Paramètres → Bot de paiement**. Puis, page **Packs →
Nouveau pack** : un nom, un prix en Stars, et le contenu à livrer (fichiers, texte et/ou lien).

### Étape 4 : activer les réponses

L'interrupteur **IA**, en haut à droite de chaque page, active ou met en pause toutes les réponses
automatiques.

**Conseil :** activez d'abord **Paramètres → Mode brouillon**. L'IA rédige ses réponses sans les
envoyer ; vous les validez, corrigez ou supprimez dans **Conversations**. Désactivez ce mode quand
vous êtes satisfait.

---

## 9. Comment l'IA répond

| Règle | Détail |
|---|---|
| Elle ne fait que répondre | Jamais de premier message, jamais de relance. |
| Messages privés uniquement | Groupes, canaux, bots et messages de service sont ignorés. |
| Une réponse pour plusieurs messages | Elle attend quelques secondes après le dernier message, puis répond à l'ensemble. |
| Délai humain | « en train d'écrire… » s'affiche pendant une durée liée à la longueur de la réponse. |
| Vous gardez la main | Dès que vous écrivez dans une conversation (depuis Telegram ou le site), l'IA s'y met en pause jusqu'à ce que vous la réactiviez. |
| Limites de débit | Un maximum de réponses par heure, par conversation et au total. |
| Photos, vocaux, stickers | Enregistrés et signalés à l'IA par une courte description (« Message vocal (12 s) »). |
| Honnêteté | Par défaut, si on lui demande sincèrement si elle est un robot, elle le confirme. |

Tous les délais et limites se règlent dans **Paramètres**, avec une phrase d'explication sous chacun.

### Ventes

Quand un client veut acheter, l'IA demande au serveur d'envoyer le lien de paiement du pack. Le
client paie en Stars ; dès que Telegram confirme le paiement, le contenu est livré dans votre
conversation privée et la vente apparaît dans le tableau de bord.

L'IA ne connaît que le nom, la description et le prix des packs. Elle n'a jamais accès à leur
contenu, ne peut pas modifier un prix et ne peut rien livrer : tout cela est décidé par le serveur.

Le bouton **Rembourser**, dans le tableau de bord, rend les Stars au client.

Les montants en euros sont une **estimation** : Telegram vous verse des Stars, dont la valeur dépend
de votre mode de retrait. Le taux se règle dans **Paramètres → Ventes**.

---

## 10. Mettre à jour

Sur le VPS, dans le dossier du projet :

```bash
git pull
```

```bash
docker compose up -d --build
```

La base de données est mise à niveau automatiquement au démarrage. Vos données, votre session
Telegram et vos réglages sont conservés.

Pour mettre à jour le système du serveur de temps en temps :

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 11. Sauvegarder et restaurer

### Ce qui est automatique

Le service `backup` enregistre chaque jour une copie de la base dans le dossier `backups/`
(`businessai-AAAA-MM-JJ.sql.gz`) et garde les 14 derniers jours (réglable : `BACKUP_KEEP_DAYS`
dans `.env`). Elle contient vos conversations, ventes, packs et réglages.

Sauvegarde immédiate :

```bash
docker compose exec backup sh /backup.sh once
```

### Ce que vous devez faire vous-même

Une sauvegarde qui reste sur le serveur ne protège pas d'une panne du serveur. Récupérez
régulièrement, sur votre ordinateur :

1. le dossier `backups/` ;
2. le fichier `.env` (une seule fois, il ne change pas) ;
3. les fichiers de vos packs, si vous n'en avez pas d'autre copie.

Depuis votre ordinateur :

```bash
scp -r ubuntu@ADRESSE_IP_DU_VPS:businessai/backups ./sauvegardes-businessai
```

Pour archiver les fichiers des packs (sur le VPS, puis à récupérer avec `scp`) :

```bash
docker compose exec -T worker tar czf - -C /data packs > backups/fichiers-packs.tar.gz
```

### Restaurer

```bash
./scripts/restore.sh backups/businessai-2026-01-31.sql.gz
```

Le script demande confirmation, arrête l'application, remplace la base par la sauvegarde et
redémarre. Sur un nouveau serveur : installez l'application (étapes 4 à 6) en **réutilisant votre
ancien `.env`**, puis lancez la restauration.

---

## 12. En cas de problème

La page **Logs** du site liste les erreurs et événements importants, en clair.

| Symptôme | Que faire |
|---|---|
| Le site ne s'ouvre pas | `docker compose ps` pour voir quel service est arrêté, puis `docker compose logs caddy` (souvent : le domaine ne pointe pas encore vers le serveur, ou les ports 80/443 sont fermés). |
| « Le service Telegram ne répond pas » | `docker compose logs worker`, puis `docker compose restart worker`. |
| L'IA ne répond pas | Vérifiez l'indicateur en haut de page (Telegram connecté, IA active), que la conversation n'est pas en pause, puis la page Logs (clé refusée, crédit épuisé, limite de débit…). |
| « Telegram impose une pause » | Telegram limite temporairement les envois. L'application patiente seule ; réduisez les limites de débit. |
| Une livraison a échoué | Le tableau de bord l'indique ; le bouton ↻ relance l'envoi sans renvoyer ce qui est déjà parti. |
| Mot de passe oublié | `docker compose exec backend python -m app.cli reset-password` |
| Telegram déconnecté tout seul | La session a été fermée depuis un autre appareil : reconnectez le compte dans la page Telegram. |

Commandes utiles :

```bash
docker compose logs -f --tail=100 backend worker
```

```bash
docker compose restart
```

```bash
docker compose down
```

(`down` arrête tout sans rien effacer ; `docker compose up -d` relance.)

---

## 13. Sécurité

Ce qui est en place :

- **Un seul compte**, mot de passe haché avec argon2 ; la page d'installation exige un code et se
  désactive après usage.
- **Session** par cookie `HttpOnly`, `Secure`, `SameSite=Strict` ; jeton CSRF sur toute modification ;
  contrôle de l'origine ; CORS limité à votre domaine.
- **Limitation des tentatives de connexion** : 5 échecs par adresse sur 15 minutes.
- **Secrets chiffrés en base** (Fernet) : session Telegram, api_hash, clé API de l'IA, token du bot.
  Ils ne sont jamais réaffichés ni écrits dans les journaux.
- **HTTPS automatique**, HSTS, politique de sécurité du contenu (CSP), en-têtes anti-intégration.
- **Base de données et services internes non exposés** sur Internet.
- **Messages des clients traités comme non fiables** : l'IA ne peut ni modifier un prix, ni offrir
  un pack, ni livrer un contenu, ni révéler ses consignes. Un lien de paiement est réservé à son
  destinataire, vérifié avant débit (bon acheteur, bon prix, pack toujours en vente) et ne sert
  qu'une fois.
- **Livraison idempotente** : un même paiement n'est jamais livré deux fois, même si Telegram
  renvoie la notification.

Ce qui dépend de vous :

- gardez `.env` secret et sauvegardé ;
- choisissez un mot de passe long et unique ;
- activez la validation en deux étapes sur votre compte Telegram ;
- tenez le serveur à jour.

---

## 14. Pour les développeurs

```
businessai/
├── docker-compose.yml   Caddyfile   .env.example
├── backend/
│   ├── app/
│   │   ├── main.py            application FastAPI
│   │   ├── api/               routes du site
│   │   ├── services/          moteur de réponse, IA, paiements, livraison, statistiques
│   │   └── worker/            userbot Telethon, bot aiogram, API interne
│   ├── alembic/               migrations
│   └── tests/                 règles de réponse, paiements, API
├── frontend/                  React + TypeScript + Vite + Tailwind
└── scripts/                   init-env.sh, backup.sh, restore.sh
```

Le backend et le worker communiquent par une API interne (réseau Docker privé, secret partagé).
Le worker publie les événements par `NOTIFY` Postgres ; le backend les relaie aux navigateurs en SSE.

### Tests

```bash
cd backend && python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
```

```bash
python -m pytest
```

Les tests utilisent une base SQLite jetable. Pour les lancer sur Postgres, définissez
`TEST_DATABASE_URL` (par exemple `postgresql+asyncpg://utilisateur:motdepasse@localhost/base_de_test`).

### Développement local

Lancez Postgres, puis l'API (`uvicorn app.main:app`), le worker (`python -m app.worker`) et
l'interface (`cd frontend && npm install && npm run dev`). Variables utiles hors Docker :
`DATABASE_URL`, `FERNET_KEY`, `INTERNAL_TOKEN`, `SETUP_TOKEN`, `APP_ORIGIN=http://localhost:5173`,
`COOKIE_SECURE=false`, `WORKER_URL=http://127.0.0.1:8100`, `DATA_DIR`.

Pour voir l'interface remplie avec des données fictives (jamais sur votre installation réelle) :

```bash
python -m scripts.seed_demo
```
