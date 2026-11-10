"""پنل‌های جعلی درون‌پردازه‌ای (aiohttp.web) برای تست آداپتورها؛ بدون شبکه‌ی واقعی."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer


class FakePanel:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str, Any]] = []
        self.created_payloads: list[dict[str, Any]] = []
        self.logins = 0
        self.valid_tokens: set[str] = set()
        self.slow = False
        self.reject_create = False
        self.server: TestServer | None = None

    @property
    def url(self) -> str:
        assert self.server is not None
        return str(self.server.make_url("")).rstrip("/")

    async def start(self, app: web.Application) -> FakePanel:
        self.server = TestServer(app)
        await self.server.start_server()
        return self

    async def stop(self) -> None:
        if self.server:
            await self.server.close()

    async def _maybe_slow(self) -> None:
        if self.slow:
            await asyncio.sleep(1.0)


def _json(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


# ------------------------------------------------------------ token panels
class FakeTokenPanel(FakePanel):
    """مشترک PasarGuard و Marzban: login فرم‌انکد + Bearer."""

    def __init__(self, *, username: str = "admin", password: str = "pw") -> None:
        super().__init__()
        self._cred = (username, password)

    def _auth(self, request: web.Request) -> bool:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        return token in self.valid_tokens

    async def token(self, request: web.Request) -> web.Response:
        form = await request.post()
        if (form.get("username"), form.get("password")) != self._cred:
            return _json({"detail": "Incorrect username or password"}, 401)
        self.logins += 1
        token = f"tok-{self.logins}"
        self.valid_tokens.add(token)
        return _json({"access_token": token, "token_type": "bearer"})

    def expire_tokens(self) -> None:
        self.valid_tokens.clear()


class FakePasarGuard(FakeTokenPanel):
    def __init__(self, groups: list[dict[str, Any]] | None = None, **kw: Any) -> None:
        super().__init__(**kw)
        self.groups = (
            groups
            if groups is not None
            else [
                {"id": 3, "name": "premium", "inbound_tags": ["a"], "is_disabled": False, "total_users": 0},
                {"id": 7, "name": "basic", "inbound_tags": ["b"], "is_disabled": False, "total_users": 0},
                {"id": 9, "name": "old", "inbound_tags": ["c"], "is_disabled": True, "total_users": 0},
            ]
        )
        self.deny_groups = False

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/api/admin/token", self.token)
        app.router.add_get("/api/groups", self.list_groups)
        app.router.add_get("/api/groups/simple", self.list_groups_simple)
        app.router.add_post("/api/user", self.create)
        app.router.add_get("/api/user/{u}", self.get)
        app.router.add_put("/api/user/{u}", self.put)
        app.router.add_delete("/api/user/{u}", self.delete)
        return app

    async def list_groups(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return _json({"detail": "Not authenticated"}, 401)
        if self.deny_groups:
            return _json({"detail": "Permission denied: groups.read"}, 403)
        return _json({"groups": self.groups, "total": len(self.groups)})

    async def list_groups_simple(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return _json({"detail": "Not authenticated"}, 401)
        rows = [{"id": g["id"], "name": g["name"]} for g in self.groups]
        return _json({"groups": rows, "total": len(rows)})

    async def create(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return _json({"detail": "Not authenticated"}, 401)
        payload = await request.json()
        self.created_payloads.append(payload)
        if self.reject_create or not payload.get("group_ids"):
            return _json({"detail": "you must select at least one group"}, 422)
        known = {g["id"] for g in self.groups if not g["is_disabled"]}
        if not set(payload["group_ids"]) <= known:
            return _json({"detail": "Group not found"}, 400)
        if payload["username"] in self.users:
            return _json({"detail": "User already exists"}, 409)
        # expire key may be omitted for unlimited (PasarGuard)
        expire_raw = payload.get("expire")
        user = {
            "username": payload["username"],
            "status": "active",
            "used_traffic": 0,
            "data_limit": payload["data_limit"],
            "expire": int(expire_raw) if expire_raw is not None else None,
            "subscription_url": f"/sub/{payload['username']}",
            "group_ids": payload["group_ids"],
        }
        self.users[payload["username"]] = user
        await self._maybe_slow()  # کاربر ساخته شده ولی پاسخ دیر می‌رسد
        return _json(user, 201)

    async def get(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return _json({"detail": "Not authenticated"}, 401)
        user = self.users.get(request.match_info["u"])
        return _json(user) if user else _json({"detail": "User not found"}, 404)

    async def put(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return _json({"detail": "Not authenticated"}, 401)
        user = self.users.get(request.match_info["u"])
        if not user:
            return _json({"detail": "User not found"}, 404)
        user.update(await request.json())
        return _json(user)

    async def delete(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return _json({"detail": "Not authenticated"}, 401)
        if self.users.pop(request.match_info["u"], None) is None:
            return _json({"detail": "User not found"}, 404)
        return web.Response(status=204)


class FakeMarzban(FakeTokenPanel):
    INBOUNDS = {
        "vless": [{"tag": "VLESS TCP", "protocol": "vless", "network": "tcp", "tls": "reality", "port": 443}],
        "vmess": [{"tag": "VMess WS", "protocol": "vmess", "network": "ws", "tls": "tls", "port": 8443}],
    }

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/api/admin/token", self.token)
        app.router.add_get("/api/inbounds", self.inbounds)
        app.router.add_post("/api/user", self.create)
        app.router.add_get("/api/user/{u}", self.get)
        app.router.add_put("/api/user/{u}", self.put)
        app.router.add_delete("/api/user/{u}", self.delete)
        return app

    async def inbounds(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return _json({"detail": "Not authenticated"}, 401)
        return _json(self.INBOUNDS)

    async def create(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return _json({"detail": "Not authenticated"}, 401)
        payload = await request.json()
        self.created_payloads.append(payload)
        if self.reject_create or not payload.get("proxies"):
            return _json({"detail": "Each user needs at least one proxy"}, 422)
        if payload["username"] in self.users:
            return _json({"detail": "User already exists"}, 409)
        user = {
            "username": payload["username"],
            "status": "active",
            "used_traffic": 0,
            "data_limit": payload["data_limit"],
            "expire": payload["expire"] or None,
            "subscription_url": f"/sub/{payload['username']}",
        }
        self.users[payload["username"]] = user
        await self._maybe_slow()  # کاربر ساخته شده ولی پاسخ دیر می‌رسد
        return _json(user, 201)

    get = FakePasarGuard.get
    put = FakePasarGuard.put
    delete = FakePasarGuard.delete


# ----------------------------------------------------------------- hiddify
class FakeHiddify(FakePanel):
    PREFIX = "/adminpath/api/v2"

    def __init__(self, *, api_key: str = "KEY", has_ping: bool = True) -> None:
        super().__init__()
        self.api_key = api_key
        self.has_ping = has_ping

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get(f"{self.PREFIX}/panel/ping/", self.ping)
        app.router.add_get(f"{self.PREFIX}/panel/info/", self.info)
        app.router.add_get(f"{self.PREFIX}/admin/me/", self.me)
        app.router.add_post(f"{self.PREFIX}/admin/user/", self.create)
        app.router.add_get(f"{self.PREFIX}/admin/user/{{u}}/", self.get)
        app.router.add_patch(f"{self.PREFIX}/admin/user/{{u}}/", self.patch)
        app.router.add_delete(f"{self.PREFIX}/admin/user/{{u}}/", self.delete)
        return app

    def _auth(self, request: web.Request) -> bool:
        return request.headers.get("Hiddify-API-Key") == self.api_key

    def _denied(self) -> web.Response:
        # رفتار واقعی: ریدایرکت به صفحه‌ی لاگین
        return web.Response(status=302, headers={"Location": "/login"})

    async def ping(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return self._denied()
        if not self.has_ping:
            return _json({"msg": "not found"}, 404)
        await self._maybe_slow()
        return _json({"msg": "pong"})

    async def info(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return self._denied()
        return _json({"version": "12.0"})

    async def me(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return self._denied()
        return _json({
            "uuid": self.api_key,
            "name": "admin",
            "telegram_id": 123456,
            "can_add_admin": True,
            "comment": "",
            "lang": "en",
            "mode": "owner",
        })

    async def create(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return self._denied()
        payload = await request.json()
        self.created_payloads.append(payload)
        if self.reject_create:
            return _json({"message": "User limit reached"}, 400)
        if payload["uuid"] in self.users:
            return _json({"message": "The user exists"}, 400)
        user = {"current_usage_GB": 0.0, "enable": True, **payload}
        self.users[payload["uuid"]] = user
        await self._maybe_slow()
        return _json(user)

    async def get(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return self._denied()
        user = self.users.get(request.match_info["u"])
        return _json(user) if user else _json({"message": "User not found"}, 404)

    async def patch(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return self._denied()
        user = self.users.get(request.match_info["u"])
        if not user:
            return _json({"message": "User not found"}, 404)
        user.update(await request.json())
        return _json(user)

    async def delete(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return self._denied()
        if self.users.pop(request.match_info["u"], None) is None:
            return _json({"message": "User not found"}, 404)
        return _json({"status": 200, "msg": "ok"})
