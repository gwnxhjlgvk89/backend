# websocket_manager.py
from fastapi import WebSocket
from typing import Dict


class ConnectionManager:
    def __init__(self):
        # 存储所有连接：{student_id: WebSocket}
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, student_id: str, websocket: WebSocket):
        await websocket.accept()  # 接受连接
        self.active_connections[student_id] = websocket
        print(f"学生 {student_id} 已连接，当前在线：{len(self.active_connections)}")

    def disconnect(self, student_id: str):
        self.active_connections.pop(student_id, None)
        print(f"学生 {student_id} 已断开，当前在线：{len(self.active_connections)}")

    def active_count(self) -> int:
        return len(self.active_connections)

    async def send_to_student(self, student_id: str, message: dict):
        websocket = self.active_connections.get(student_id)
        if websocket:
            try:
                await websocket.send_json(message)
            except Exception as e:
                print(f"[WS] 推送失败，学生 {student_id} 已断线: {e}")
                self.disconnect(student_id)  # ✅ 推送失败说明连接已死，直接清理

    async def broadcast(self, message: dict):
        # ✅ 遍历副本，防止推送过程中字典被修改报错
        disconnected = []
        for student_id, ws in list(self.active_connections.items()):
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(student_id)


# 全局单例
manager = ConnectionManager()
