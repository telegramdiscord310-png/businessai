"""Données de démonstration, pour voir l'interface remplie en développement.

    python -m scripts.seed_demo          (refuse de s'exécuter si des conversations existent déjà)

À NE PAS lancer sur votre installation réelle : les conversations et ventes créées sont fictives.
"""
from __future__ import annotations

import asyncio
import os
import random
import struct
import sys
import zlib
from datetime import timedelta

from sqlalchemy import func, select

from app import crypto
from app.config import get_config
from app.db import dispose_engine, get_sessionmaker
from app.models import Chat, LogEntry, Message, Pack, PackFile, Sale, TelegramAccount, utcnow
from app.services.chatlog import PeerInfo, add_message, upsert_chat
from app.services.delivery import pack_files_dir
from app.settings_store import save_settings


def gradient_png(path: str, top: tuple[int, int, int], bottom: tuple[int, int, int], w: int = 640, h: int = 360) -> int:
    rows = bytearray()
    for y in range(h):
        t = y / (h - 1)
        rows.append(0)
        for x in range(w):
            k = min(1.0, max(0.0, t * 0.8 + (x / w) * 0.2))
            rows.extend(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


CLIENTS = [
    (5012345678, "Camille", "Durand", "camille_drd"),
    (5023456789, "Lucas", "Martin", "lucasm"),
    (5034567890, "Inès", "Bernard", None),
    (5045678901, "Théo", "Petit", "theo.ptt"),
    (5056789012, "Manon", "Leroy", "manonlry"),
    (5067890123, "Hugo", "Moreau", None),
    (5078901234, "Léa", "Fournier", "lea_frn"),
    (5089012345, "Nathan", "Girard", "nath_grd"),
    (5090123456, "Chloé", "Roux", None),
]


async def main() -> int:
    rnd = random.Random(7)
    cfg = get_config()
    async with get_sessionmaker()() as s:
        if await s.scalar(select(func.count()).select_from(Chat)) and "--force" not in sys.argv:
            print("Des conversations existent déjà : rien n'a été modifié.")
            return 1
        now = utcnow()
        await save_settings(s, {
            "ai_enabled": True, "ai_model": "grok-4", "ai_api_key_enc": crypto.encrypt("xai-cle-de-demonstration-0000"),
            "bot_token_enc": crypto.encrypt("123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"), "bot_username": "MaBoutiqueStarsBot",
        })
        account = await s.get(TelegramAccount, 1) or TelegramAccount(id=1)
        account.status, account.me_name, account.me_username, account.phone, account.api_id, account.last_error = "connected", "Alex Démo", "alex_demo", "+33612345678", 1234567, None
        s.add(account)

        packs = [
            Pack(name="Pack Photos Été", description="20 photos exclusives en haute définition.", price_stars=250, content_text="Merci ! Voici le lien vers la galerie privée.", content_link="https://exemple.fr/galerie/ete", active=True),
            Pack(name="Pack Vidéo Coulisses", description="3 vidéos des coulisses, 12 minutes au total.", price_stars=600, content_text="Bon visionnage !", active=True),
            Pack(name="Guide PDF Complet", description="Le guide de 40 pages, mis à jour chaque mois.", price_stars=120, content_link="https://exemple.fr/guide.pdf", active=True),
            Pack(name="Pack Archives 2024", description="Toutes les anciennes séries. Bientôt de retour.", price_stars=900, content_text="Archives", active=False),
        ]
        s.add_all(packs)
        await s.flush()
        covers = {0: ((255, 170, 90), (220, 70, 120)), 1: ((60, 110, 220), (30, 30, 80))}
        for index, (top, bottom) in covers.items():
            folder = pack_files_dir(cfg.data_dir, packs[index].id)
            os.makedirs(folder, exist_ok=True)
            stored = f"demo_{index}.png"
            size = gradient_png(os.path.join(folder, stored), top, bottom)
            s.add(PackFile(pack_id=packs[index].id, filename="apercu.png", stored_name=stored, size=size, mime="image/png"))
            s.add(PackFile(pack_id=packs[index].id, filename="contenu.zip", stored_name=stored, size=48_500_000, mime="application/zip"))

        tg_id = iter(range(10_000, 99_999))

        async def say(chat, minutes_ago: float, direction: str, sender: str, text: str = "", **kw):
            return await add_message(s, chat, direction=direction, sender=sender, text=text, tg_message_id=next(tg_id),
                                     created_at=now - timedelta(minutes=minutes_ago), answered=kw.pop("answered", True), **kw)

        chats = []
        for cid, first, last, username in CLIENTS:
            chats.append(await upsert_chat(s, PeerInfo(id=cid, first_name=first, last_name=last, username=username, access_hash=1)))
        camille, lucas, ines, theo, manon, hugo, lea, nathan, chloe = chats
        link = {"pack_id": packs[0].id, "pack_name": packs[0].name, "stars": 250}

        # Conversation complète : question, proposition, lien, paiement, livraison.
        await say(camille, 1500, "in", "client", "Coucou ! J'ai vu ton profil, tu proposes quoi exactement ?")
        await say(camille, 1498, "out", "ai", "Hello Camille ! Je propose des packs de photos et de vidéos exclusives. Tu cherches plutôt quoi ?")
        await say(camille, 1490, "in", "client", "Plutôt des photos")
        await say(camille, 1489, "in", "client", "c'est combien ?")
        await say(camille, 1487, "out", "ai", "Le Pack Photos Été, c'est 20 photos en haute définition pour 250 Stars. Je t'envoie le lien si ça te dit !")
        await say(camille, 62, "in", "client", "Ok je le prends 🙂")
        await say(camille, 61, "out", "ai", "Super, voilà le lien de paiement juste en dessous !")
        await say(camille, 61, "out", "ai", f"{packs[0].name} — 250 ⭐\nhttps://t.me/$demoFacture1", kind="payment_link", meta=link)
        await say(camille, 58, "out", "system", "Merci pour ton achat ! Voici ton pack :\n\nMerci ! Voici le lien vers la galerie privée.\n\nhttps://exemple.fr/galerie/ete", kind="delivery", meta=link)
        await say(camille, 57, "out", "system", "", kind="delivery", meta=link, media_type="document", media_desc="Fichier : contenu.zip")
        await say(camille, 12, "in", "client", "Bien reçu, merci beaucoup !!")
        await say(camille, 11, "in", "client", "", kind="media", media_type="voice", media_desc="Message vocal (14 s)", answered=False)
        camille.unread_count = 2

        # Brouillon en attente de validation.
        await say(lucas, 240, "in", "client", "Salut, t'es dispo ?")
        await say(lucas, 238, "out", "ai", "Salut Lucas ! Oui, dis-moi tout.")
        await say(lucas, 26, "in", "client", "Tu fais des réductions si je prends deux packs ?", answered=False)
        await add_message(s, lucas, direction="out", sender="ai", status="draft", created_at=now - timedelta(minutes=25),
                          text="Je n'ai pas de réduction en ce moment, mais le Pack Vidéo Coulisses est celui qui a le plus de contenu pour son prix. Tu veux que je t'envoie le lien ?",
                          meta={"pack_ids": [], "pack_names": [], "answer_upto": None})
        lucas.unread_count = 1

        # Conversation reprise à la main : IA en pause.
        await say(ines, 3000, "in", "client", "Bonjour, j'ai payé mais je ne retrouve pas le fichier")
        await say(ines, 2998, "out", "ai", "Bonjour Inès ! Je transmets tout de suite, le propriétaire va vérifier.")
        await say(ines, 2900, "out", "owner", "Bonjour Inès, c'est moi en direct. Je viens de vous renvoyer le lien, dites-moi si c'est bon.")
        await say(ines, 2890, "in", "client", "Parfait, c'est reçu. Merci pour la réactivité !")
        await say(ines, 2885, "out", "owner", "Avec plaisir, bonne journée !")
        ines.ai_paused, ines.paused_reason = True, "manual"

        await say(theo, 95, "in", "client", "", kind="media", media_type="photo", media_desc="Photo")
        await say(theo, 95, "in", "client", "C'est ce pack-là dont tu parlais ?")
        await say(theo, 93, "out", "ai", "Je ne peux pas voir les images, mais dis-moi le nom du pack et je te réponds !")
        await say(manon, 60 * 26, "in", "client", "T'es un vrai humain ou un robot ?")
        await say(manon, 60 * 26 - 1, "out", "ai", "Je suis un assistant automatique 🙂 Je peux répondre à tes questions et t'envoyer les liens des packs.")
        await say(hugo, 60 * 50, "in", "client", "Le guide PDF, il est à jour ?")
        await say(hugo, 60 * 50 - 2, "out", "ai", "Oui, il est mis à jour chaque mois. Il est à 120 Stars, je t'envoie le lien ?")
        await say(lea, 60 * 75, "in", "client", "Merci pour le pack vidéo, top qualité")
        await say(lea, 60 * 75 - 1, "out", "ai", "Merci Léa, ça fait plaisir ! N'hésite pas si tu veux autre chose.")
        await say(nathan, 60 * 24 * 6, "in", "client", "Hello")
        await say(nathan, 60 * 24 * 6 - 1, "out", "ai", "Hello Nathan ! Comment je peux t'aider ?")
        await say(chloe, 60 * 24 * 12, "in", "client", "Vous livrez comment après paiement ?")
        await say(chloe, 60 * 24 * 12 - 1, "out", "ai", "Tout arrive automatiquement ici, dans notre conversation, juste après le paiement.")
        chloe.ai_enabled = False
        for chat in chats:
            if chat not in (camille, lucas):
                chat.unread_count = 0

        # Ventes sur 75 jours, plus denses récemment.
        buyers = [camille, lea, hugo, ines, manon, nathan, theo]
        weights = [5, 4, 3, 3, 2, 1, 1]
        n = 0
        for day in range(75):
            for _ in range(rnd.choices([0, 1, 2, 3, 4], weights=[5, 4, 3, 2, 1] if day > 20 else [2, 4, 4, 3, 2])[0]):
                pack = rnd.choices(packs[:3], weights=[5, 2, 4])[0]
                buyer = rnd.choices(buyers, weights=weights)[0]
                paid = now - timedelta(days=day, minutes=rnd.randint(0, 600) if day else rnd.randint(30, 300))
                n += 1
                s.add(Sale(pack_id=pack.id, chat_id=buyer.id, buyer_tg_id=buyer.id, stars=pack.price_stars, telegram_payment_charge_id=f"demo_{n}",
                           paid_at=paid, delivery_status="delivered", delivered_at=paid + timedelta(seconds=20), delivery_step=1,
                           refunded_at=paid + timedelta(hours=3) if n % 23 == 0 else None))
        s.add(Sale(pack_id=packs[0].id, chat_id=camille.id, buyer_tg_id=camille.id, stars=250, telegram_payment_charge_id="demo_camille",
                   paid_at=now - timedelta(minutes=58), delivery_status="delivered", delivered_at=now - timedelta(minutes=57), delivery_step=2))
        s.add(Sale(pack_id=packs[1].id, chat_id=theo.id, buyer_tg_id=theo.id, stars=600, telegram_payment_charge_id="demo_echec",
                   paid_at=now - timedelta(hours=5), delivery_status="failed", delivery_error="Fichier introuvable sur le serveur : contenu.zip"))

        s.add_all([
            LogEntry(level="INFO", source="telegram", logger="app.telegram", message="Compte Telegram connecté", created_at=now - timedelta(days=2)),
            LogEntry(level="WARNING", source="site", logger="app.auth", message="Tentative de connexion refusée depuis 203.0.113.45", created_at=now - timedelta(days=1, hours=7)),
            LogEntry(level="ERROR", source="telegram", logger="app.engine", message=f"Réponse IA impossible (conversation {hugo.id}) : Le fournisseur d'IA limite les requêtes ou vous n'avez plus de crédit (erreur 429).", created_at=now - timedelta(days=1, hours=2)),
            LogEntry(level="ERROR", source="telegram", logger="app.delivery", message="Livraison de la vente n°149 interrompue : Fichier introuvable sur le serveur : contenu.zip",
                     details="Traceback (most recent call last):\n  File \"/app/app/services/delivery.py\", line 71, in deliver\n    await self.outbox.send(...)\napp.worker.userbot.TgError: Fichier introuvable sur le serveur : contenu.zip", created_at=now - timedelta(hours=5)),
            LogEntry(level="WARNING", source="telegram", logger="app.engine", message=f"Limite de débit atteinte pour la conversation {nathan.id} (20 réponses sur une heure)", created_at=now - timedelta(hours=3)),
            LogEntry(level="INFO", source="telegram", logger="app.payments", message="Vente n°148 enregistrée : 250 Stars", created_at=now - timedelta(minutes=58)),
            LogEntry(level="INFO", source="telegram", logger="app.engine", message=f"Réponse IA envoyée (conversation {camille.id})", created_at=now - timedelta(minutes=61)),
        ])
        await s.commit()
    await dispose_engine()
    print(f"Données de démonstration créées : {len(CLIENTS)} conversations, {n + 2} ventes.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
