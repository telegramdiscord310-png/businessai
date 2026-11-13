"""Commandes d'administration.

    python -m app.cli create-admin      crée le compte administrateur (si aucun n'existe)
    python -m app.cli reset-password    change le mot de passe (en cas d'oubli)
    python -m app.cli generate-keys     affiche des secrets prêts à coller dans .env
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import secrets
import sys

from cryptography.fernet import Fernet
from sqlalchemy import delete, select

from . import security
from .db import dispose_engine, get_sessionmaker
from .models import AdminUser, WebSession


def ask_password() -> str:
    while True:
        first = getpass.getpass("Mot de passe (10 caractères minimum) : ")
        if len(first) < 10:
            print("Trop court : 10 caractères minimum.")
            continue
        if first != getpass.getpass("Confirmez le mot de passe : "):
            print("Les deux saisies ne correspondent pas.")
            continue
        return first


async def create_admin(username: str | None, password: str | None) -> int:
    async with get_sessionmaker()() as session:
        if await session.scalar(select(AdminUser)):
            print("Un compte administrateur existe déjà. Utilisez « reset-password » pour changer le mot de passe.")
            return 1
        username = username or input("Identifiant : ").strip()
        if len(username) < 3:
            print("Identifiant trop court (3 caractères minimum).")
            return 1
        password = password or ask_password()
        if len(password) < 10:
            print("Mot de passe trop court (10 caractères minimum).")
            return 1
        session.add(AdminUser(username=username, password_hash=security.hash_password(password)))
        await session.commit()
    print(f"Compte « {username} » créé. Vous pouvez vous connecter au site.")
    return 0


async def reset_password(password: str | None) -> int:
    async with get_sessionmaker()() as session:
        user = await session.scalar(select(AdminUser))
        if user is None:
            print("Aucun compte administrateur : utilisez « create-admin ».")
            return 1
        password = password or ask_password()
        if len(password) < 10:
            print("Mot de passe trop court (10 caractères minimum).")
            return 1
        user.password_hash = security.hash_password(password)
        await session.execute(delete(WebSession))
        await session.commit()
    print(f"Mot de passe de « {user.username} » modifié. Toutes les sessions ont été fermées.")
    return 0


def generate_keys() -> int:
    print(f"FERNET_KEY={Fernet.generate_key().decode()}")
    print(f"INTERNAL_TOKEN={secrets.token_urlsafe(32)}")
    print(f"SETUP_TOKEN={secrets.token_urlsafe(12)}")
    print(f"POSTGRES_PASSWORD={secrets.token_urlsafe(24)}")
    return 0


async def _run(args) -> int:
    try:
        if args.command == "create-admin":
            return await create_admin(args.username, args.password)
        return await reset_password(args.password)
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Administration de BusinessAI")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin", help="Crée le compte administrateur")
    p.add_argument("--username")
    p.add_argument("--password", help="À éviter : préférez la saisie interactive")
    p = sub.add_parser("reset-password", help="Change le mot de passe administrateur")
    p.add_argument("--password", help="À éviter : préférez la saisie interactive")
    sub.add_parser("generate-keys", help="Génère les secrets du fichier .env")
    args = parser.parse_args()
    if args.command == "generate-keys":
        sys.exit(generate_keys())
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
