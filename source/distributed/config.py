from __future__ import annotations

from panda3d.core import (
    ConfigVariableBool,
    ConfigVariableDouble,
    ConfigVariableInt,
    ConfigVariableString,
)

# --------------------------------------------------------------------------------
# Client-side configuration variables for interpolation and pinging.

cl_cmdrate: ConfigVariableInt = ConfigVariableInt("cl_cmdrate", 100)
cl_updaterate: ConfigVariableInt = ConfigVariableInt("cl_updaterate", 20)
cl_interp: ConfigVariableDouble = ConfigVariableDouble("cl_interp", 0.1)
cl_interp_ratio: ConfigVariableDouble = ConfigVariableDouble("cl_interp_ratio", 2)
# Should we ping the server every so often to measure latency?
cl_ping: ConfigVariableBool = ConfigVariableBool("cl_ping", True)
# How often we ping the server to measure latency.
cl_ping_interval: ConfigVariableDouble = ConfigVariableDouble("cl_ping_interval", 0.5)
# Should we print the latest ping measurement to console?
cl_report_ping: ConfigVariableBool = ConfigVariableBool("cl_report_ping", False)


def get_client_interp_amount() -> float:
    """Return the client-side interpolation amount in seconds."""
    return max(
        cl_interp.getValue(),
        cl_interp_ratio.getValue() / float(cl_updaterate.getValue()),
    )


# Keep old name as an alias for backwards compatibility.
getClientInterpAmount = get_client_interp_amount

# --------------------------------------------------------------------------------
# Server-side configuration variables for update rate and interpolation.

sv_max_clients: ConfigVariableInt = ConfigVariableInt("sv_max_clients", 24)
sv_password: ConfigVariableString = ConfigVariableString("sv_password", "")
sv_minupdaterate: ConfigVariableInt = ConfigVariableInt("sv_minupdaterate", 1)
sv_maxupdaterate: ConfigVariableInt = ConfigVariableInt("sv_maxupdaterate", 255)
sv_tickrate: ConfigVariableInt = ConfigVariableInt("sv_tickrate", 66)

# How many past snapshots do we save?
sv_snapshot_history: ConfigVariableInt = ConfigVariableInt("sv_snapshot_history", 50)
sv_port: ConfigVariableInt = ConfigVariableInt("sv_port", 27015)
sv_alternateticks: ConfigVariableBool = ConfigVariableBool("sv_alternateticks", False)
sv_clockcorrection_msecs: ConfigVariableDouble = ConfigVariableDouble("sv_clockcorrection_msecs", 60)
