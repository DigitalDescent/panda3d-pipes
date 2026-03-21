from __future__ import annotations

from panda3d.core import ConfigVariableBool, ConfigVariableInt
from panda3d_toolbox import runtime

cl_clock_correction: ConfigVariableBool = ConfigVariableBool("cl-clock-correction", True)
cl_clockdrift_max_ms: ConfigVariableInt = ConfigVariableInt("cl-clock-drift-max-ms", 150)
cl_clock_show_debug_info: ConfigVariableBool = ConfigVariableBool("cl-clock-show-debug-info", False)
cl_clock_correction_force_server_tick: ConfigVariableInt = ConfigVariableInt("cl-clock-correction-force-server-tick", 999)
cl_clock_correction_adjustment_max_amount: ConfigVariableInt = ConfigVariableInt("cl-clock-correction-adjustment-max-amount", 200)
cl_clock_correction_adjustment_min_offset: ConfigVariableInt = ConfigVariableInt("cl-clock-correction-adjustment-min-offset", 10)
cl_clock_correction_adjustment_max_offset: ConfigVariableInt = ConfigVariableInt("cl-clock-correction-adjustment-max-offset", 90)


class ClockDriftManager:

    def __init__(self) -> None:
        self.clear()

    def remap_val(self, val: float, a: float, b: float, c: float, d: float) -> float:
        if a == b:
            return d if val >= b else c
        return c + (d - c) * (val - a) / (b - a)

    def get_current_clock_difference(self) -> float:
        total: float = 0.0
        for i in range(16):
            total += self.clock_offsets[i]
        return total / 16

    def get_clock_adjustment_amount(self, curr_diff_in_ms: float) -> float:
        curr_diff_in_ms = max(
            cl_clock_correction_adjustment_min_offset.getValue(),
            min(cl_clock_correction_adjustment_max_offset.getValue(), curr_diff_in_ms),
        )
        return self.remap_val(
            curr_diff_in_ms,
            cl_clock_correction_adjustment_min_offset.getValue(),
            cl_clock_correction_adjustment_max_offset.getValue(),
            0,
            cl_clock_correction_adjustment_max_amount.getValue() / 1000.0,
        )

    def set_server_tick(self, tick: int) -> None:
        self.server_tick = tick
        max_drift_ticks: int = runtime.base.timeToTicks(cl_clockdrift_max_ms.getValue() / 1000.0)

        client_tick: int = runtime.base.tickCount + runtime.base.currentTicksThisFrame - 1
        if cl_clock_correction_force_server_tick.getValue() == 999:
            if (not self.is_clock_correction_enabled()) or (client_tick == 0) or (abs(tick - client_tick) > max_drift_ticks):
                runtime.base.tickCount = tick - (runtime.base.currentTicksThisFrame - 1)
                if runtime.base.tickCount < runtime.base.oldTickCount:
                    runtime.base.oldTickCount = runtime.base.tickCount
                self.clock_offsets = [0] * 16
                runtime.base.resetSimulation(runtime.base.tickCount)
        else:
            runtime.base.tickCount = tick + cl_clock_correction_force_server_tick.getValue()
            runtime.base.resetSimulation(runtime.base.tickCount)

        # Adjust the clock offset.
        self.clock_offsets[self.current_clock_offset] = client_tick - self.server_tick
        self.current_clock_offset = (self.current_clock_offset + 1) % 16

    def adjust_frame_time(self, input_frame_time: float) -> float:
        adjustment_this_frame: float = 0
        adjustment_per_sec: float = 0
        if self.is_clock_correction_enabled():
            curr_diff_in_seconds: float = self.get_current_clock_difference() * runtime.base.intervalPerTick
            curr_diff_in_ms: float = curr_diff_in_seconds * 1000.0

            if curr_diff_in_ms > cl_clock_correction_adjustment_min_offset.getValue():
                adjustment_per_sec = -self.get_clock_adjustment_amount(curr_diff_in_ms)
                adjustment_this_frame = input_frame_time * adjustment_per_sec
                adjustment_this_frame = max(adjustment_this_frame, -curr_diff_in_seconds)
            elif curr_diff_in_ms < -cl_clock_correction_adjustment_min_offset.getValue():
                adjustment_per_sec = self.get_clock_adjustment_amount(-curr_diff_in_ms)
                adjustment_this_frame = input_frame_time * adjustment_per_sec
                adjustment_this_frame = min(adjustment_this_frame, -curr_diff_in_seconds)

            self.adjust_average_difference_by(adjustment_this_frame)

        self.show_debug_info(adjustment_per_sec)
        return input_frame_time + adjustment_this_frame

    def show_debug_info(self, adjustment: float) -> None:
        if not cl_clock_show_debug_info.getValue():
            return

        if self.is_clock_correction_enabled():
            high: float = -999
            low: float = 999
            exact_diff: int = runtime.base.tickCount - self.server_tick
            for i in range(16):
                high = max(high, self.clock_offsets[i])
                low = min(low, self.clock_offsets[i])
            print(
                "Clock drift: adjustment (per sec): %.2fms, avg: %.3f, lo: %d, hi: %d, ex: %d"
                % (adjustment * 1000.0, self.get_current_clock_difference(), low, high, exact_diff)
            )
        else:
            print("Clock drift disabled.")

    def adjust_average_difference_by(self, amount_in_seconds: float) -> None:
        c: float = self.get_current_clock_difference()
        if c < 0.05:
            return

        amount_in_ticks: float = amount_in_seconds / runtime.base.intervalPerTick
        factor: float = 1 + amount_in_ticks / c

        for i in range(16):
            self.clock_offsets[i] *= factor

    def is_clock_correction_enabled(self) -> bool:
        return cl_clock_correction.getValue() and runtime.base.cl.connected and (runtime.base.cl.server_tick_count != -1)

    def clear(self) -> None:
        self.clock_offsets: list[float] = [0] * 16
        self.current_clock_offset: int = 0
        self.server_tick: int = 0
        self.client_tick: int = 0
