"""
Example server for panda3d-pipes.

Starts a headless Panda3D server that:
  - Listens for client connections on the configured port (default 27015)
  - Creates a shared DistributedChat object in zone 1
  - Spawns a DistributedAvatar for each client that connects
  - Replicates avatar position and chat messages to all interested clients

Usage:
    python server.py

Requirements:
    - Panda3D 1.11.0+
    - panda3d-pipes (built and installed / on sys.path)
    - panda3d-steamworks
    - Steam client running (for Steam networking)
"""

import sys
import os

# Ensure the examples package is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from panda3d.core import loadPrcFileData, ClockObject
from panda3d_steamworks.showbase import SteamShowBase


class GameShowBase(SteamShowBase):
    """SteamShowBase extended with tick-rate bookkeeping expected by ServerRepository."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ticksPerSec = 30
        self.tickCount = 0
        self._tickInterval = 1.0 / self.ticksPerSec
        self._tickAccum = 0.0
        self.clockMgr = self._ClockMgr()
        self.taskMgr.add(self._tickTask, "tickTask", sort=-200)

    class _ClockMgr:
        def getTime(self):
            return ClockObject.getGlobalClock().getRealTime()

    def setTickRate(self, rate):
        self.ticksPerSec = rate
        self._tickInterval = 1.0 / rate

    def _tickTask(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self._tickAccum += dt
        while self._tickAccum >= self._tickInterval:
            self._tickAccum -= self._tickInterval
            self.tickCount += 1
        return task.cont


# Server-side PRC configuration.
loadPrcFileData("", """
window-type none
notify-level-ServerRepository info
sv-tickrate 30
sv-port 27015
sv-max-clients 8
""")

# Start Panda3D in headless mode.
base = GameShowBase(windowType="none")

from panda3d_pipes.repository import ServerRepository
from examples.objects import DistributedChatAI, DistributedAvatarAI

import math

# ---------------------------------------------------------------------------

ZONE_LOBBY = 1


class ExampleServer(ServerRepository):
    """A minimal game server demonstrating panda3d-pipes."""

    def __init__(self):
        # Initialize the server (starts listening automatically).
        super().__init__(listen_port=27015)
        
        # Read the DC file so both sides agree on the object schema.
        self.read_dc_files(["examples/example.dc"])

        # Create a shared chat object in the lobby zone.
        self.chat_obj = DistributedChatAI()
        self.generate_object(self.chat_obj, zone_id=ZONE_LOBBY)

        # Create an NPC avatar that orbits in a circle.  Because it has no
        # owner, every client sees it as a *remote* object and will
        # interpolate its position – handy for testing even with one client.
        self.npc = DistributedAvatarAI()
        self.generate_object(self.npc, zone_id=ZONE_LOBBY)
        base.taskMgr.add(self._move_npc_task, "moveNpc")

        # Listen for client lifecycle events.
        self.accept("clientConnected", self.on_client_connected)
        self.accept("clientDisconnected", self.on_client_disconnected)

        print(f"[Server] Listening on port 27015 (tick rate: {base.ticksPerSec})")
        print(f"[Server] NPC avatar {self.npc.do_id} orbiting in zone {ZONE_LOBBY}")
        print("[Server] Waiting for clients...")

    def on_client_connected(self, client):
        print(f"[Server] Client {client.id} connected from {client.net_address}")

        # Give the client interest in the lobby zone so they see objects there.
        self.add_explicit_interest(client, [ZONE_LOBBY])

        # Spawn an avatar for this client.
        avatar = DistributedAvatarAI()
        self.generate_object(avatar, zone_id=ZONE_LOBBY, owner=client)
        print(f"[Server] Spawned avatar {avatar.do_id} for client {client.id}")

    def on_client_disconnected(self, client):
        print(f"[Server] Client {client.id} disconnected")

    # -- NPC movement -------------------------------------------------------

    def _move_npc_task(self, task):
        """Update the NPC's position every frame.

        We write directly to the attributes that ``SendProxy_setPos`` /
        ``SendProxy_setH`` read — the snapshot system picks them up
        automatically each tick.  No ``send_update`` needed.
        """
        t = globalClock.getRealTime()
        self.npc.x = math.sin(t * 0.5) * 3.0
        self.npc.y = math.cos(t * 0.5) * 3.0
        self.npc.h = math.degrees(t * 0.5) % 360
        return task.cont


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    server = ExampleServer()
    print("[Server] Running. Press Ctrl+C to stop.")
    base.run()
