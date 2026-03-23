# locustfile.py
import json
import time
import threading
import random
from locust import HttpUser, task, between, events
from websocket import WebSocketApp

BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://your-server-ip:8000/ws"

# ── 预先准备好 1000 个测试账号的 token ──────────────────────
# 提前跑一遍登录，把 token 存进来
TOKENS = []

# # 启动 Web UI 模式（推荐，可实时看曲线）
# locust -f locustfile.py --host http://your-server-ip:8000

# # 然后浏览器打开 http://localhost:8089
# # 设置：
# #   Number of users:  1000
# #   Spawn rate:       50      ← 每秒新增50个用户，20秒内达到1000
# #   Host:             http://your-server-ip:8000

STUDENT_COUNT = 1000  # 预设的测试学生数量


def reset_test_students():
    """重置测试学生数据（选社状态）"""
    import requests

    try:
        res = requests.post(
            f"{BASE_URL}/admin/createteststudents",
            json={"count": STUDENT_COUNT},
            timeout=10,
        )
        if res.status_code == 200:
            print(f"[reset] 成功重置测试学生数据")
        else:
            print(f"[reset] 重置失败 状态码: {res.status_code}")
    except Exception as e:
        print(f"[reset] 请求失败 {e}")


def preload_tokens():
    """启动前批量登录，拿到所有 token"""
    import requests

    for i in range(1, STUDENT_COUNT + 1):
        try:
            res = requests.post(
                f"{BASE_URL}/auth/login",
                json={
                    "username": f"test{i:04d}",  # test0001 ~ test1000
                    "password": f"测试用户{i}",
                },
                timeout=10,
            )
            token = res.json()["data"]["token"]
            if token:
                TOKENS.append(token)
        except Exception as e:
            print(f"[preload] 登录失败 test{i:04d}: {e}")
    print(f"[preload] 共获取 {len(TOKENS)} 个 token")


reset_test_students()  # 启动时重置数据
# 启动时预加载
preload_tokens()


# ══════════════════════════════════════════════════════════════
# HTTP 压测用户：模拟选社 / 退社
# ══════════════════════════════════════════════════════════════
class ClubSelectUser(HttpUser):
    host = BASE_URL
    wait_time = between(0.5, 2)  # 每次操作间隔 0.5~2s

    def on_start(self):
        """每个虚拟用户启动时随机领一个 token"""
        if not TOKENS:
            self.token = None
            return
        self.token = random.choice(TOKENS)
        self.headers = {"Authorization": f"Bearer {self.token}"}
        # 随机选一个社团名测试
        self.club_names = ["EC社"]

    @task(5)  # 权重 5：选社最多
    def select_club(self):
        if not self.token:
            return
        club_name = random.choice(self.club_names)
        with self.client.post(
            "/student/select",
            json={"club_name": club_name},
            headers=self.headers,
            catch_response=True,
            name="POST /student /select",
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 400:
                # 业务失败（已满/已选）视为预期，不算错误
                resp.success()
            else:
                resp.failure(f"非预期状态码: {resp.status_code}")

    @task(2)  # 权重 2：退社
    def quit_club(self):
        if not self.token:
            return
        with self.client.post(
            "/student/quit",
            headers=self.headers,
            catch_response=True,
            name="POST /student/quit",
        ) as resp:
            # ✅ 200=退社成功 400=未选社 404=社团不存在 均为预期
            if resp.status_code in (200, 400, 404):
                resp.success()
            else:
                resp.failure(f"非预期: {resp.status_code} {resp.text[:100]}")

    @task(3)  # 权重 3：查询列表（读多写少）
    def get_clubs(self):
        if not self.token:
            return
        self.client.get(
            "/student/clubs",
            headers=self.headers,
            name="GET /student/clubs",
        )


# ══════════════════════════════════════════════════════════════
# WebSocket 压测用户：模拟长连接 + 心跳
# ══════════════════════════════════════════════════════════════
# class WsHeartbeatUser(HttpUser):
#     """
#     纯 WS 用户，不做 HTTP 请求。
#     每 10s 发一次 ping，持续持有连接。
#     """

#     host = BASE_URL
#     wait_time = between(10, 12)  # 模拟心跳间隔

#     def on_start(self):
#         if not TOKENS:
#             return
#         self.token = random.choice(TOKENS)
#         self.ws = None
#         self.running = True
#         self._connect_ws()

#     def _connect_ws(self):
#         url = f"{WS_URL}?token={self.token}"

#         def on_open(ws):
#             print(f"[WS] 连接成功")

#         def on_message(ws, msg):
#             data = json.loads(msg)
#             if data.get("event") == "pong":
#                 pass  # 心跳正常

#         def on_error(ws, err):
#             print(f"[WS] 错误: {err}")

#         def on_close(ws, code, reason):
#             if self.running:
#                 # 自动重连
#                 time.sleep(2)
#                 self._connect_ws()

#         self.ws = WebSocketApp(
#             url,
#             on_open=on_open,
#             on_message=on_message,
#             on_error=on_error,
#             on_close=on_close,
#         )
#         # 后台线程跑 WS
#         t = threading.Thread(target=self.ws.run_forever, daemon=True)
#         t.start()

#     @task
#     def send_ping(self):
#         """模拟前端心跳"""
#         if self.ws and self.ws.sock:
#             try:
#                 start = time.time()
#                 self.ws.send(json.dumps({"event": "ping"}))
#                 # 手动上报 WS 心跳耗时到 Locust 统计
#                 elapsed = int((time.time() - start) * 1000)
#                 events.request.fire(
#                     request_type="WS",
#                     name="ping",
#                     response_time=elapsed,
#                     response_length=0,
#                     exception=None,
#                     context={},
#                 )
#             except Exception as e:
#                 events.request.fire(
#                     request_type="WS",
#                     name="ping",
#                     response_time=0,
#                     response_length=0,
#                     exception=e,
#                     context={},
#                 )

#     def on_stop(self):
#         self.running = False
#         if self.ws:
#             self.ws.close()
