from fastapi import APIRouter
from routers.student.student import router as student_router

# 后续在 add / clear / edit 里定义好 router 后，在这里取消注释即可：
# from routers.admin.add import router as add_router
# from routers.admin.clear import router as clear_router
# from routers.admin.edit import router as edit_router

router = APIRouter()
router.include_router(student_router)
# router.include_router(add_router)
# router.include_router(clear_router)
# router.include_router(edit_router)
