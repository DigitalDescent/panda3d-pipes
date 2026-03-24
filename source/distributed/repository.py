from __future__ import annotations

from enum import IntEnum
from typing import Any

from panda3d.core import UniqueIdAllocator
from panda3d.direct import DCPacker
from panda3d_steamworks import (
    SteamConstants,
    SteamNetworkConnectionInfo,
    SteamNetworkManager,
    SteamNetworkMessage,
    SteamNetworkingConfigValue,
    SteamNetworkingConnectionState,
    SteamNetworkingUtilsAPI,
)
from panda3d_toolbox import runtime

from direct.directnotify.DirectNotifyGlobal import directNotify
from direct.distributed.PyDatagram import PyDatagram

from panda3d_pipes.distributed.constants import NetMessages
from panda3d_pipes.distributed.config import (
    cl_cmdrate,
    cl_ping,
    cl_ping_interval,
    cl_report_ping,
    cl_updaterate,
    get_client_interp_amount,
    sv_max_clients,
    sv_maxupdaterate,
    sv_minupdaterate,
    sv_password,
    sv_tickrate,
)
from panda3d_pipes.native import (
    CClientRepository,
    ClientFrame,
    ClientFrameManager,
    FrameSnapshot,
    FrameSnapshotManager,
    NetworkClock,
)
from .objects import BaseObjectManager, DistributedObject

# -- shared event routing for hosted (server + client in one process) sessions ---


class _NetEvent:
    """Lightweight copy of a SteamNetworking connection-state event."""
    __slots__ = ('connection', 'state', 'old_state')

    def __init__(self, connection: int, state: int, old_state: int) -> None:
        self.connection = connection
        self.state = state
        self.old_state = old_state


_pending_network_events: list[_NetEvent] = []
_client_owned_connections: set[int] = set()


def _drain_network_events(net_sys: SteamNetworkManager) -> None:
    """Drain all pending connection-state events into a shared buffer.

    Both :class:`ClientRepository` and :class:`ServerRepository` call this.
    The first call per frame actually drains; subsequent calls are no-ops
    because the underlying queue is already empty.
    """
    net_sys.run_callbacks()
    event = net_sys.get_next_event()
    while event:
        _pending_network_events.append(
            _NetEvent(event.connection, event.state, event.old_state)
        )
        event = net_sys.get_next_event()


# --------------------------------------------------------------------------------


class ClientState(IntEnum):
    Unverified = 0
    Authenticating = 1
    Verified = 2


# --------------------------------------------------------------------------------


class ClientRepository(BaseObjectManager, CClientRepository):
    notify = directNotify.newCategory("ClientRepository")

    def __init__(self) -> None:
        BaseObjectManager.__init__(self, True)
        CClientRepository.__init__(self)
        self.set_python_repository(self)
        runtime.base.cl = self
        runtime.client = self

        self.net_clock: NetworkClock = NetworkClock.get_global_ptr()

        self.net_sys = SteamNetworkManager.get_global_ptr()
        self.connected: bool = False
        self.is_authed: bool = False
        self.connection_handle: int | None = None
        self.server_address: Any | None = None
        self.msg_type: int = 0

        self.client_id: int = 0
        self.server_tick_count: int = 0
        self.server_tick_rate: int = 0
        self.delta_tick: int = -1
        self.server_interval_per_tick: float = 0
        self.last_server_tick_time: float = 0
        self.interest_handle: int = 0
        self.last_update_time: float = 0

        self.ping_latency: int = 0
        self.pending_ping: bool = False
        self.ping_send_out_time: float = 0.0
        self.next_ping_time: float = 0.0

        self.prediction_random_seed: int = 0
        self.prediction_player: Any | None = None

        self._ip_auth_relaxed: bool = False

    def _configure_networking(self) -> None:
        if self._ip_auth_relaxed:
            return
        SteamNetworkingUtilsAPI.set_global_config_value_int32(
            SteamNetworkingConfigValue.k_ESteamNetworkingConfig_IP_AllowWithoutAuth, 1,
        )
        SteamNetworkingUtilsAPI.set_global_config_value_int32(
            SteamNetworkingConfigValue.k_ESteamNetworkingConfig_IPLocalHost_AllowWithoutAuth, 1,
        )
        self._ip_auth_relaxed = True

    def connect(self, address: Any) -> None:
        """Connect to a server at the given NetAddress."""
        self._configure_networking()
        self.server_address = address
        self.connection_handle = self.net_sys.connect_by_ip_address(address)
        _client_owned_connections.add(self.connection_handle)
        self.connected = True
        self.start_client_loop()

    def disconnect(self) -> None:
        """Disconnect from the server."""
        if self.connection_handle is not None:
            _client_owned_connections.discard(self.connection_handle)
            self.net_sys.close_connection(self.connection_handle)
            self.connection_handle = None
        self.connected = False
        self.is_authed = False
        self.stop_client_loop()

    def send_datagram(self, dg: PyDatagram, reliable: bool = True) -> None:
        """Send a datagram to the server."""
        if self.connection_handle is None:
            return
        if reliable:
            send_type = SteamConstants.k_nSteamNetworkingSend_ReliableNoNagle
        else:
            send_type = SteamConstants.k_nSteamNetworkingSend_UnreliableNoDelay
        self.net_sys.send_datagram(self.connection_handle, dg, send_type)

    def reader_poll_until_empty(self) -> None:
        if self.connection_handle is None:
            return
        msg = SteamNetworkMessage()
        while self.net_sys.receive_message_on_connection(self.connection_handle, msg):
            self.handle_datagram(msg)
            msg = SteamNetworkMessage()

    def handle_datagram(self, msg: SteamNetworkMessage) -> None:
        dgi = msg.dgi
        if dgi.getRemainingSize() < 2:
            return
        self.msg_type = dgi.getUint16()
        self.handle_client_datagram(dgi)

    def handle_client_datagram(self, dgi: Any) -> None:
        """Dispatch incoming server messages.

        Handles all standard protocol messages.  Override individual
        ``_handle_*`` methods (or this method) for custom behaviour.
        """
        mt: int = self.msg_type
        if mt == NetMessages.SV_Hello_Resp:
            self._handle_hello_resp(dgi)
        elif mt == NetMessages.SV_InterestComplete:
            self._handle_interest_complete(dgi)
        elif mt == NetMessages.SV_Tick:
            self._handle_server_tick(dgi)
        elif mt == NetMessages.SV_GenerateObject:
            self._handle_generate_object(dgi)
        elif mt == NetMessages.SV_GenerateOwnerObject:
            self._handle_generate_owner_object(dgi)
        elif mt == NetMessages.SV_DisableObject:
            self._handle_disable_object(dgi)
        elif mt == NetMessages.SV_DeleteObject:
            self._handle_delete_object(dgi)
        elif mt == NetMessages.B_ObjectMessage:
            self._handle_object_message(dgi)
        elif mt == NetMessages.SV_Ping_Resp:
            self.handle_ping_response()
        else:
            self.notify.warning("Unknown message type %i" % mt)

    # -- standard message handlers -------------------------------------------

    def _handle_hello_resp(self, dgi: Any) -> None:
        accepted = bool(dgi.getUint8())
        if not accepted:
            reason = dgi.getString()
            self.notify.warning("Server rejected hello: %s" % reason)
            self.disconnect()
            return

        want_auth = dgi.getBool()
        if want_auth:
            self.notify.info("Server requires authentication")
            self.disconnect()
            return

        self.client_id = dgi.getUint16()
        self.server_tick_rate = dgi.getUint8()
        self.server_interval_per_tick = 1.0 / self.server_tick_rate
        self.server_tick_count = dgi.getUint32()
        self.is_authed = True

        self.net_clock.set_tick_rate(self.server_tick_rate)

        self.notify.info(
            "Authenticated client_id=%i tick_rate=%i" % (self.client_id, self.server_tick_rate)
        )
        runtime.messenger.send('helloResponse')

    def _handle_interest_complete(self, dgi: Any) -> None:
        handle: int = dgi.getUint8()
        runtime.messenger.send('interestComplete', [handle])

    def _handle_server_tick(self, dgi: Any) -> None:
        """Receive a tick snapshot from the server, ack it, and unpack."""
        if dgi.getRemainingSize() < 4:
            return

        tick_count: int = dgi.getUint32()
        self.server_tick_count = tick_count
        self.last_server_tick_time = self.net_clock.ticks_to_time(tick_count)

        is_delta: bool = bool(dgi.getUint8())

        # Let sub-classes read additional header data.
        self.read_snapshot_header_data(dgi)

        # Unpack the object state via the C++ fast-path.
        self.unpack_server_snapshot(dgi, is_delta)

        # Ack the tick so the server can delta-compress against it.
        dg = PyDatagram()
        dg.addUint16(NetMessages.CL_Tick)
        dg.addInt32(tick_count)
        dg.addFloat32(runtime.globalClock.dt)
        self.send_datagram(dg)

    def read_snapshot_header_data(self, dgi: Any) -> None:
        """Override to read custom data appended by
        ``ServerRepository.add_snapshot_header_data``."""

    def _handle_generate_object(self, dgi: Any) -> None:
        if dgi.getRemainingSize() < 8:
            return
        dclass_num: int = dgi.getUint16()
        do_id: int = dgi.getUint32()
        zone_id: int = dgi.getUint32()

        dclass = self.dclasses_by_number.get(dclass_num)
        if not dclass:
            self.notify.warning("Generate for unknown dclass %i" % dclass_num)
            return

        class_def = dclass.getClassDef()
        if not class_def:
            self.notify.warning("No class def for dclass %s" % dclass.getName())
            return

        do = class_def()
        do.dclass = dclass
        do.do_id = do_id
        do.zone_id = zone_id
        self.do_id_to_do[do_id] = do

        # Register with C++ repository so snapshots can unpack onto this object.
        self.add_object(do)

        has_baseline: int = dgi.getUint8()
        if has_baseline:
            self.unpack_object_state(dgi, do_id)

        self._unpack_required_fields(dgi, do)

        do.generate()
        do.announce_generate()
        self.notify.info(
            "Generated %s do_id=%i zone=%i" % (dclass.getName(), do_id, zone_id)
        )

    def _handle_generate_owner_object(self, dgi: Any) -> None:
        if dgi.getRemainingSize() < 8:
            return
        dclass_num: int = dgi.getUint16()
        do_id: int = dgi.getUint32()
        zone_id: int = dgi.getUint32()

        dclass = self.dclasses_by_number.get(dclass_num)
        if not dclass:
            self.notify.warning("Owner generate for unknown dclass %i" % dclass_num)
            return

        class_def = dclass.getOwnerClassDef()
        if class_def is None:
            class_def = dclass.getClassDef()
        if not class_def:
            self.notify.warning("No class def for dclass %s" % dclass.getName())
            return

        do = class_def()
        do.dclass = dclass
        do.do_id = do_id
        do.zone_id = zone_id
        do.is_owner = True
        self.do_id_to_do[do_id] = do

        self.add_object(do)

        has_baseline: int = dgi.getUint8()
        if has_baseline:
            self.unpack_object_state(dgi, do_id)

        self._unpack_required_fields(dgi, do)

        do.generate()
        do.announce_generate()
        self.notify.info(
            "Generated OWNER %s do_id=%i zone=%i" % (dclass.getName(), do_id, zone_id)
        )

    def _handle_disable_object(self, dgi: Any) -> None:
        if dgi.getRemainingSize() < 4:
            return
        do_id: int = dgi.getUint32()
        do = self.do_id_to_do.get(do_id)
        if do:
            self.remove_object(do_id)
            do.disable()

    def _handle_delete_object(self, dgi: Any) -> None:
        if dgi.getRemainingSize() < 4:
            return
        do_id: int = dgi.getUint32()
        do = self.do_id_to_do.pop(do_id, None)
        if do:
            self.remove_object(do_id)
            do.delete()

    def _handle_object_message(self, dgi: Any) -> None:
        if dgi.getRemainingSize() < 6:
            return
        do_id: int = dgi.getUint32()
        field_num: int = dgi.getUint16()

        do = self.do_id_to_do.get(do_id)
        if not do or not do.dclass:
            return

        field = do.dclass.getFieldByIndex(field_num)
        if not field:
            return

        if hasattr(do, 'pre_data_update'):
            do.pre_data_update()

        packer = DCPacker()
        packer.setUnpackData(dgi.getRemainingBytes())
        packer.beginUnpack(field)
        field.receiveUpdate(packer, do)
        packer.endUnpack()

        if hasattr(do, 'post_data_update'):
            do.post_data_update()

    def _unpack_required_fields(self, dgi: Any, do: Any) -> None:
        """Unpack ``required`` atomic fields appended after the baseline.

        These are fields that carry the ``required`` keyword but are not
        DC parameter fields, so they are not included in the baseline
        :class:`PackedObject`.  The server packs them separately in
        :meth:`ServerRepository._pack_required_fields`.
        """
        if dgi.getRemainingSize() < 2:
            return

        num_required: int = dgi.getUint16()
        for _ in range(num_required):
            if dgi.getRemainingSize() < 2:
                break
            field_index: int = dgi.getUint16()
            field = do.dclass.getInheritedField(field_index)
            if not field:
                self.notify.warning(
                    "Required field index %d not found on %s"
                    % (field_index, do.dclass.getName())
                )
                return

            packer = DCPacker()
            packer.setUnpackData(dgi.getRemainingBytes())
            packer.beginUnpack(field)
            field.receiveUpdate(packer, do)
            if not packer.endUnpack():
                self.notify.warning(
                    "Failed to unpack required field %s" % field.getName()
                )
                return
            dgi.skipBytes(packer.getNumUnpackedBytes())

    def run_callbacks(self) -> None:
        _drain_network_events(self.net_sys)
        remaining: list[_NetEvent] = []
        for event in _pending_network_events:
            if event.connection == self.connection_handle:
                self._handle_client_net_event(event)
            else:
                remaining.append(event)
        _pending_network_events[:] = remaining

    def _handle_client_net_event(self, event: Any) -> None:
        if event.state == SteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_Connected:
            self.notify.info("Connected to server")
            runtime.messenger.send('connectSuccess', [self.server_address])
        elif event.state in (
            SteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_ClosedByPeer,
            SteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_ProblemDetectedLocally,
        ):
            self.notify.info("Connection lost (state: %s)" % event.state)
            self.disconnect()
            runtime.messenger.send('connectionLost')

    def send_ping(self) -> None:
        """Issue a ping query to the server."""
        if self.pending_ping:
            return
        self.pending_ping = True

        self.ping_send_out_time = runtime.globalClock.real_time
        dg = PyDatagram()
        dg.addUint16(NetMessages.CL_Ping)
        self.send_datagram(dg)

    def handle_ping_response(self) -> None:
        if not self.pending_ping:
            return
        self.pending_ping = False
        now: float = runtime.globalClock.real_time
        self.ping_latency = max(0, int((now - self.ping_send_out_time) * 1000.0))
        if cl_report_ping.value:
            self.notify.info("Current ping: %i ms" % self.ping_latency)
        self.next_ping_time = now + cl_ping_interval.value

        dg = PyDatagram()
        dg.addUint16(NetMessages.CL_InformPing)
        dg.addUint32(self.ping_latency)
        self.send_datagram(dg)

    # -- frame loop -----------------------------------------------------------

    def run_frame(self, task: Any) -> Any:
        self.reader_poll_until_empty()
        self.run_callbacks()

        if self.connected and self.is_authed and cl_ping.value:
            if runtime.globalClock.real_time >= self.next_ping_time:
                self.send_ping()

        return task.cont

    def _interpolate_objects_task(self, task: Any) -> Any:
        DistributedObject.interpolate_objects()
        return task.cont

    def start_client_loop(self) -> None:
        runtime.base.taskMgr.add(self.run_frame, "clientRunFrame", sort=-100)
        runtime.base.taskMgr.add(self._interpolate_objects_task, "clientInterpolateObjects", sort=30)

    def stop_client_loop(self) -> None:
        runtime.base.taskMgr.remove("clientRunFrame")
        runtime.base.taskMgr.remove("clientSimObjects")
        runtime.base.taskMgr.remove("clientInterpolateObjects")

    # -- interest -------------------------------------------------------------

    def get_next_interest_handle(self) -> int:
        return (self.interest_handle + 1) % 256

    def set_update_rate(self, rate: int) -> None:
        """Change the rate at which we receive state snapshots from the server."""
        dg = PyDatagram()
        dg.addUint16(NetMessages.CL_SetUpdateRate)
        dg.addUint8(rate)
        self.send_datagram(dg)

    def set_cmd_rate(self, rate: int) -> None:
        """Change the rate at which we send commands to the server."""
        dg = PyDatagram()
        dg.addUint16(NetMessages.CL_SetCMDRate)
        dg.addUint8(rate)
        self.send_datagram(dg)

    def set_interest(self, interest_zones: list[int]) -> int:
        """Request the server to replace our interested zones with this list."""
        dg = PyDatagram()
        dg.addUint16(NetMessages.CL_SetInterest)
        handle = self.get_next_interest_handle()
        dg.addUint8(handle)
        dg.addUint8(len(interest_zones))
        for zone_id in interest_zones:
            dg.addUint32(zone_id)
        self.send_datagram(dg)
        return handle

    def remove_interest(self, interest_zones: list[int]) -> int:
        """Request the server to remove the specified zones from our interest."""
        dg = PyDatagram()
        dg.addUint16(NetMessages.CL_RemoveInterest)
        handle = self.get_next_interest_handle()
        dg.addUint8(handle)
        dg.addUint8(len(interest_zones))
        for zone_id in interest_zones:
            dg.addUint32(zone_id)
        self.send_datagram(dg)
        return handle

    def add_interest(self, interest_zones: list[int]) -> int:
        """Request the server to add the specified zones to our interest."""
        dg = PyDatagram()
        dg.addUint16(NetMessages.CL_AddInterest)
        handle = self.get_next_interest_handle()
        dg.addUint8(handle)
        dg.addUint8(len(interest_zones))
        for zone_id in interest_zones:
            dg.addUint32(zone_id)
        self.send_datagram(dg)
        return handle

    def send_hello(self, password: str = "") -> None:
        dg = PyDatagram()
        dg.addUint16(NetMessages.CL_Hello)
        dg.addString(password)
        dg.addUint32(self.hash_val)
        dg.addUint8(cl_updaterate.getValue())
        dg.addUint8(cl_cmdrate.getValue())
        dg.addFloat32(get_client_interp_amount())
        self.send_datagram(dg)

    def send_update(self, do: Any, name: str, args: list[Any]) -> None:
        """Pack and send a field update for *do* to the server."""
        if not do or not do.dclass:
            return

        field = do.dclass.getFieldByName(name)
        if not field:
            self.notify.warning("Tried to send unknown field %s" % name)
            return
        if field.asParameter():
            self.notify.warning("Can't send parameter field as a message")
            return

        packer = DCPacker()
        packer.rawPackUint16(NetMessages.B_ObjectMessage)
        packer.rawPackUint32(do.do_id)
        packer.rawPackUint16(field.getNumber())

        packer.beginPack(field)
        field.packArgs(packer, args)
        if not packer.endPack():
            self.notify.warning("Failed to pack message")
            return

        reliable: bool = not field.hasKeyword("unreliable")
        dg = PyDatagram(packer.getBytes())
        self.send_datagram(dg, reliable)


# --------------------------------------------------------------------------------


class ServerRepository(BaseObjectManager):
    """Server-side repository managing distributed objects and clients."""

    notify = directNotify.newCategory("ServerRepository")
    notify.setDebug(False)

    class Client:
        def __init__(self, connection: int, net_address: Any, id: int = -1) -> None:
            self.id: int = id
            self.connection: int = connection
            self.net_address: Any = net_address
            self.state: int = ClientState.Unverified
            self.update_rate: int = 0
            self.update_interval: float = 0
            self.next_update_time: float = 0.0
            self.cmd_rate: int = 0
            self.cmd_interval: float = 0

            self.current_rtt: int = 0
            self.average_rtt: float = 0
            self.rtt_window_size: int = 5
            self.rtt_sliding_window: list[int] = [0] * self.rtt_window_size

            self.interp_amount: float = 0.0

            self.prev_tick_count: int = 0
            self.dt: float = 0
            self.tick_remainder: float = 0
            self.tick_count: int = 0
            self.delta_tick: int = -1

            self.frame_mgr: ClientFrameManager = ClientFrameManager()

            self.last_snapshot: FrameSnapshot | None = None
            self.current_frame: ClientFrame | None = None

            self.objects_by_do_id: dict[int, Any] = {}
            self.objects_by_zone_id: dict[int, set[Any]] = {}
            self.explicit_interest_zone_ids: set[int] = set()
            self.current_interest_zone_ids: set[int] = set()

        def get_client_frame(self, tick: int) -> ClientFrame | None:
            return self.frame_mgr.get_client_frame(tick)

        def setup_pack_info(self, snapshot: FrameSnapshot) -> None:
            frame = ClientFrame(snapshot)
            max_frames: int = 128
            if max_frames < self.frame_mgr.add_client_frame(frame):
                self.frame_mgr.remove_oldest_frame()
            self.current_frame = frame

        def is_verified(self) -> bool:
            return self.state == ClientState.Verified and self.id != -1

    def __init__(self, listen_port: int) -> None:
        BaseObjectManager.__init__(self, False)
        self.dc_suffix = 'AI'

        self.client_sender: ServerRepository.Client | None = None

        self.net_clock: NetworkClock = NetworkClock.get_global_ptr()
        self.listen_port: int = listen_port
        self.net_sys = SteamNetworkManager.get_global_ptr()
        self._configure_networking()
        self.listen_socket = self.net_sys.create_ip_socket(listen_port)
        self.poll_group = self.net_sys.create_poll_group()
        self.client_id_allocator: UniqueIdAllocator = UniqueIdAllocator(0, 0xFFFF)
        self.object_id_allocator: UniqueIdAllocator = UniqueIdAllocator(0, 0xFFFF)
        self.num_clients: int = 0
        self.clients_by_connection: dict[int, ServerRepository.Client] = {}
        self.zones_to_clients: dict[int, set[ServerRepository.Client]] = {}

        self.snapshot_mgr: FrameSnapshotManager = FrameSnapshotManager()

        self.objects_by_zone_id: dict[int, list[Any]] = {}

        self.net_clock.set_tick_rate(sv_tickrate.getValue())
        runtime.base.taskMgr.add(self.run_frame, "serverRunFrame", sort=-100)
        runtime.base.taskMgr.add(self._take_snapshot_task, "serverTakeSnapshot", sort=100)

        runtime.base.sv = self
        runtime.base.server = self

    # -- helpers --------------------------------------------------------------

    def get_max_clients(self) -> int:
        return sv_max_clients.getValue()

    def allocate_object_id(self) -> int:
        return self.object_id_allocator.allocate()

    def free_object_id(self, id: int) -> None:
        self.object_id_allocator.free(id)

    def get_dclass(self, name: str) -> Any:
        return self.dclasses_by_name.get(name)

    # -- object lifecycle -----------------------------------------------------

    def generate_object(
        self,
        do: Any,
        zone_id: int,
        owner: ServerRepository.Client | None = None,
        announce: bool = True,
        dclass_name: str | None = None,
    ) -> None:
        do.zone_id = zone_id
        do.do_id = self.allocate_object_id()
        if not dclass_name:
            dclass_name = do.__class__.__name__
        do.dclass = self.dclasses_by_name.get(dclass_name)
        if not do.dclass:
            self.notify.error("Could not find DCClass for %s" % dclass_name)
        do.owner = owner
        self.do_id_to_do[do.do_id] = do
        self.objects_by_zone_id.setdefault(do.zone_id, []).append(do)
        if owner:
            owner.objects_by_do_id[do.do_id] = do
            owner.objects_by_zone_id.setdefault(do.zone_id, set()).add(do)

        self.snapshot_mgr.add_object(do)

        do.generate()
        assert do.is_do_generated()

        clients = set(self.zones_to_clients.get(do.zone_id, set()))
        if owner and clients:
            clients -= {owner}

        if clients:
            dg = PyDatagram()
            dg.addUint16(NetMessages.SV_GenerateObject)
            self._pack_object_generate(dg, do)
            for client in clients:
                self.send_datagram(dg, client.connection)

        if owner:
            dg = PyDatagram()
            dg.addUint16(NetMessages.SV_GenerateOwnerObject)
            self._pack_object_generate(dg, do)
            self.send_datagram(dg, owner.connection)

            self._update_client_interest_zones(owner)

        if announce:
            do.announce_generate()
            assert do.is_do_alive()

    def delete_object(self, do: Any, remove_from_owner_table: bool = True) -> None:
        if do.is_do_deleted():
            assert do.do_id not in self.do_id_to_do
            return

        assert do.do_id in self.do_id_to_do

        saved_do_id: int = do.do_id

        del self.do_id_to_do[do.do_id]
        self.objects_by_zone_id[do.zone_id].remove(do)
        if not self.objects_by_zone_id[do.zone_id]:
            del self.objects_by_zone_id[do.zone_id]

        if remove_from_owner_table and (do.owner is not None):
            client = do.owner
            client.objects_by_zone_id[do.zone_id].remove(do)
            if not client.objects_by_zone_id[do.zone_id]:
                del client.objects_by_zone_id[do.zone_id]
            del client.objects_by_do_id[do.do_id]

        clients = self.zones_to_clients.get(do.zone_id, set())
        if len(clients) > 0:
            dg = PyDatagram()
            dg.addUint16(NetMessages.SV_DeleteObject)
            dg.addUint32(do.do_id)
            for client in clients:
                self.send_datagram(dg, client.connection)

        self.snapshot_mgr.remove_prev_sent_packet(do.do_id)
        self.snapshot_mgr.remove_object(do.do_id)

        do.delete()
        assert do.is_do_deleted()

        self.free_object_id(saved_do_id)

    # -- frame loop -----------------------------------------------------------

    def run_frame(self, task: Any) -> Any:
        self.reader_poll_until_empty()
        self.run_callbacks()
        return task.cont

    def _client_needs_update(self, client: ServerRepository.Client) -> bool:
        return client.is_verified() and client.next_update_time <= self.net_clock.get_time()

    # -- snapshots ------------------------------------------------------------

    def _take_snapshot_task(self, task: Any) -> Any:
        self._take_tick_snapshot(self.net_clock.get_tick_count())
        return task.cont

    def _take_tick_snapshot(self, tick_count: int) -> None:
        self.notify.debug("Take tick snapshot at tick %i" % tick_count)
        snap = FrameSnapshot(tick_count, len(self.do_id_to_do))

        clients_needing_snapshots: list[ServerRepository.Client] = []
        client_zones: set[int] = set()
        for _, client in self.clients_by_connection.items():
            if self._client_needs_update(client):
                client_zones |= client.current_interest_zone_ids
                client.next_update_time = self.net_clock.get_time() + client.update_interval
                client.setup_pack_info(snap)
                clients_needing_snapshots.append(client)

        if not clients_needing_snapshots:
            self.notify.debug("Punting, no clients need snapshot")
            return

        self.notify.debug("All unique client interest zones: %s" % repr(client_zones))

        items = list(self.do_id_to_do.items())
        for i in range(len(items)):
            do_id, do = items[i]
            if do.zone_id not in client_zones:
                continue
            self.snapshot_mgr.pack_object_in_snapshot(snap, i, do, do_id, do.zone_id, do.dclass)

        for client in clients_needing_snapshots:
            old_frame = client.get_client_frame(client.delta_tick)
            client.last_snapshot = snap

            dg = PyDatagram()
            dg.addUint16(NetMessages.SV_Tick)
            self.add_snapshot_header_data(dg, client)
            if old_frame:
                self.snapshot_mgr.client_format_delta_snapshot(
                    dg, old_frame.get_snapshot(), snap,
                    list(client.current_interest_zone_ids),
                )
            else:
                self.snapshot_mgr.client_format_snapshot(
                    dg, snap, list(client.current_interest_zone_ids),
                )
            self.send_datagram(dg, client.connection)

    def add_snapshot_header_data(self, dg: PyDatagram, client: ServerRepository.Client) -> None:
        """Override to append show-specific data to the snapshot header."""

    def is_full(self) -> bool:
        return self.num_clients >= sv_max_clients.getValue()

    def can_accept_connection(self) -> bool:
        return True

    def _configure_networking(self) -> None:
        SteamNetworkingUtilsAPI.set_global_config_value_int32(
            SteamNetworkingConfigValue.k_ESteamNetworkingConfig_IP_AllowWithoutAuth, 1,
        )
        SteamNetworkingUtilsAPI.set_global_config_value_int32(
            SteamNetworkingConfigValue.k_ESteamNetworkingConfig_IPLocalHost_AllowWithoutAuth, 1,
        )

    # -- network I/O ----------------------------------------------------------

    def run_callbacks(self) -> None:
        _drain_network_events(self.net_sys)
        remaining: list[_NetEvent] = []
        for event in _pending_network_events:
            if event.connection not in _client_owned_connections:
                self.__handle_net_callback(event.connection, event.state, event.old_state)
            else:
                remaining.append(event)
        _pending_network_events[:] = remaining

    def reader_poll_until_empty(self) -> None:
        while self._reader_poll_once():
            pass

    def _reader_poll_once(self) -> bool:
        msg = SteamNetworkMessage()
        if self.net_sys.receive_message_on_poll_group(self.poll_group, msg):
            self._handle_datagram(msg)
            return True
        return False

    def _ensure_datagram_size(self, n: int, dgi: Any, client: ServerRepository.Client) -> bool:
        if dgi.getRemainingSize() < n:
            self.notify.warning("Truncated message from client %i" % client.connection)
            self.close_client_connection(client)
            return False
        return True

    def _handle_datagram(self, msg: SteamNetworkMessage) -> None:
        connection = msg.connection
        dgi = msg.dgi
        client = self.clients_by_connection.get(connection)

        if not client:
            self.notify.warning("SECURITY: received message from unknown source %i" % connection)
            return

        if not self._ensure_datagram_size(2, dgi, client):
            return
        msg_type: int = dgi.getUint16()

        self.client_sender = client

        if client.state == ClientState.Unverified:
            if msg_type == NetMessages.CL_Hello:
                self._handle_client_hello(client, dgi)
            else:
                self.notify.warning(
                    "SUSPICIOUS: client %i sent unknown message %i in unverified state"
                    % (client.connection, msg_type)
                )
                self.close_client_connection(client)

        elif client.state == ClientState.Authenticating:
            if msg_type == NetMessages.CL_AuthenticateResponse:
                self._handle_client_auth_response(client, dgi)
            else:
                self.notify.warning(
                    "SUSPICIOUS: client %i sent unknown message %i in in-verify state"
                    % (client.connection, msg_type)
                )
                self.close_client_connection(client)

        elif client.state == ClientState.Verified:
            if msg_type == NetMessages.CL_SetCMDRate:
                self._handle_client_set_cmd_rate(client, dgi)
            elif msg_type == NetMessages.CL_SetUpdateRate:
                self._handle_client_set_update_rate(client, dgi)
            elif msg_type == NetMessages.CL_Disconnect:
                self._handle_client_disconnect(client)
            elif msg_type == NetMessages.CL_Tick:
                self._handle_client_tick(client, dgi)
            elif msg_type == NetMessages.CL_AddInterest:
                self._handle_client_add_interest(client, dgi)
            elif msg_type == NetMessages.CL_RemoveInterest:
                self._handle_client_remove_interest(client, dgi)
            elif msg_type == NetMessages.CL_SetInterest:
                self._handle_client_set_interest(client, dgi)
            elif msg_type == NetMessages.B_ObjectMessage:
                self._handle_object_message(client, dgi)
            elif msg_type == NetMessages.CL_Ping:
                self._handle_client_ping(client)
            elif msg_type == NetMessages.CL_InformPing:
                self._handle_client_inform_ping(client, dgi)
            else:
                self.notify.warning(
                    "SUSPICIOUS: client %i sent unknown message %i in verified state"
                    % (client.connection, msg_type)
                )
                self.close_client_connection(client)

    # -- message handlers -----------------------------------------------------

    def _handle_client_ping(self, client: ServerRepository.Client) -> None:
        dg = PyDatagram()
        dg.addUint16(NetMessages.SV_Ping_Resp)
        self.send_datagram(dg, client.connection)

    def _handle_client_inform_ping(self, client: ServerRepository.Client, dgi: Any) -> None:
        rtt: int = dgi.getUint32()
        client.current_rtt = rtt
        if client.average_rtt == 0:
            client.rtt_sliding_window = [rtt] * client.rtt_window_size
        else:
            client.rtt_sliding_window = [rtt] + client.rtt_sliding_window[:client.rtt_window_size - 1]
        total: int = 0
        for r in client.rtt_sliding_window:
            total += r
        client.average_rtt = total / client.rtt_window_size
        assert self.notify.debug(
            "Client " + str(client.connection) + " average RTT: " + str(client.average_rtt)
        )

    def send_update(
        self,
        do: Any,
        name: str,
        args: list[Any],
        client: ServerRepository.Client | None = None,
        exclude_clients: list[ServerRepository.Client] | None = None,
    ) -> None:
        if exclude_clients is None:
            exclude_clients = []
        if not do:
            return
        if not do.dclass:
            return

        field = do.dclass.getFieldByName(name)
        if not field:
            self.notify.warning("Tried to send unknown field %s" % name)
            return
        if field.asParameter():
            self.notify.warning("Can't sent parameter field as a message")
            return

        packer = DCPacker()
        packer.rawPackUint16(NetMessages.B_ObjectMessage)
        packer.rawPackUint32(do.do_id)
        packer.rawPackUint16(field.getNumber())

        packer.beginPack(field)
        field.packArgs(packer, args)
        if not packer.endPack():
            self.notify.warning("Failed to pack message")
            return

        reliable: bool = not field.hasKeyword("unreliable")

        dg = PyDatagram(packer.getBytes())
        if not client:
            if field.isBroadcast():
                for cl in self.zones_to_clients.get(do.zone_id, set()):
                    if cl in exclude_clients:
                        continue
                    self.send_datagram(dg, cl.connection, reliable)
            elif field.isOwnrecv():
                if not do.owner:
                    self.notify.warning(
                        "Can't implicitly send ownrecv message to owner with no owner client"
                    )
                    return
                self.send_datagram(dg, do.owner.connection, reliable)
            else:
                self.notify.warning(
                    "Can't send non-broadcast and non-ownrecv object message without a target client"
                )
                return
        else:
            self.send_datagram(dg, client.connection, reliable)

    def _handle_object_message(self, client: ServerRepository.Client, dgi: Any) -> None:
        """Receive and validate an object message from a client."""

        if not self._ensure_datagram_size(6, dgi, client):
            return

        do_id: int = dgi.getUint32()

        do = self.do_id_to_do.get(do_id)
        if not do:
            self.notify.warning(
                "SUSPICIOUS: client %i tried to send message to unknown do_id %i"
                % (client.id, do_id)
            )
            return

        if not do.dclass:
            return

        if do.zone_id not in client.current_interest_zone_ids:
            self.notify.warning(
                "SUSPICIOUS: client %i tried to send message to an object "
                "whose zone ID is not in the client interest zones." % client.id
            )
            return

        field_number: int = dgi.getUint16()
        field = do.dclass.getFieldByIndex(field_number)
        if not field:
            self.notify.warning(
                "SUSPICIOUS: client %i tried to send message on unknown field %i on do_id %i"
                % (client.id, field_number, do_id)
            )
            return

        if field.asParameter():
            self.notify.warning(
                "SUSPICIOUS: client %i tried to send message on a parameter field!" % client.id
            )
            return

        if do.owner != client:
            if not field.isClsend():
                self.notify.warning(
                    "SUSPICIOUS: client %i tried to send non-clsend message on do_id %i"
                    % (client.id, do_id)
                )
                return
        else:
            if not field.isOwnsend() and not field.isClsend():
                self.notify.warning(
                    "SUSPICIOUS: owner client %i tried to send non-ownsend and non-clsend message on do_id %i"
                    % (client.id, do_id)
                )
                return

        packer = DCPacker()
        packer.setUnpackData(dgi.getRemainingBytes())
        packer.beginUnpack(field)
        field.receiveUpdate(packer, do)
        if not packer.endUnpack():
            self.notify.warning("Failed to unpack object message")

    def is_valid_client_interest(self, zone: int) -> bool:
        return True

    def add_explicit_interest(self, client: ServerRepository.Client, zones: Any) -> None:
        if not isinstance(zones, (tuple, list)):
            zones = tuple(zones)
        for zone_id in zones:
            client.explicit_interest_zone_ids.add(zone_id)
        self._update_client_interest_zones(client)

    def _handle_client_add_interest(self, client: ServerRepository.Client, dgi: Any) -> None:
        if not self._ensure_datagram_size(2, dgi, client):
            return
        handle: int = dgi.getUint8()
        num_zones: int = dgi.getUint8()

        zones: list[int] = []
        i = 0
        while i < num_zones and dgi.getRemainingSize() >= 4:
            zone_id: int = dgi.getUint32()
            if not self.is_valid_client_interest(zone_id):
                self.close_client_connection(client)
                return
            zones.append(zone_id)
            i += 1

        self.add_explicit_interest(client, zones)
        self._send_interest_complete(client, handle)

    def _handle_client_remove_interest(self, client: ServerRepository.Client, dgi: Any) -> None:
        if not self._ensure_datagram_size(2, dgi, client):
            return
        handle: int = dgi.getUint8()
        num_zones: int = dgi.getUint8()

        i = 0
        while i < num_zones and dgi.getRemainingSize() >= 4:
            zone_id: int = dgi.getUint32()
            if zone_id in client.explicit_interest_zone_ids:
                client.explicit_interest_zone_ids.remove(zone_id)
            i += 1

        self._update_client_interest_zones(client)
        self._send_interest_complete(client, handle)

    def _handle_client_set_interest(self, client: ServerRepository.Client, dgi: Any) -> None:
        if not self._ensure_datagram_size(2, dgi, client):
            return

        client.explicit_interest_zone_ids = set()

        handle: int = dgi.getUint8()
        num_zones: int = dgi.getUint8()

        i = 0
        while i < num_zones and dgi.getRemainingSize() >= 4:
            zone_id: int = dgi.getUint32()
            client.explicit_interest_zone_ids.add(zone_id)
            i += 1

        self._update_client_interest_zones(client)
        self._send_interest_complete(client, handle)

    def _pack_object_generate(self, dg: PyDatagram, obj: Any) -> None:
        dg.addUint16(obj.dclass.getNumber())
        dg.addUint32(obj.do_id)
        dg.addUint32(obj.zone_id)

        assert self.notify.debug("Packing generate for " + repr(obj))

        baseline = self.snapshot_mgr.find_or_create_object_packet_for_baseline(
            obj, obj.dclass, obj.do_id,
        )
        if baseline:
            dg.addUint8(1)
            baseline.pack_datagram(dg)
        else:
            dg.addUint8(0)

        self._pack_required_fields(dg, obj)

    def _get_required_field_value(
        self, obj: Any, field: Any,
    ) -> list[Any] | None:
        """Return the value of a required atomic field from *obj*.

        Uses the traditional DC getter convention (``setFoo`` -> ``getFoo``),
        falling back to a direct attribute lookup.
        """
        name: str = field.getName()
        if name.startswith('set'):
            getter_name = 'g' + name[1:]
        else:
            getter_name = 'get' + name[0].upper() + name[1:]

        getter = getattr(obj, getter_name, None)
        if getter is not None and callable(getter):
            result = getter()
            if not isinstance(result, (tuple, list)):
                result = (result,)
            return list(result)

        val = getattr(obj, name, None)
        if val is not None and not callable(val):
            if not isinstance(val, (tuple, list)):
                val = (val,)
            return list(val)

        return None

    def _pack_required_fields(self, dg: PyDatagram, obj: Any) -> None:
        """Pack ``required`` atomic fields that are not in the baseline.

        Parameter fields are already encoded in the baseline
        :class:`PackedObject`.  This packs any remaining atomic fields
        that carry the ``required`` keyword so the client receives their
        initial values in the generate message.
        """
        packed: list[tuple[int, bytes]] = []
        dclass = obj.dclass
        for i in range(dclass.getNumInheritedFields()):
            field = dclass.getInheritedField(i)
            if field.asParameter():
                continue  # already in baseline
            if not field.hasKeyword("required"):
                continue

            args = self._get_required_field_value(obj, field)
            packer = DCPacker()
            packer.beginPack(field)
            if args is not None:
                field.packArgs(packer, args)
            else:
                packer.packDefaultValue()
            if not packer.endPack():
                self.notify.warning(
                    "Failed to pack required field %s on %s"
                    % (field.getName(), repr(obj))
                )
                continue
            packed.append((i, packer.getBytes()))

        dg.addUint16(len(packed))
        for field_index, data in packed:
            dg.addUint16(field_index)
            dg.appendData(data)

    def _update_client_interest_zones(self, client: ServerRepository.Client) -> None:
        orig_zone_ids = client.current_interest_zone_ids
        new_zone_ids = client.explicit_interest_zone_ids | set(client.objects_by_zone_id.keys())
        if orig_zone_ids == new_zone_ids:
            return

        client.current_interest_zone_ids = new_zone_ids
        added_zone_ids = new_zone_ids - orig_zone_ids
        removed_zone_ids = orig_zone_ids - new_zone_ids

        for zone_id in added_zone_ids:
            self.zones_to_clients.setdefault(zone_id, set()).add(client)

            for obj in self.objects_by_zone_id.get(zone_id, []):
                if obj.owner != client:
                    dg = PyDatagram()
                    dg.addUint16(NetMessages.SV_GenerateObject)
                    self._pack_object_generate(dg, obj)
                    self.send_datagram(dg, client.connection)

        for zone_id in removed_zone_ids:
            self.zones_to_clients[zone_id].remove(client)
            for obj in self.objects_by_zone_id.get(zone_id, []):
                if obj.owner != client:
                    dg = PyDatagram()
                    dg.addUint16(NetMessages.SV_DeleteObject)
                    dg.addUint32(obj.do_id)
                    self.send_datagram(dg, client.connection)

    def _send_interest_complete(self, client: ServerRepository.Client, handle: int) -> None:
        dg = PyDatagram()
        dg.addUint16(NetMessages.SV_InterestComplete)
        dg.addUint8(handle)
        self.send_datagram(dg, client.connection)

    def send_datagram(self, dg: PyDatagram, connection: int, reliable: bool = True) -> None:
        if reliable:
            send_type = SteamConstants.k_nSteamNetworkingSend_ReliableNoNagle
        else:
            send_type = SteamConstants.k_nSteamNetworkingSend_UnreliableNoDelay
        self.net_sys.send_datagram(connection, dg, send_type)

    def close_client_connection(self, client: ServerRepository.Client) -> None:
        if client.id != -1:
            self.client_id_allocator.free(client.id)
        if client.state == ClientState.Verified:
            self.num_clients -= 1
        self.net_sys.close_connection(client.connection)
        del self.clients_by_connection[client.connection]

    def _handle_client_tick(self, client: ServerRepository.Client, dgi: Any) -> None:
        if not self._ensure_datagram_size(8, dgi, client):
            return
        client.prev_tick_count = int(client.tick_count)
        client.delta_tick = dgi.getInt32()
        client.dt = dgi.getFloat32()
        self.notify.debug("Client acknowledged tick %i" % client.delta_tick)

    def _handle_client_set_cmd_rate(self, client: ServerRepository.Client, dgi: Any) -> None:
        if not self._ensure_datagram_size(1, dgi, client):
            return
        cmd_rate: int = dgi.getUint8()
        client.cmd_rate = cmd_rate
        client.cmd_interval = 1.0 / cmd_rate

    def _handle_client_set_update_rate(self, client: ServerRepository.Client, dgi: Any) -> None:
        if not self._ensure_datagram_size(1, dgi, client):
            return
        update_rate: int = dgi.getUint8()
        update_rate = max(sv_minupdaterate.getValue(), min(update_rate, sv_maxupdaterate.getValue()))
        client.update_rate = update_rate
        client.update_interval = 1.0 / update_rate

    def _handle_client_hello(self, client: ServerRepository.Client, dgi: Any) -> None:
        if not self._ensure_datagram_size(2, dgi, client):
            return
        password: str = dgi.getString()

        if not self._ensure_datagram_size(10, dgi, client):
            return
        dc_hash: int = dgi.getUint32()
        update_rate: int = dgi.getUint8()
        cmd_rate: int = dgi.getUint8()
        interp_amount: float = dgi.getFloat32()

        dg = PyDatagram()
        dg.addUint16(NetMessages.SV_Hello_Resp)

        valid: bool = True
        msg: str = ""
        if self.is_full():
            valid = False
            msg = "Server is full"
        elif password != sv_password.getValue():
            valid = False
            msg = "Incorrect password"
        elif dc_hash != self.hash_val:
            valid = False
            msg = "DC hash mismatch"
        elif client.state == ClientState.Verified:
            valid = False
            msg = "Already signed in"

        dg.addUint8(int(valid))
        if not valid:
            self.notify.warning("Could not verify client %i (%s)" % (client.connection, msg))
            dg.addString(msg)
            self.send_datagram(dg, client.connection)
            self.close_client_connection(client)
            return

        update_rate = max(sv_minupdaterate.getValue(), min(update_rate, sv_maxupdaterate.getValue()))
        client.update_rate = update_rate
        client.update_interval = 1.0 / update_rate
        client.interp_amount = interp_amount

        client.cmd_rate = cmd_rate
        client.cmd_interval = 1.0 / cmd_rate

        if not self.want_authentication():
            client.state = ClientState.Verified
            client.id = self.client_id_allocator.allocate()

            self.notify.info(
                "Got hello from client %i, verified, given ID %i" % (client.connection, client.id)
            )
            self.notify.info("Client lerp time: " + str(interp_amount))

            dg.addBool(False)
            dg.addUint16(client.id)
            dg.addUint8(self.net_clock.get_tick_rate())
            dg.addUint32(self.net_clock.get_tick_count())

            self.num_clients += 1

            self.send_datagram(dg, client.connection)

            runtime.messenger.send('clientConnected', [client])
        else:
            dg.addBool(True)
            self.send_datagram(dg, client.connection)

            client.state = ClientState.Authenticating
            self._send_client_auth_request(client)

    def want_authentication(self) -> bool:
        return False

    def _send_client_auth_request(self, client: ServerRepository.Client) -> None:
        raise NotImplementedError

    def _handle_client_auth_response(self, client: ServerRepository.Client, dgi: Any) -> None:
        raise NotImplementedError

    def _handle_client_disconnect(self, client: ServerRepository.Client) -> None:
        for do in client.objects_by_do_id.values():
            self.delete_object(do, False)
        client.objects_by_do_id = {}
        client.objects_by_zone_id = {}
        runtime.messenger.send('clientDisconnected', [client])
        self.close_client_connection(client)

    def __handle_net_callback(self, connection: int, state: int, old_state: int) -> None:
        if state == SteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_Connecting:
            if not self.can_accept_connection():
                return
            self.net_sys.accept_connection(connection)
            self.net_sys.set_connection_poll_group(connection, self.poll_group)
            info = SteamNetworkConnectionInfo()
            self.net_sys.get_connection_info(connection, info)
            self.handle_new_connection(connection, info)

        elif state in (
            SteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_ClosedByPeer,
            SteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_ProblemDetectedLocally,
        ):
            client = self.clients_by_connection.get(connection)
            if not client:
                self.notify.info(
                    "Connection %i disconnected but wasn't a recorded client, ignoring " % connection
                )
                return
            self.notify.info("Client %i disconnected" % client.connection)
            self._handle_client_disconnect(client)

    def handle_new_connection(self, connection: int, info: SteamNetworkConnectionInfo) -> None:
        self.notify.info(
            "Got client from %s (connection %i), awaiting hello"
            % (info.get_net_address(), connection)
        )
        client = ServerRepository.Client(connection, info.get_net_address())
        self.clients_by_connection[connection] = client
