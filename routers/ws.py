from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from websocket_manager import manager
from auth import decode_access_token
import asyncio
import models
import json
from database import SessionLocal

router = APIRouter()

HEARTBEAT_TIMEOUT = 30  # 超过 30s 没收到 ping，判定为断线


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
):
    # ── 1. 验证 token ─────────────────────────────────────────
    payload = decode_access_token(token)
    if payload is None:
        await websocket.close(code=1008, reason="Invalid token")
        return

    student_id = payload.get("sub")
    if not student_id:
        await websocket.close(code=1008, reason="Missing student_id")
        return

    # ── 2. 验证学生是否存在 ───────────────────────────────────
    db = SessionLocal()
    try:
        student = (
            db.query(models.Students)
            .filter(models.Students.student_id == student_id)
            .first()
        )
    finally:
        db.close()

    if student is None:
        await websocket.close(code=1008, reason="Student not found")
        return

    # ── 3. 建立连接 ───────────────────────────────────────────
    await manager.connect(student.student_id, websocket)
    print(f"[WS] 学生 {student.student_id} 已连接，当前在线: {manager.active_count()}")

    # 连接成功后推送欢迎消息
    await websocket.send_json(
        {
            "event": "connected",
            "message": f"欢迎，{student.name}！连接已建立",
        }
    )

    # ── 4. 持续监听 ───────────────────────────────────────────
    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=HEARTBEAT_TIMEOUT
                )

                # ── 解析消息 ──────────────────────────────────
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    print(f"[WS] 学生 {student.student_id} 发送了非法消息: {data}")
                    await websocket.send_json(
                        {
                            "event": "error",
                            "message": "消息格式错误，请发送 JSON",
                        }
                    )
                    continue

                # ── 路由事件 ──────────────────────────────────
                event_type = msg.get("event")

                if event_type == "ping":
                    print(f"[WS] 收到学生 {student.student_id} 的心跳 ping")
                    await websocket.send_json({"event": "pong"})

                else:
                    print(
                        f"[WS] 收到未知事件: {event_type}，来自: {student.student_id}"
                    )
                    await websocket.send_json(
                        {
                            "event": "error",
                            "message": f"未知事件类型: {event_type}",
                        }
                    )

            except asyncio.TimeoutError:
                print(f"[WS] 学生 {student.student_id} 心跳超时，主动断开")
                try:
                    await websocket.send_json(
                        {
                            "event": "timeout",
                            "message": "心跳超时，连接已断开，请重新连接",
                        }
                    )
                    await websocket.close(code=1001)
                except Exception:
                    pass  # 发送失败也无所谓，连接本身已经断了
                break

    except WebSocketDisconnect as e:
        print(f"[WS] 学生 {student.student_id} 主动断开，code={e.code}")

    except Exception as e:
        print(f"[WS] 学生 {student.student_id} 发生未知错误: {e}")
        try:
            await websocket.close(code=1011)  # ✅ 兜底 close
        except Exception:
            pass  # 已经断了就算了

    finally:
        manager.disconnect(student.student_id)
        print(
            f"[WS] 学生 {student.student_id} 连接已清理，当前在线: {manager.active_count()}"
        )
