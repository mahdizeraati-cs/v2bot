from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
import pytest_asyncio

from core.panels import groups
from core.panels.hiddify import HiddifyAdapter
from core.panels.http import PanelHTTP
from core.panels.marzban import MarzbanAdapter
from core.panels.pasarguard import PasarGuardAdapter
from core.panels.token_base import clear_token_cache
from tests.fake_panels import FakeHiddify, FakeMarzban, FakePanel, FakePasarGuard

NOW = 1_700_000_000.0
TODAY = date(2023, 11, 14)
SECRETS = ("pw", "KEY")


@pytest.fixture(autouse=True)
def _clean_caches() -> None:
    clear_token_cache()
    groups.clear_targets_cache()


@dataclass
class Panel:
    kind: str
    fake: FakePanel
    adapter: Any


async def _make(kind: str, *, bad_credentials: bool, timeout: float) -> Panel:
    if kind == "hiddify":
        fake = FakeHiddify()
        await fake.start(fake.app())
        key = "WRONG" if bad_credentials else "KEY"
        http = PanelHTTP(fake.url, headers={"Hiddify-API-Key": key}, backoff_base=0, total_timeout=timeout)
        adapter = HiddifyAdapter(
            base_url=fake.url,
            api_key=key,
            config={"admin_proxy_path": "adminpath", "client_proxy_path": "clientpath"},
            http=http,
            clock=lambda: NOW,
            today=lambda: TODAY,
            seed="srv-1",
        )
        return Panel(kind, fake, adapter)

    fake_cls, adapter_cls = (
        (FakePasarGuard, PasarGuardAdapter) if kind == "pasarguard" else (FakeMarzban, MarzbanAdapter)
    )
    fake = fake_cls()
    await fake.start(fake.app())
    http = PanelHTTP(fake.url, backoff_base=0, total_timeout=timeout)
    adapter = adapter_cls(
        base_url=fake.url,
        username="admin",
        password="WRONG" if bad_credentials else "pw",
        http=http,
        clock=lambda: NOW,
        cache_key=f"test:{kind}:{fake.url}",
    )
    return Panel(kind, fake, adapter)


@pytest_asyncio.fixture(params=["pasarguard", "marzban", "hiddify"])
async def panel(request: pytest.FixtureRequest) -> AsyncIterator[Panel]:
    p = await _make(request.param, bad_credentials=False, timeout=0.3)
    yield p
    await p.adapter.aclose()
    await p.fake.stop()


@pytest_asyncio.fixture(params=["pasarguard", "marzban", "hiddify"])
async def bad_panel(request: pytest.FixtureRequest) -> AsyncIterator[Panel]:
    p = await _make(request.param, bad_credentials=True, timeout=0.3)
    yield p
    await p.adapter.aclose()
    await p.fake.stop()


@pytest_asyncio.fixture
async def pg() -> AsyncIterator[Panel]:
    p = await _make("pasarguard", bad_credentials=False, timeout=2)
    yield p
    await p.adapter.aclose()
    await p.fake.stop()


@pytest_asyncio.fixture
async def marzban() -> AsyncIterator[Panel]:
    p = await _make("marzban", bad_credentials=False, timeout=2)
    yield p
    await p.adapter.aclose()
    await p.fake.stop()


@pytest_asyncio.fixture
async def hiddify() -> AsyncIterator[Panel]:
    p = await _make("hiddify", bad_credentials=False, timeout=2)
    yield p
    await p.adapter.aclose()
    await p.fake.stop()
