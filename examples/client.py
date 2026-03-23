"""
Example client for panda3d-pipes.

Connects to the example server, sends a hello, and after authentication:
  - Requests interest in the lobby zone
  - Listens for chat messages and avatar updates
  - Sends a chat message once connected
  - Periodically moves the avatar

Usage:
    1. Start server.py in one terminal
    2. Start client.py in another terminal

Requirements:
    - Panda3D 1.11.0+
    - panda3d-pipes (built and installed / on sys.path)
    - panda3d-steamworks
    - Steam client running (for Steam networking)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from panda3d.core import loadPrcFileData, ClockObject, NetAddress

loadPrcFileData("", """
window-type none
notify-level-ClientRepository info
dc-file examples/example.dc
""")

from panda3d_steamworks.showbase import SteamShowBase


class GameShowBase(SteamShowBase):
    """SteamShowBase extended with tick-rate bookkeeping expected by ClientRepository."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tickCount = 0
        self.intervalPerTick = 0.0
        self.remainder = 0.0
        self._tickAccum = 0.0
        self.clockMgr = self._ClockMgr(self)
        self.taskMgr.add(self._tick_task, "tickTask", sort=-200)

    class _ClockMgr:
        def __init__(self, base):
            self._base = base
            self._client_time = 0.0
            self._prev_tick_count = 0

        def getTime(self):
            return ClockObject.getGlobalClock().getRealTime()

        def getClientTime(self):
            return self._client_time

        def networkToClientTime(self, server_time):
            """Convert a server timestamp to client-local time.

            In a simple setup without sophisticated clock correction the
            server tick time is just used directly.
            """
            return server_time

        @property
        def simulationDeltaNoRemainder(self):
            delta_ticks = self._base.tickCount - self._prev_tick_count
            return delta_ticks * self._base.intervalPerTick

    def setTickRate(self, rate):
        self.intervalPerTick = 1.0 / rate

    def ticksToTime(self, ticks):
        return ticks * self.intervalPerTick

    def timeToTicks(self, time_val):
        if self.intervalPerTick <= 0:
            return 0
        return int(time_val / self.intervalPerTick + 0.5)

    def _tick_task(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        if self.intervalPerTick <= 0:
            return task.cont
        self._tickAccum += dt
        self.clockMgr._prev_tick_count = self.tickCount
        while self._tickAccum >= self.intervalPerTick:
            self._tickAccum -= self.intervalPerTick
            self.tickCount += 1
        self.remainder = self._tickAccum
        self.clockMgr._client_time += dt
        return task.cont


base = GameShowBase(windowType="none")

from panda3d_pipes.distributed.repository import ClientRepository
from panda3d_pipes.distributed.config import sv_password

# ---------------------------------------------------------------------------

ZONE_LOBBY = 1
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 27015


class ExampleClient(ClientRepository):
    """A minimal client demonstrating panda3d-pipes.

    All standard protocol handling (hello, tick/snapshot, generate,
    delete, object messages, ping) is provided by the base
    ``ClientRepository``.  This subclass only adds game-specific
    behaviour.
    """

    def __init__(self):
        super().__init__()

        # Read DC files for object schema.
        self.read_dc_files(["examples/example.dc"])

        # Listen for lifecycle events emitted by the base class.
        self.accept("connectSuccess", self.on_connect_success)
        self.accept("connectionLost", self.on_connection_lost)
        self.accept("helloResponse", self.on_hello_response)
        self.accept("interestComplete", self.on_interest_complete)

        # Connect to the local server.
        addr = NetAddress()
        addr.setHost(SERVER_HOST, SERVER_PORT)
        print(f"[Client] Connecting to {SERVER_HOST}:{SERVER_PORT}...")
        self.connect(addr)

    # -- Connection lifecycle -----------------------------------------------

    def on_connect_success(self, address):
        print("[Client] Connected! Sending hello...")
        self.send_hello(sv_password.getValue())

    def on_connection_lost(self):
        print("[Client] Connection lost.")
        sys.exit(1)

    def on_hello_response(self):
        print(f"[Client] Authenticated! client_id={self.client_id} "
              f"tick_rate={self.server_tick_rate}")
        self.set_interest([ZONE_LOBBY])

    def on_interest_complete(self, handle):
        print(f"[Client] Interest complete (handle={handle})")
        # Send a chat message after a short delay.
        base.taskMgr.doMethodLater(1.0, self._send_chat_task, "sendChat")
        # Move avatar at ~20 Hz (fast enough to give the interpolation system
        # on OTHER clients a steady stream of sample points to blend between).
        base.taskMgr.doMethodLater(0.05, self._move_avatar_task, "moveAvatar")

    # -- Example tasks ------------------------------------------------------

    def _send_chat_task(self, task):
        """Send a chat message via any DistributedChat object we know about."""
        from examples.objects import DistributedChat
        for do in self.do_id_to_do.values():
            if isinstance(do, DistributedChat):
                do.sendChat("Hello from the example client!")
                print("[Client] Sent chat message")
                return task.done
        print("[Client] No chat object found yet, retrying...")
        return task.again

    def _move_avatar_task(self, task):
        """Send position updates for our *own* avatar at a steady rate."""
        from examples.objects import DistributedAvatar
        import math
        t = globalClock.getRealTime()
        x = math.sin(t) * 5.0
        y = math.cos(t) * 5.0
        h = math.degrees(t) % 360
        for do in self.do_id_to_do.values():
            if isinstance(do, DistributedAvatar) and do.is_owner:
                # Set local position immediately so we see smooth movement.
                do.x, do.y, do.z = x, y, 0.0
                do.h = h
                # Replicate to server (and from there to other clients).
                do.send_update("setPos", [x, y, 0.0])
                do.send_update("setH", [h])
                return task.again
        return task.again


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    client = ExampleClient()
    print("[Client] Running. Press Ctrl+C to stop.")
    base.run()
