from __future__ import annotations

import mimetypes
import os
import re
import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..db import get_session
from ..models import Pack, PackFile, Sale, utcnow
from ..security import require_auth
from ..services.delivery import pack_files_dir
from .serializers import pack_out

router = APIRouter(prefix="/api/packs", tags=["packs"], dependencies=[Depends(require_auth)])
MAX_FILES_PER_PACK = 30
NEEDS_CONTENT = "Ajoutez un contenu à livrer (texte, lien ou fichier) avant de mettre ce pack en vente."


class PackIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    description: str = Field(default="", max_length=255)
    price_stars: int = Field(ge=1, le=100_000)
    content_text: str = Field(default="", max_length=3500)
    content_link: str = Field(default="", max_length=1024)
    active: bool = True

    @field_validator("name", "description", "content_text", "content_link")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v:
            raise ValueError("Le nom est obligatoire.")
        return v

    @field_validator("content_link")
    @classmethod
    def check_link(cls, v: str) -> str:
        if v and not re.match(r"^https?://\S+$", v):
            raise ValueError("Le lien doit commencer par https:// et ne pas contenir d'espace.")
        return v


def has_content(pack: Pack) -> bool:
    return bool((pack.content_text or "").strip() or (pack.content_link or "").strip() or pack.files)


async def get_pack(session: AsyncSession, pack_id: int) -> Pack:
    pack = await session.get(Pack, pack_id)
    if pack is None or pack.deleted_at is not None:
        raise HTTPException(404, "Ce pack n'existe pas ou a été supprimé.")
    return pack


async def sales_by_pack(session: AsyncSession) -> dict[int, tuple[int, int]]:
    rows = await session.execute(
        select(Sale.pack_id, func.count(), func.coalesce(func.sum(Sale.stars), 0)).where(Sale.refunded_at.is_(None)).group_by(Sale.pack_id)
    )
    return {pid: (count, int(stars)) for pid, count, stars in rows.all()}


@router.get("")
async def list_packs(session: AsyncSession = Depends(get_session)):
    packs = (await session.scalars(select(Pack).where(Pack.deleted_at.is_(None)).order_by(Pack.active.desc(), Pack.id.desc()))).all()
    stats = await sales_by_pack(session)
    return [pack_out(p, *stats.get(p.id, (0, 0))) for p in packs]


@router.post("", status_code=201)
async def create_pack(body: PackIn, session: AsyncSession = Depends(get_session)):
    pack = Pack(**body.model_dump())
    pack.content_text, pack.content_link = body.content_text or None, body.content_link or None
    if body.active and not (body.content_text or body.content_link):
        # Les fichiers s'ajoutent après la création : le pack reste hors vente en attendant.
        pack.active = False
    session.add(pack)
    await session.commit()
    await session.refresh(pack)
    return pack_out(pack)


@router.put("/{pack_id}")
async def update_pack(pack_id: int, body: PackIn, session: AsyncSession = Depends(get_session)):
    pack = await get_pack(session, pack_id)
    pack.name, pack.description, pack.price_stars = body.name, body.description, body.price_stars
    pack.content_text, pack.content_link = body.content_text or None, body.content_link or None
    if body.active and not has_content(pack):
        raise HTTPException(422, NEEDS_CONTENT)
    pack.active = body.active
    await session.commit()
    stats = await sales_by_pack(session)
    return pack_out(pack, *stats.get(pack.id, (0, 0)))


@router.delete("/{pack_id}")
async def delete_pack(pack_id: int, session: AsyncSession = Depends(get_session)):
    """Suppression : le pack disparaît du catalogue, ses ventes passées restent dans les statistiques."""
    pack = await get_pack(session, pack_id)
    pack.deleted_at, pack.active = utcnow(), False
    for f in list(pack.files):
        await session.delete(f)
    await session.commit()
    shutil.rmtree(pack_files_dir(get_config().data_dir, pack_id), ignore_errors=True)
    return {"ok": True}


def safe_filename(name: str | None) -> str:
    name = os.path.basename((name or "fichier").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name).strip(". ") or "fichier"
    return name[:200]


@router.post("/{pack_id}/files", status_code=201)
async def upload_files(pack_id: int, files: list[UploadFile], session: AsyncSession = Depends(get_session)):
    cfg = get_config()
    pack = await get_pack(session, pack_id)
    if len(pack.files) + len(files) > MAX_FILES_PER_PACK:
        raise HTTPException(422, f"Un pack contient au maximum {MAX_FILES_PER_PACK} fichiers.")
    folder = pack_files_dir(cfg.data_dir, pack_id)
    os.makedirs(folder, exist_ok=True)
    limit = cfg.max_upload_mb * 1024 * 1024
    written: list[str] = []
    try:
        for upload in files:
            filename = safe_filename(upload.filename)
            stored = uuid.uuid4().hex + os.path.splitext(filename)[1].lower()[:12]
            path = os.path.join(folder, stored)
            size = 0
            written.append(path)
            with open(path, "wb") as out:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"« {filename} » dépasse la taille maximale de {cfg.max_upload_mb} Mo.")
                    out.write(chunk)
            if size == 0:
                raise HTTPException(422, f"« {filename} » est vide.")
            session.add(PackFile(
                pack_id=pack_id, filename=filename, stored_name=stored, size=size,
                mime=upload.content_type or mimetypes.guess_type(filename)[0],
            ))
        await session.commit()
    except BaseException:
        await session.rollback()
        for path in written:
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    await session.refresh(pack)
    return pack_out(pack)


@router.delete("/{pack_id}/files/{file_id}")
async def delete_file(pack_id: int, file_id: int, session: AsyncSession = Depends(get_session)):
    pack = await get_pack(session, pack_id)
    target = next((f for f in pack.files if f.id == file_id), None)
    if target is None:
        raise HTTPException(404, "Fichier introuvable.")
    path = os.path.join(pack_files_dir(get_config().data_dir, pack_id), target.stored_name)
    pack.files.remove(target)
    if pack.active and not has_content(pack):
        pack.active = False  # plus rien à livrer : le pack sort de la vente
    await session.commit()
    try:
        os.remove(path)
    except OSError:
        pass
    await session.refresh(pack)
    return pack_out(pack)


@router.get("/{pack_id}/files/{file_id}")
async def download_file(pack_id: int, file_id: int, session: AsyncSession = Depends(get_session)):
    pack = await get_pack(session, pack_id)
    target = next((f for f in pack.files if f.id == file_id), None)
    if target is None:
        raise HTTPException(404, "Fichier introuvable.")
    path = os.path.join(pack_files_dir(get_config().data_dir, pack_id), target.stored_name)
    if not os.path.isfile(path):
        raise HTTPException(404, "Le fichier n'est plus présent sur le serveur.")
    return FileResponse(path, filename=target.filename, media_type=target.mime or "application/octet-stream")
