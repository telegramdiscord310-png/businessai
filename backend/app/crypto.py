"""Chiffrement symétrique (Fernet) des secrets stockés en base."""
from cryptography.fernet import Fernet, InvalidToken

from .config import get_config


class CryptoError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_config().fernet_key
    if not key:
        raise CryptoError("FERNET_KEY est vide : renseignez-la dans le fichier .env.")
    try:
        return Fernet(key.encode())
    except Exception as exc:  # clé mal formée
        raise CryptoError("FERNET_KEY est invalide : générez-la avec `python -m app.cli generate-keys`.") from exc


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise CryptoError(
            "Impossible de déchiffrer un secret : la FERNET_KEY a changé depuis son enregistrement."
        ) from exc


def mask(value: str | None) -> str | None:
    """Aperçu masqué pour l'interface : seuls les 4 derniers caractères sont visibles."""
    if not value:
        return None
    return "••••••••" + value[-4:] if len(value) > 8 else "••••••••"
