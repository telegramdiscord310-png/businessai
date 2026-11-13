"""API du site : installation, connexion, CSRF, limitation des tentatives, packs, tableau de bord."""
from datetime import timedelta

import httpx
import pytest_asyncio
from sqlalchemy import select

from app import db as app_db
from app.events import EventHub
from app.main import create_app
from app.models import Chat, LoginAttempt, Sale, utcnow

PASSWORD = "un-mot-de-passe-solide"


class Site:
    def __init__(self, client: httpx.AsyncClient, app, world):
        self.client, self.app, self.world = client, app, world
        self.csrf = ""
        self.worker_calls: list[tuple] = []

    async def install(self):
        r = await self.client.post("/api/setup", json={"setup_token": "code-installation-test", "username": "admin", "password": PASSWORD})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]
        return r

    async def post(self, url, json=None, **kw):
        return await self.client.post(url, json=json, headers={"X-CSRF-Token": self.csrf}, **kw)

    async def put(self, url, json=None):
        return await self.client.put(url, json=json, headers={"X-CSRF-Token": self.csrf})

    async def delete(self, url):
        return await self.client.delete(url, headers={"X-CSRF-Token": self.csrf})


@pytest_asyncio.fixture
async def site(world, monkeypatch):
    monkeypatch.setattr(app_db, "_sessionmaker", world.sm)
    monkeypatch.setenv("DATA_DIR", world.data_dir)
    from app.config import get_config

    get_config.cache_clear()
    app = create_app(with_lifespan=False)
    app.state.bus, app.state.hub = world.bus, EventHub()
    app.state.ai_factory = lambda settings: world.ai
    transport = httpx.ASGITransport(app=app, client=("203.0.113.5", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        s = Site(client, app, world)

        async def fake_worker(method, path, json=None, timeout=0):
            s.worker_calls.append((method, path, json))
            return {"ok": True}

        for module in ("chats", "sales", "settings", "telegram"):
            monkeypatch.setattr(f"app.api.{module}.call_worker", fake_worker)
        yield s
    get_config.cache_clear()


# ---------------------------------------------------------------- installation et connexion


async def test_installation_puis_page_desactivee(site):
    assert (await site.client.get("/api/setup/status")).json() == {"needs_setup": True}
    bad = await site.client.post("/api/setup", json={"setup_token": "faux", "username": "admin", "password": PASSWORD})
    assert bad.status_code == 403
    weak = await site.client.post("/api/setup", json={"setup_token": "code-installation-test", "username": "admin", "password": "court"})
    assert weak.status_code == 422
    r = await site.install()
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert (await site.client.get("/api/setup/status")).json() == {"needs_setup": False}
    again = await site.client.post("/api/setup", json={"setup_token": "code-installation-test", "username": "pirate", "password": PASSWORD})
    assert again.status_code == 403, "la page d'installation se désactive après la création du compte"


async def test_mot_de_passe_hache_en_argon2(site):
    await site.install()
    from app.models import AdminUser

    async with site.world.sm() as s:
        user = await s.scalar(select(AdminUser))
    assert user.password_hash.startswith("$argon2id$") and PASSWORD not in user.password_hash


async def test_routes_protegees_sans_session(site):
    for url in ("/api/status", "/api/chats", "/api/packs", "/api/dashboard", "/api/logs", "/api/settings", "/api/events", "/api/sales/export.csv"):
        assert (await site.client.get(url)).status_code == 401, url


async def test_connexion_deconnexion(site):
    await site.install()
    await site.post("/api/auth/logout")
    assert (await site.client.get("/api/status")).status_code == 401
    assert (await site.client.post("/api/auth/login", json={"username": "admin", "password": "mauvais"})).status_code == 401
    r = await site.client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert r.status_code == 200
    assert (await site.client.get("/api/auth/me")).json()["username"] == "admin"


async def test_csrf_obligatoire_pour_modifier(site):
    await site.install()
    assert (await site.client.post("/api/ai/toggle", json={"enabled": True})).status_code == 403
    r = await site.client.post("/api/ai/toggle", json={"enabled": True}, headers={"X-CSRF-Token": "faux"})
    assert r.status_code == 403
    assert (await site.post("/api/ai/toggle", {"enabled": True})).status_code == 200


async def test_origine_etrangere_refusee(site):
    await site.install()
    r = await site.client.post("/api/ai/toggle", json={"enabled": True}, headers={"X-CSRF-Token": site.csrf, "Origin": "https://site-pirate.example"})
    assert r.status_code == 403
    preflight = await site.client.options(
        "/api/status", headers={"Origin": "https://site-pirate.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in preflight.headers, "CORS strict"


async def test_limitation_des_tentatives_de_connexion(site):
    await site.install()
    await site.post("/api/auth/logout")
    for _ in range(5):
        assert (await site.client.post("/api/auth/login", json={"username": "admin", "password": "faux"})).status_code == 401
    blocked = await site.client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers
    # Après la fenêtre de 15 minutes, la connexion redevient possible.
    async with site.world.sm() as s:
        for attempt in (await s.scalars(select(LoginAttempt))).all():
            attempt.created_at = utcnow() - timedelta(minutes=16)
        await s.commit()
    assert (await site.client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})).status_code == 200


async def test_en_tetes_de_securite(site):
    r = await site.client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]


async def test_changement_de_mot_de_passe(site):
    await site.install()
    bad = await site.post("/api/auth/password", {"current_password": "faux", "new_password": "nouveau-mot-de-passe"})
    assert bad.status_code == 400
    ok = await site.post("/api/auth/password", {"current_password": PASSWORD, "new_password": "nouveau-mot-de-passe"})
    assert ok.status_code == 200
    await site.post("/api/auth/logout")
    assert (await site.client.post("/api/auth/login", json={"username": "admin", "password": "nouveau-mot-de-passe"})).status_code == 200


# ---------------------------------------------------------------- IA et réglages


async def test_cle_api_chiffree_et_masquee(site):
    await site.install()
    body = {"ai_base_url": "https://api.x.ai/v1", "ai_model": "grok-test", "ai_api_key": "xai-cle-tres-secrete-1234", "ai_system_prompt": "Sois sympa."}
    r = await site.put("/api/ai/config", body)
    assert r.status_code == 200
    data = r.json()
    assert "xai-cle-tres-secrete-1234" not in r.text and data["ai_api_key_set"] is True and data["ai_api_key_hint"].endswith("1234")
    from app.models import Setting

    async with site.world.sm() as s:
        stored = (await s.get(Setting, "ai_api_key_enc")).value
    assert "secrete" not in stored and stored.startswith("gAAAA"), "la clé est chiffrée en base"
    # Clé laissée vide : la clé enregistrée est conservée.
    r = await site.put("/api/ai/config", {**body, "ai_api_key": "", "ai_model": "grok-autre"})
    assert r.json()["ai_api_key_set"] is True and r.json()["ai_model"] == "grok-autre"


async def test_bouton_tester_n_envoie_rien_sur_telegram(site):
    await site.install()
    pack = await site.world.add_pack(name="Pack Test", price=99)
    site.world.ai.call_tool(pack.id)
    site.world.ai.say("Voilà le lien !")
    r = await site.post("/api/ai/test", {"messages": [{"role": "user", "content": "Je veux acheter"}]})
    assert r.status_code == 200, r.text
    assert r.json() == {"reply": "Voilà le lien !", "payment_links": [{"pack_id": pack.id, "name": "Pack Test", "price_stars": 99}]}
    assert site.world.transport.sent == [] and site.world.bot.invoice_calls == [] and site.worker_calls == []


async def test_reglages_valides_et_messages_en_francais(site):
    await site.install()
    current = (await site.client.get("/api/settings")).json()
    payload = {k: current[k] for k in ("draft_mode", "batch_delay_seconds", "typing_min_seconds", "typing_max_seconds",
                                       "typing_chars_per_second", "mark_as_read", "rate_global_per_hour", "rate_chat_per_hour",
                                       "stars_eur_rate", "delivery_intro")}
    r = await site.put("/api/settings", {**payload, "stars_eur_rate": 0.015, "draft_mode": True})
    assert r.status_code == 200 and r.json()["stars_eur_rate"] == 0.015 and r.json()["draft_mode"] is True
    r = await site.put("/api/settings", {**payload, "typing_min_seconds": 10, "typing_max_seconds": 2})
    assert r.status_code == 422 and "maximum" in r.json()["detail"]
    r = await site.put("/api/settings", {**payload, "rate_chat_per_hour": 0})
    assert r.status_code == 422 and "Limite par conversation" in r.json()["detail"]
    r = await site.put("/api/settings/bot", {"token": "pas-un-token-du-tout-mais-assez-long"})
    assert r.status_code == 422


async def test_token_du_bot_chiffre_et_masque(site):
    await site.install()
    token = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
    r = await site.put("/api/settings/bot", {"token": token})
    assert r.status_code == 200 and token not in r.text
    assert r.json()["bot"]["configured"] is True and r.json()["bot"]["token_hint"].endswith("Dsaw")
    assert ("POST", "/bot/reload", None) in site.worker_calls


# ---------------------------------------------------------------- packs


async def test_cycle_de_vie_d_un_pack(site):
    await site.install()
    r = await site.post("/api/packs", {"name": "Pack Photos", "description": "20 photos", "price_stars": 250, "active": True})
    assert r.status_code == 201
    pack = r.json()
    assert pack["active"] is False, "sans contenu à livrer, le pack n'est pas mis en vente"
    r = await site.put(f"/api/packs/{pack['id']}", {"name": "Pack Photos", "price_stars": 250, "active": True})
    assert r.status_code == 422 and "contenu" in r.json()["detail"]

    files = [("files", ("../../etc/photo 1.jpg", b"contenu-image", "image/jpeg"))]
    r = await site.client.post(f"/api/packs/{pack['id']}/files", files=files, headers={"X-CSRF-Token": site.csrf})
    assert r.status_code == 201 and r.json()["files"][0]["filename"] == "photo 1.jpg", "nom de fichier nettoyé"
    file_id = r.json()["files"][0]["id"]
    r = await site.put(f"/api/packs/{pack['id']}", {"name": "Pack Photos", "price_stars": 300, "active": True})
    assert r.status_code == 200 and r.json()["active"] is True and r.json()["price_stars"] == 300

    download = await site.client.get(f"/api/packs/{pack['id']}/files/{file_id}")
    assert download.content == b"contenu-image"
    r = await site.delete(f"/api/packs/{pack['id']}/files/{file_id}")
    assert r.json()["active"] is False, "plus rien à livrer : le pack sort de la vente"

    assert (await site.post("/api/packs", {"name": "", "price_stars": 10})).status_code == 422
    assert (await site.post("/api/packs", {"name": "X", "price_stars": 0})).status_code == 422
    assert (await site.post("/api/packs", {"name": "X", "price_stars": 10, "content_link": "javascript:alert(1)"})).status_code == 422
    assert (await site.delete(f"/api/packs/{pack['id']}")).status_code == 200
    assert (await site.client.get("/api/packs")).json() == []


# ---------------------------------------------------------------- conversations, tableau de bord, export


async def seed_sales(site):
    world = site.world
    pack = await world.add_pack(name="Pack Photos", price=250)
    await world.receive(111, "Salut")
    await world.receive(222, "Bonjour", peer=__import__("app.services.chatlog", fromlist=["PeerInfo"]).PeerInfo(id=222, first_name="=Tom"))
    async with world.sm() as s:
        s.add_all([
            Sale(pack_id=pack.id, chat_id=111, buyer_tg_id=111, stars=250, telegram_payment_charge_id="c1", paid_at=utcnow(), delivery_status="delivered"),
            Sale(pack_id=pack.id, chat_id=111, buyer_tg_id=111, stars=250, telegram_payment_charge_id="c2", paid_at=utcnow() - timedelta(days=10), delivery_status="delivered"),
            Sale(pack_id=pack.id, chat_id=222, buyer_tg_id=222, stars=250, telegram_payment_charge_id="c3", paid_at=utcnow() - timedelta(days=40),
                 delivery_status="delivered", refunded_at=utcnow()),
        ])
        await s.commit()
    return pack


async def test_tableau_de_bord(site):
    await site.install()
    await seed_sales(site)
    current = (await site.client.get("/api/settings")).json()
    data = (await site.client.get("/api/dashboard?days=30")).json()
    rate = current["stars_eur_rate"]
    assert data["revenue"]["today"] == {"stars": 250, "eur": round(250 * rate, 2)}
    assert data["revenue"]["d7"]["stars"] == 250 and data["revenue"]["d30"]["stars"] == 500
    assert data["revenue"]["total"]["stars"] == 500, "la vente remboursée est exclue"
    assert len(data["series"]) == 30 and data["series"][-1]["stars"] == 250
    assert data["by_pack"][0]["name"] == "Pack Photos" and data["by_pack"][0]["count"] == 2
    assert data["top_customers"][0]["chat_id"] == 111
    assert data["conversations"] == 2 and data["buyers"] == 1 and data["conversion"] == 50.0
    assert len(data["recent_sales"]) == 3 and data["recent_sales"][0]["chat_id"] == "111"


async def test_export_csv(site):
    await site.install()
    await seed_sales(site)
    r = await site.client.get("/api/sales/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8-sig")
    lines = text.strip().split("\r\n")
    assert lines[0].startswith("Date;Client;Identifiant Telegram;Pack;Stars")
    assert len(lines) == 4
    assert ";Oui;" in lines[3] and "'=Tom" in lines[3], "formule de tableur neutralisée"


async def test_conversations_et_fiche_client(site):
    await site.install()
    await seed_sales(site)
    chats = (await site.client.get("/api/chats")).json()
    assert {c["id"] for c in chats} == {"111", "222"} and chats[0]["unread_count"] == 1
    assert [c["name"] for c in (await site.client.get("/api/chats?search=lé")).json()] == ["Léa"]
    detail = (await site.client.get("/api/chats/111")).json()
    assert detail["customer"]["total_stars"] == 500 and len(detail["customer"]["purchases"]) == 2
    msgs = (await site.client.get("/api/chats/111/messages")).json()["messages"]
    assert [m["sender"] for m in msgs] == ["client", "ai"]

    await site.post("/api/chats/111/read")
    assert (await site.client.get("/api/chats/111")).json()["unread_count"] == 0
    r = await site.client.patch("/api/chats/111", json={"ai_paused": True}, headers={"X-CSRF-Token": site.csrf})
    assert r.json()["ai_paused"] is True
    r = await site.post("/api/chats/111/messages", {"text": "Bonjour !"})
    assert r.status_code == 200 and site.worker_calls[-1] == ("POST", "/telegram/send", {"chat_id": 111, "text": "Bonjour !"})
    assert (await site.client.get("/api/chats/999")).status_code == 404


async def test_etat_general_et_parcours_guide(site):
    await site.install()
    await site.post("/api/ai/toggle", {"enabled": False})
    data = (await site.client.get("/api/status")).json()
    assert data["onboarding"] == {"telegram": False, "ai": True, "pack": False, "enabled": False, "done": False}
    assert data["telegram"]["status"] == "disconnected"
    await site.world.add_pack()
    await site.post("/api/ai/toggle", {"enabled": True})
    data = (await site.client.get("/api/status")).json()
    assert data["onboarding"]["pack"] is True and data["onboarding"]["enabled"] is True
    assert site.world.bus.of_type("status")
