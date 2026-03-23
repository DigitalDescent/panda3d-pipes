# Panda3D Pipes

> "The internet is a series of pipes"
> — Some guy, probably.

**NOT PRODUCTION READY. HEAVILY EXPERIMENTAL**

A networked distributed-object framework for [Panda3D](https://www.panda3d.org/) built on top of Steam networking sockets. It provides authoritative server snapshots with delta compression, client-side interpolation, zone-based interest management, and a DC (distributed class) schema for defining replicated object fields — all driven by a tick-based simulation loop.

> The original foundation of Panda3D pipes is based on the work of Brian Lach from the Panda3D player project.

## Features

- **Snapshot replication** — The server captures the state of every distributed object each tick and sends delta-compressed snapshots to clients. Only changed fields are transmitted.
- **Client-side interpolation** — Templated C++ `InterpolatedVariable` types (float, Vec2/3/4, Quaternion) record value history and interpolate smoothly between received snapshots using linear or Hermite curves, with configurable extrapolation.
- **Zone-based interest** — Clients subscribe to zones; the server only sends object data for zones a client cares about.
- **DC schema** — Shared `.dc` files define the replicated fields, ownership rules (`ownsend`, `clsend`), and broadcast behaviour for each distributed class.
- **Distributed object lifecycle** — Objects follow a well-defined lifecycle: `Fresh → Generated → Alive → Disabled → Deleted`, with separate client, server (AI), and owner views.
- **Clock drift correction** — A drift manager keeps the client simulation clock aligned to the server tick using sliding-window offset averaging and configurable correction thresholds.
- **Ping / RTT tracking** — Built-in ping protocol with a sliding-window average; per-client latency is available on both the server and client.
- **Per-client rate control** — Update rate, command rate, and interpolation amount are individually negotiable per client.
- **C++ performance core** — Snapshot packing, field unpacking (`CClientRepository`), frame management, packed objects, and math utilities are implemented in C++ and exposed to Python via Panda3D's interrogate system.
- **Steam networking transport** — Uses Valve's `SteamNetworkingSockets` for reliable/unreliable messaging, NAT traversal, and optional Steam authentication.

## Dependencies

- [Panda3D](https://www.panda3d.org/) 1.10.14+
- [panda3d-steamworks](https://github.com/DigitalDescent/panda3d-steamworks) — Python/C++ bindings for Steamworks networking
- [panda3d-toolbox](https://github.com/DigitalDescent/panda3d-toolbox) — Runtime helpers used by the framework
- **Steam client** running (required for Steam networking sockets)
- CMake 3.16+, a C++ compiler, and Python 3.10+

## Building

```bash
pip install .
```

This invokes the CMake / interrogate pipeline via setuptools to compile the C++ extension module (`panda3d_pipes`).

Set `SETUPTOOLS_SCM_PRETEND_VERSION` to control the wheel version if building outside of CI.

## Quick Start

See the [examples/](examples/) directory for a minimal client/server demo. In two terminals from the repository root:

```bash
# Terminal 1 — start the server
python examples/server.py

# Terminal 2 — connect a client
python examples/client.py
```

The server listens on port 27015, spawns avatars for connecting clients, and relays chat messages. The client connects, sends a greeting, and periodically moves its avatar.

## Configuration

Configuration is done through Panda3D PRC variables. Key defaults:

| Variable | Default | Description |
|---|---|---|
| `pipes-tickrate` | 66 | Simulation tick rate (Hz) |
| `pipes-maxupdaterate` | 255 | Max snapshot send rate per client |
| `pipes-minupdaterate` | 1 | Min snapshot send rate per client |
| `pipes-max-clients` | 24 | Maximum concurrent clients |
| `pipes-snapshot-history` | 50 | Snapshots retained for delta compression |
| `pipes-password` | *empty* | Optional server password |
| `pipes-updaterate` | 20 | Desired snapshot receive rate |
| `pipes-cmdrate` | 100 | Command send rate |
| `pipes-interp` | 0.1 | Interpolation buffer (seconds) |
| `pipes-interp-ratio` | 2 | Ratio applied to update rate for interp |
| `pipes-ping-interval` | 0.5 | Ping measurement interval (seconds) |

The effective interpolation delay is `max(pipes-interp, pipes-interp-ratio / pipes-updaterate)`.

## License

This project is licensed under the BSD 3-Clause License — see [LICENSE](LICENSE) for details.

The Steamworks SDK is Copyright © Valve Corporation and is subject to the rules outlined at [Distributing Open Source](https://partner.steamgames.com/doc/sdk/uploading/distributing_opensource).