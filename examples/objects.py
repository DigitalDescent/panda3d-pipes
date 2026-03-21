"""
Example distributed object classes for the panda3d-pipes basic demo.

Defines both client-side and server-side (AI) versions of:
  - DistributedChat / DistributedChatAI
  - DistributedAvatar / DistributedAvatarAI
"""

from panda3d.core import Vec3

from panda3d_pipes.native import InterpolatedFloat, InterpolatedVec3
from panda3d_pipes.objects import DistributedObject, DistributedObjectAI

# ---------------------------------------------------------------------------
# Chat object -- client side
# ---------------------------------------------------------------------------


class DistributedChat(DistributedObject):
    """Client-side view of the chat object."""

    def chatMessage(self, sender: str, text: str) -> None:
        """Called when the server broadcasts a chat message."""
        print(f"[Chat] {sender}: {text}")

    def sendChat(self, text: str) -> None:
        """Send a chat message to the server."""
        self.send_update("sendChat", [text])


class DistributedChatAI(DistributedObjectAI):
    """Server-side view of the chat object."""

    def sendChat(self, text: str) -> None:
        """A client wants to send a chat message."""
        client = self.owner
        name = f"Client-{client.id}" if client else "Unknown"
        print(f"[Server Chat] {name}: {text}")
        # Broadcast to all interested clients.
        self.send_update("chatMessage", [name, text])


# ---------------------------------------------------------------------------
# Avatar object -- client side
# ---------------------------------------------------------------------------


class DistributedAvatar(DistributedObject):
    """Client-side view of an avatar with interpolated position."""

    def __init__(self) -> None:
        super().__init__()
        self.predictable: bool = False

        # Raw network-received values (written by setPos / setH).
        self.x: float = 0.0
        self.y: float = 0.0
        self.z: float = 0.0
        self.h: float = 0.0

        # Interpolated variables.
        self.iv_pos: InterpolatedVec3 = InterpolatedVec3()
        self.iv_h: InterpolatedFloat = InterpolatedFloat()

    # -- network field handlers (called by B_ObjectMessage / receiveUpdate) ----

    def setPos(self, x: float, y: float, z: float) -> None:
        self.x, self.y, self.z = x, y, z

    def setH(self, h: float) -> None:
        self.h = h

    # -- snapshot recv proxies (called by C++ unpack_object_state) -------------
    # Without these the C++ code falls back to __dict__["setPos"] = (x,y,z)
    # which overwrites the *method* with a tuple and never touches self.x/y/z.

    def RecvProxy_setPos(self, x: float, y: float, z: float) -> None:
        self.x, self.y, self.z = x, y, z

    def RecvProxy_setH(self, h: float) -> None:
        self.h = h

    # -- lifecycle ------------------------------------------------------------

    def announce_generate(self) -> None:
        super().announce_generate()

        if not self.is_owner:
            # Register interpolated variables so remote avatar position is
            # smoothed between network updates.  The *owner* sets position
            # locally every frame, so interpolation would fight with that.
            self.add_interpolated_var(
                self.iv_pos,
                self._get_pos,
                self._set_pos,
            )
            self.add_interpolated_var(
                self.iv_h,
                self._get_h,
                self._set_h,
            )

        print(f"[Client] Avatar {self.do_id} generated "
              f"(owner={self.is_owner}) at ({self.x}, {self.y}, {self.z})")

    def disable(self) -> None:
        print(f"[Client] Avatar {self.do_id} disabled")
        super().disable()

    def delete(self) -> None:
        print(f"[Client] Avatar {self.do_id} deleted")
        super().delete()

    # -- interpolation helpers ------------------------------------------------

    def _get_pos(self) -> Vec3:
        return Vec3(self.x, self.y, self.z)

    def _set_pos(self, v: Vec3) -> None:
        self.x, self.y, self.z = v.x, v.y, v.z

    def _get_h(self) -> float:
        return self.h

    def _set_h(self, v: float) -> None:
        self.h = v

    def post_interpolate(self) -> None:
        """Called each frame after interpolation has blended x/y/z/h."""
        print(f"[Interp] Avatar {self.do_id} pos=({self.x:.3f}, {self.y:.3f}, {self.z:.3f}) "
              f"h={self.h:.2f}  samples={self.iv_pos.get_num_samples()}")


class DistributedAvatarAI(DistributedObjectAI):
    """Server-side view of an avatar."""

    def __init__(self) -> None:
        super().__init__()
        self.x: float = 0.0
        self.y: float = 0.0
        self.z: float = 0.0
        self.h: float = 0.0

    # -- snapshot send proxies (called by C++ encode_object_state) -------------
    # Without these the C++ code looks for __dict__["setPos"] which doesn't
    # exist (the method lives on the class), so snapshots pack default zeros.

    def SendProxy_setPos(self):
        return (self.x, self.y, self.z)

    def SendProxy_setH(self):
        return (self.h,)

    def setPos(self, x: float, y: float, z: float) -> None:
        self.x, self.y, self.z = x, y, z
        # Rebroadcast to other interested clients (exclude the owner who sent it).
        self.send_update("setPos", [x, y, z],
                         exclude_clients=[self.owner] if self.owner else [])
        client = self.owner
        name = f"Client-{client.id}" if client else "?"
        print(f"[Server] {name}'s avatar pos=({x:.1f}, {y:.1f}, {z:.1f})")

    def setH(self, h: float) -> None:
        self.h = h
        self.send_update("setH", [h],
                         exclude_clients=[self.owner] if self.owner else [])
