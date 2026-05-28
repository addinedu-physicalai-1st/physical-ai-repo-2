import asyncio

from control_service.eduping.mugunghwa_relay import (
    MugunghwaEventHub,
    MugunghwaVideoHub,
)


class FakeWS:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.byte_frames: list[bytes] = []
        self.closed = False

    async def send_text(self, t: str) -> None:
        self.texts.append(t)

    async def send_bytes(self, b: bytes) -> None:
        self.byte_frames.append(b)

    async def close(self, code: int | None = None) -> None:
        self.closed = True


def test_event_hub_forward_robot_to_ui():
    async def run() -> None:
        hub = MugunghwaEventHub()
        robot, ui = FakeWS(), FakeWS()
        await hub.register("robot", robot)
        await hub.register("ui", ui)
        await hub.forward("robot", '{"type":"registered","child_id":3}')
        assert ui.texts[-1] == '{"type":"registered","child_id":3}'

    asyncio.run(run())


def test_event_hub_forward_ui_to_robot():
    async def run() -> None:
        hub = MugunghwaEventHub()
        robot, ui = FakeWS(), FakeWS()
        await hub.register("robot", robot)
        await hub.register("ui", ui)
        await hub.forward("ui", '{"type":"observe_start"}')
        assert robot.texts[-1] == '{"type":"observe_start"}'

    asyncio.run(run())


def test_video_hub_fanout_and_last_frame():
    async def run() -> None:
        hub = MugunghwaVideoHub()
        c1 = FakeWS()
        await hub.register_consumer(c1)
        await hub.push_frame(b"jpeg-1")
        assert c1.byte_frames == [b"jpeg-1"]
        # 늦게 들어온 consumer 는 마지막 프레임을 즉시 받는다.
        c2 = FakeWS()
        await hub.register_consumer(c2)
        assert c2.byte_frames == [b"jpeg-1"]

    asyncio.run(run())
