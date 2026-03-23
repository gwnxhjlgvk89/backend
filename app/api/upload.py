# app/api/upload.py
import uuid
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.core.r2 import get_r2_client
from app.core.config import settings

router = APIRouter()

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE = 2 * 1024 * 1024  # 2MB


@router.post("/upload/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    # current_user = Depends(get_current_user),  # 鉴权
):
    # 1️⃣ 校验文件类型
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, "只支持 JPG / PNG / WebP")

    # 2️⃣ 读取内容并校验大小
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "文件不能超过 2MB")

    # 3️⃣ 生成唯一文件名
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")
    ext = file.filename.rsplit(".", 1)[-1]
    filename = f"avatars/{uuid.uuid4().hex}.{ext}"

    # 4️⃣ 上传到 R2
    try:
        client = get_r2_client()
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=filename,
            Body=content,
            ContentType=file.content_type,
        )
    except Exception as e:
        raise HTTPException(500, f"上传失败: {str(e)}")

    # 5️⃣ 返回公开访问 URL
    url = f"{settings.R2_PUBLIC_URL}/{filename}"
    return url
