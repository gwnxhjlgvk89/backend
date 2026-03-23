from fastapi import APIRouter
from routers.admin.upload_xlsx import router as upload_xlsx_router
from routers.admin.test import router as test_router

# 后续在 add / clear / edit 里定义好 router 后，在这里取消注释即可：
# from routers.admin.add import router as add_router
# from routers.admin.clear import router as clear_router
# from routers.admin.edit import router as edit_router

router = APIRouter()
router.include_router(upload_xlsx_router)
router.include_router(test_router)
# router.include_router(clear_router)
# router.include_router(edit_router)
