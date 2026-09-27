import asyncio
from io import BytesIO
import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import update

from club.config import settings
from club.errors import fail
from club.models import User
from club.security import rate_limit, student

router = APIRouter()


def normalize(content):
    try:
        with Image.open(BytesIO(content)) as img:
            if img.format not in {"JPEG", "PNG", "WEBP"} or img.width * img.height > 16000000:
                fail(422, "INVALID_IMAGE", "图片格式或尺寸不受支持")
            img.load()
            img.thumbnail((512, 512))
            output = BytesIO()
            img.convert("RGB").save(output, "JPEG", quality=85)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        fail(422, "INVALID_IMAGE", "无法读取图片")


def save_image(content, name):
    s = settings()
    if s.storage_backend == "local":
        folder = s.storage_dir / "avatars"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
        return f"{s.public_url}/api/v1/media/{name}"
    import boto3
    from botocore.config import Config
    client = boto3.client("s3", endpoint_url=s.r2_endpoint, aws_access_key_id=s.r2_access_key,
                          aws_secret_access_key=s.r2_secret_key,
                          config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 2}))
    client.put_object(Bucket=s.r2_bucket, Key=f"avatars/{name}", Body=content, ContentType="image/jpeg")
    return f"{s.r2_public_url}/avatars/{name}"


@router.post("/profile/avatar")
async def upload(request: Request, file: UploadFile = File(), user=Depends(student)):
    await rate_limit(request, "upload", user.id, 5, 60)
    raw = await file.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        fail(413, "FILE_TOO_LARGE", "头像不能超过2MB")
    content = await asyncio.to_thread(normalize, raw)
    url = await asyncio.to_thread(save_image, content, uuid.uuid4().hex + ".jpg")
    async with request.app.state.sessions() as db, db.begin():
        await db.execute(update(User).where(User.id == user.id).values(avatar=url))
    return {"data": {"avatar": url}}


@router.get("/media/{name}")
async def media(name: str):
    if len(name) != 36 or not name.endswith(".jpg") or any(c not in "0123456789abcdef" for c in name[:32]):
        fail(404, "NOT_FOUND", "文件不存在")
    path = settings().storage_dir / "avatars" / name
    if not path.is_file():
        fail(404, "NOT_FOUND", "文件不存在")
    return FileResponse(path, media_type="image/jpeg")
