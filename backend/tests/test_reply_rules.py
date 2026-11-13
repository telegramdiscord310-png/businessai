"""Règles de réponse automatique : le userbot ne fait que répondre, et seulement quand il en a le droit."""
import asyncio
import random
from types import SimpleNamespace

from sqlalchemy import select

from app.models import Message
from app.services.chatlog import PeerInfo, resume_ai
from app.services.reply_engine import should_handle, typing_delay


async def all_messages(world, chat_id=111):
    async with world.sm() as s:
        return list((await s.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.id))).all())


# ---------------------------------------------------------------- qui a droit à une réponse


async def test_repond_a_un_message_prive_humain(world):
    await world.receive(text="Bonjour, tu vends quoi ?")
    assert world.transport.texts() == ["Bonjour ! Comment puis-je t'aider ?"]
    msgs = await all_messages(world)
    assert [(m.direction, m.sender) for m in msgs] == [("in", "client"), ("out", "ai")]
    assert world.transport.typing_calls, "l'indicateur « en train d'écrire » doit être affiché"


async def test_ignore_groupes_canaux_bots_et_messages_de_service(world):
    cases = [
        world.incoming(text="message de groupe", is_private=False),
        world.incoming(text="je suis un bot", peer=PeerInfo(id=222, first_name="Bot", is_bot=True)),
        world.incoming(text="", is_service=True),
        world.incoming(text="Code de connexion : 12345", peer=PeerInfo(id=777000, first_name="Telegram", is_service_account=True)),
        world.incoming(text="note à moi-même", peer=PeerInfo(id=1, is_self=True)),
        world.incoming(text="sortant", is_outgoing=True),
    ]
    for msg in cases:
        assert should_handle(msg) is False
        assert await world.engine.on_incoming(msg) is None
    await world.engine.wait_idle()
    assert world.transport.sent == []
    assert world.ai.calls == []
    async with world.sm() as s:
        assert (await s.scalars(select(Message))).all() == [], "rien ne doit être enregistré"


# ---------------------------------------------------------------- ne jamais écrire en premier


async def test_n_ecrit_jamais_en_premier(world):
    # Une conversation existe (créée par un message manuel du propriétaire) mais le client n'a rien écrit.
    await world.engine.on_owner_message(world.incoming(text="Salut, c'est moi", is_outgoing=True))
    await world.settings(ai_enabled=True)
    async with world.sm() as s:
        chat = await s.get(type(await world.chat()), 111)
        chat.ai_paused = False
        await s.commit()
    await world.engine._process(111)
    assert world.transport.sent == []
    assert world.ai.calls == []


async def test_ne_relance_jamais_apres_avoir_repondu(world):
    await world.receive(text="Salut")
    assert len(world.transport.sent) == 1
    # Le moteur est sollicité à nouveau sans nouveau message : il ne doit rien envoyer.
    for _ in range(3):
        await world.engine._process(111)
        world.engine._schedule(111)
        await world.engine.wait_idle()
    assert len(world.transport.sent) == 1
    assert len(world.ai.calls) == 1


async def test_envoi_refuse_si_deja_repondu_entre_temps(world):
    """Dernier garde-fou : même si une réponse est prête, elle n'est pas envoyée s'il n'y a plus rien à quoi répondre."""
    stored = await world.engine.on_incoming(world.incoming(text="Salut"))
    world.engine._cancel(111)
    await asyncio.sleep(0)
    await world.engine._send_reply(111, stored.id, "première", [])
    await world.engine._send_reply(111, stored.id, "seconde", [])
    assert world.transport.texts() == ["première"]


# ---------------------------------------------------------------- regroupement


async def test_plusieurs_messages_d_affilee_une_seule_reponse(world):
    await world.settings(batch_delay_seconds=0.05)
    for text in ("Salut", "t'es là ?", "j'ai une question sur tes packs"):
        await world.engine.on_incoming(world.incoming(text=text))
        await asyncio.sleep(0.01)
    await world.engine.wait_idle()
    assert len(world.transport.sent) == 1
    assert len(world.ai.calls) == 1
    content = world.ai.last_user_content()
    assert "Salut" in content and "t'es là ?" in content and "question sur tes packs" in content


async def test_message_recu_pendant_la_redaction_relance_le_regroupement(world):
    world.ai.default = "réponse"

    async def client_ecrit_encore():
        if len(world.ai.calls) == 1:
            await world.engine.on_incoming(world.incoming(text="ah et aussi…"))

    world.ai.before_complete = client_ecrit_encore
    await world.engine.on_incoming(world.incoming(text="Salut"))
    await asyncio.sleep(0.05)
    await world.engine.wait_idle()
    assert len(world.transport.sent) == 1, "une seule réponse pour l'ensemble"
    assert "ah et aussi…" in world.ai.last_user_content()


# ---------------------------------------------------------------- pause après message manuel


async def test_pause_apres_message_manuel_depuis_telegram(world):
    await world.receive(text="Salut")
    assert len(world.transport.sent) == 1
    await world.engine.on_owner_message(world.incoming(text="Je prends la main", is_outgoing=True))
    chat = await world.chat()
    assert chat.ai_paused is True and chat.paused_reason == "manual"

    await world.receive(text="Ok merci")
    await world.receive(text="Tu es là ?")
    assert len(world.transport.sent) == 1, "l'IA ne répond plus tant qu'elle est en pause"
    assert (await all_messages(world))[1].sender == "ai"
    assert [m.sender for m in await all_messages(world)][2] == "owner"


async def test_pause_apres_message_manuel_depuis_le_site(world):
    await world.receive(text="Salut")
    await world.engine.send_owner_message(111, "Bonjour, c'est moi en direct")
    assert (await world.chat()).ai_paused is True
    await world.receive(text="Super")
    assert world.transport.texts() == ["Bonjour ! Comment puis-je t'aider ?", "Bonjour, c'est moi en direct"]


async def test_reactivation_ne_declenche_aucun_message(world):
    await world.receive(text="Salut")
    await world.engine.on_owner_message(world.incoming(text="Je gère", is_outgoing=True))
    await world.receive(text="D'accord")
    async with world.sm() as s:
        await resume_ai(s, 111)  # ce que fait le bouton « Réactiver l'IA » du site
        await s.commit()
    assert (await world.chat()).ai_paused is False
    world.engine._schedule(111)
    await world.engine.wait_idle()
    assert len(world.transport.sent) == 1, "réactiver l'IA ne doit pas provoquer de relance"
    await world.receive(text="Tu as des nouveautés ?")
    assert len(world.transport.sent) == 2, "elle répond de nouveau au prochain message reçu"


async def test_les_messages_de_l_application_ne_sont_pas_pris_pour_des_messages_manuels(world):
    await world.receive(text="Salut")
    tg_id = world.transport.sent[0]["tg_id"]
    # Telegram renvoie au userbot l'écho de son propre envoi.
    echo = world.incoming(text="Bonjour ! Comment puis-je t'aider ?", is_outgoing=True, tg_message_id=tg_id)
    assert await world.engine.on_owner_message(echo) is None
    assert (await world.chat()).ai_paused is False


async def test_le_proprietaire_ecrit_pendant_que_l_ia_redige(world):
    async def proprietaire_repond():
        await world.engine.on_owner_message(world.incoming(text="Je réponds moi-même", is_outgoing=True))

    world.ai.before_complete = proprietaire_repond
    await world.receive(text="Salut")
    assert world.transport.sent == [], "la réponse de l'IA est abandonnée"
    assert (await world.chat()).ai_paused is True


# ---------------------------------------------------------------- interrupteurs


async def test_interrupteur_global(world):
    await world.settings(ai_enabled=False)
    await world.receive(text="Salut")
    assert world.transport.sent == [] and world.ai.calls == []
    assert len(await all_messages(world)) == 1, "le message est quand même enregistré"


async def test_interrupteur_par_conversation(world):
    await world.receive(111, "Salut")
    async with world.sm() as s:
        chat = await s.get(type(await world.chat()), 111)
        chat.ai_enabled = False
        await s.commit()
    await world.receive(111, "Encore moi")
    await world.receive(333, "Bonjour", peer=PeerInfo(id=333, first_name="Tom"))
    assert [s["chat_id"] for s in world.transport.sent] == [111, 333]


async def test_ia_non_configuree_aucun_envoi(world):
    await world.settings(ai_api_key_enc=None)
    await world.receive(text="Salut")
    assert world.transport.sent == []


# ---------------------------------------------------------------- limites de débit


async def test_limite_de_debit_par_conversation(world):
    await world.settings(rate_chat_per_hour=2, rate_global_per_hour=100)
    for i in range(4):
        await world.receive(111, f"message {i}")
    assert len(world.transport.texts(111)) == 2
    # Les autres conversations ne sont pas touchées.
    await world.receive(333, "Bonjour", peer=PeerInfo(id=333, first_name="Tom"))
    assert len(world.transport.texts(333)) == 1


async def test_limite_de_debit_globale(world):
    await world.settings(rate_chat_per_hour=100, rate_global_per_hour=3)
    for i in range(5):
        await world.receive(1000 + i, "Salut", peer=PeerInfo(id=1000 + i, first_name=f"Client {i}"))
    assert len(world.transport.sent) == 3


# ---------------------------------------------------------------- mode brouillon


async def test_mode_brouillon_rien_n_est_envoye_sans_validation(world):
    await world.settings(draft_mode=True)
    await world.receive(text="Salut")
    assert world.transport.sent == []
    drafts = [m for m in await all_messages(world) if m.status == "draft"]
    assert len(drafts) == 1 and drafts[0].sender == "ai"

    await world.engine.approve_draft(drafts[0].id, "Bonjour (corrigé par moi)")
    assert world.transport.texts() == ["Bonjour (corrigé par moi)"]
    sent = [m for m in await all_messages(world) if m.sender == "ai"]
    assert sent[0].status == "sent" and sent[0].tg_message_id is not None
    assert (await world.chat()).ai_paused is False


async def test_brouillon_remplace_par_le_suivant_et_supprimable(world):
    await world.settings(draft_mode=True)
    await world.receive(text="Salut")
    await world.receive(text="Tu es là ?")
    msgs = await all_messages(world)
    assert [m.status for m in msgs if m.sender == "ai"] == ["discarded", "draft"]
    draft = [m for m in msgs if m.status == "draft"][0]
    await world.engine.discard_draft(draft.id)
    assert world.transport.sent == []
    assert [m.status for m in await all_messages(world) if m.sender == "ai"] == ["discarded", "discarded"]


# ---------------------------------------------------------------- délai humain et médias


def test_delai_d_ecriture_proportionnel_et_borne():
    settings = SimpleNamespace(typing_min_seconds=2, typing_max_seconds=10, typing_chars_per_second=20)
    rng = random.Random(3)
    assert typing_delay(1, settings, rng) == 2  # borne basse
    assert typing_delay(5000, settings, rng) == 10  # borne haute
    values = {round(typing_delay(100, settings, rng), 3) for _ in range(20)}
    assert all(3.75 <= v <= 6.25 for v in values), "100 caractères à 20 c/s : 5 s ± 25 %"
    assert len(values) > 1, "une part d'aléatoire est attendue"


async def test_delai_applique_avant_l_envoi(world):
    await world.settings(typing_min_seconds=3, typing_max_seconds=3)
    await world.receive(text="Salut")
    assert world.transport.typing_calls == [(111, 3.0)]
    assert world.transport.read == [111]


async def test_message_non_textuel_enregistre_et_decrit_a_l_ia(world):
    await world.receive(text="", media_type="voice", media_desc="Message vocal (12 s)")
    await world.receive(text="regarde", media_type="photo", media_desc="Photo")
    msgs = await all_messages(world)
    assert msgs[0].media_type == "voice" and msgs[0].kind == "media"
    first_call_user = [m for m in world.ai.calls[0] if m["role"] == "user"][-1]["content"]
    assert "Message vocal (12 s)" in first_call_user
    assert "Photo" in world.ai.last_user_content() and "regarde" in world.ai.last_user_content()
    assert len(world.transport.sent) == 2


async def test_doublon_telegram_ignore(world):
    msg = world.incoming(text="Salut", tg_message_id=555)
    await world.engine.on_incoming(msg)
    assert await world.engine.on_incoming(msg) is None
    await world.engine.wait_idle()
    assert len(world.transport.sent) == 1


async def test_identifiant_telegram_deja_connu_n_interrompt_pas_l_envoi(world):
    """Si Telegram renvoie un identifiant déjà enregistré, l'envoi se termine quand même proprement."""
    await world.receive(text="Salut")
    import itertools

    world.transport._ids = itertools.count(world.transport.sent[0]["tg_id"])  # même identifiant qu'avant
    await world.receive(text="Encore moi")
    assert len(world.transport.sent) == 2
