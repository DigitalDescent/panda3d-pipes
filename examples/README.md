# panda3d-pipes Example

Basic client/server demo using `panda3d-pipes` and `panda3d-steamworks`.

## Prerequisites

- **Panda3D 1.11.0+** installed  
- **panda3d-pipes** built (`python setup.py build` from the repo root)  
- **panda3d-steamworks** installed  
- **Steam client** running (required for Steam networking sockets)

## Files

| File | Description |
|------|-------------|
| `example.dc` | DC (distributed class) definitions for chat and avatar objects |
| `objects.py` | Client and server DO classes (`DistributedChat`, `DistributedAvatar`, and their AI counterparts) |
| `server.py` | Headless server — listens on port 27015, spawns avatars for connecting clients |
| `client.py` | Headless client — connects to the server, sends a chat message, moves its avatar |

## Running

Open two terminals in the **repository root** directory:

**Terminal 1 — Server:**
```
python examples/server.py
```

**Terminal 2 — Client:**
```
python examples/client.py
```

The server will log client connections, chat messages, and avatar movement. The client will send a hello, request interest in zone 1, send a chat message after 1 second, and move its avatar every 2 seconds.

## Configuration

Server-side PRC variables (set in `server.py` or a PRC file):
- `pipes-tickrate` — simulation tick rate (default 30)
- `pipes-port` — listen port (default 27015)
- `pipes-max-clients` — max concurrent clients (default 8)
- `pipes-password` — optional server password

Client-side PRC variables:
- `pipes-updaterate` — requested snapshot rate from server
- `pipes-cmdrate` — command send rate
- `pipes-interp` / `pipes-interp-ratio` — interpolation settings
