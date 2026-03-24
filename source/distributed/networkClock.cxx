/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


#include "networkClock.h"

#include <algorithm>
#include <cmath>

TypeHandle NetworkClock::_type_handle;
PT(NetworkClock) NetworkClock::_global_ptr;

static ConfigVariableBool pipes_clock_correction
("pipes-clock-correction", true);
static ConfigVariableInt pipes_clock_drift_max_ms
("pipes-clock-drift-max-ms", 150);
static ConfigVariableBool pipes_clock_show_debug_info
("pipes-clock-show-debug-info", false);
static ConfigVariableInt pipes_clock_correction_force_server_tick
("pipes-clock-correction-force-server-tick", 999);
static ConfigVariableInt pipes_clock_correction_adjustment_max_amount
("pipes-clock-correction-adjustment-max-amount", 200);
static ConfigVariableInt pipes_clock_correction_adjustment_min_offset
("pipes-clock-correction-adjustment-min-offset", 10);
static ConfigVariableInt pipes_clock_correction_adjustment_max_offset
("pipes-clock-correction-adjustment-max-offset", 90);

/**
 *
 */
NetworkClock::
NetworkClock() :
  _tick_count(0),
  _old_tick_count(0),
  _current_ticks_this_frame(0),
  _ticks_per_sec(0),
  _interval_per_tick(0.0),
  _remainder(0.0),
  _tick_accum(0.0),
  _client_time(0.0),
  _current_clock_offset(0),
  _server_tick(0),
  _clock_correction_active(false) {
  for (int i = 0; i < DRIFT_SAMPLE_COUNT; i++) {
    _clock_offsets[i] = 0.0;
  }
}

// -- tick management ---------------------------------------------------------

/**
 * Sets the tick rate in Hz.  Recomputes interval_per_tick.
 */
void NetworkClock::
set_tick_rate(int rate) {
  _ticks_per_sec = rate;
  if (rate > 0) {
    _interval_per_tick = 1.0 / (double)rate;
    start();
  } else {
    _interval_per_tick = 0.0;
  }
}

/**
 * Converts a time value in seconds to the nearest tick count.
 */
int NetworkClock::
time_to_ticks(double time_val) const {
  if (_interval_per_tick <= 0.0) {
    return 0;
  }
  return (int)(time_val / _interval_per_tick + 0.5);
}

/**
 * Converts a server timestamp to client-local time.
 */
double NetworkClock::
network_to_client_time(double server_time) const {
  return server_time;
}

/**
 * Resets the simulation to the given tick count, clearing
 * per-frame accumulators.
 */
void NetworkClock::
reset_simulation(int tick_count) {
  _tick_count = tick_count;
  _old_tick_count = tick_count;
  _current_ticks_this_frame = 0;
  _tick_accum = 0.0;
}

/**
 * Advances the clock by the given frame delta-time.  Increments
 * the tick counter as many times as the accumulated time allows
 * and records the fractional remainder for interpolation.
 */
void NetworkClock::
advance(double dt) {
  if (_interval_per_tick <= 0.0) {
    _client_time += dt;
    return;
  }

  _old_tick_count = _tick_count;
  _tick_accum += dt;

  _current_ticks_this_frame = 0;
  while (_tick_accum >= _interval_per_tick) {
    _tick_accum -= _interval_per_tick;
    _tick_count++;
    _current_ticks_this_frame++;
  }

  _remainder = _tick_accum;
  _client_time += dt;
}

/**
 * Registers a task that calls advance() every frame.  Safe to call
 * multiple times — only the first call has an effect.
 */
void NetworkClock::
start() {
  if (_task != nullptr) {
    return;
  }
  _task = new GenericAsyncTask("netClockAdvance", advance_task, this);
  _task->set_sort(-200);
  AsyncTaskManager::get_global_ptr()->add(_task);
}

/**
 * Removes the advance task.  Normally not needed — the task lives
 * for the lifetime of the process.
 */
void NetworkClock::
stop() {
  if (_task != nullptr) {
    _task->remove();
    _task = nullptr;
  }
}

/**
 * Static task callback that advances the singleton clock.
 */
AsyncTask::DoneStatus NetworkClock::
advance_task(GenericAsyncTask *, void *data) {
  NetworkClock *self = (NetworkClock *)data;
  double dt = ClockObject::get_global_clock()->get_dt();
  self->advance(dt);
  return AsyncTask::DS_cont;
}

// -- clock drift correction --------------------------------------------------

/**
 * Enables or disables clock correction.  The ClientRepository should call
 * this with true once it is connected and has received a server tick, and
 * with false when disconnected.
 */
void NetworkClock::
set_clock_correction_enabled(bool enabled) {
  _clock_correction_active = enabled;
}

/**
 * Records a server tick and, if the client clock has drifted too far,
 * snaps or begins correcting back toward alignment.
 */
void NetworkClock::
set_server_tick(int tick) {
  _server_tick = tick;

  int max_drift_ticks = time_to_ticks(
    pipes_clock_drift_max_ms.get_value() / 1000.0);

  int client_tick = _tick_count + _current_ticks_this_frame - 1;

  int force = pipes_clock_correction_force_server_tick.get_value();
  if (force == 999) {
    if (!_clock_correction_active || client_tick == 0 ||
        abs(tick - client_tick) > max_drift_ticks) {
      _tick_count = tick - (_current_ticks_this_frame - 1);
      if (_tick_count < _old_tick_count) {
        // _old_tick_count must not exceed _tick_count
        _old_tick_count = _tick_count;
      }
      for (int i = 0; i < DRIFT_SAMPLE_COUNT; i++) {
        _clock_offsets[i] = 0.0;
      }
      reset_simulation(_tick_count);
    }
  } else {
    _tick_count = tick + force;
    reset_simulation(_tick_count);
  }

  _clock_offsets[_current_clock_offset] = (double)(client_tick - _server_tick);
  _current_clock_offset = (_current_clock_offset + 1) % DRIFT_SAMPLE_COUNT;
}

/**
 * Adjusts the input frame time to gradually correct clock drift.
 * Returns the modified frame time that should be used for simulation.
 */
double NetworkClock::
adjust_frame_time(double input_frame_time) {
  double adjustment_this_frame = 0.0;
  double adjustment_per_sec = 0.0;

  if (_clock_correction_active && pipes_clock_correction.get_value()) {
    double curr_diff_in_seconds =
      get_current_clock_difference() * _interval_per_tick;
    double curr_diff_in_ms = curr_diff_in_seconds * 1000.0;

    double min_offset = (double)pipes_clock_correction_adjustment_min_offset.get_value();

    if (curr_diff_in_ms > min_offset) {
      adjustment_per_sec = -get_clock_adjustment_amount(curr_diff_in_ms);
      adjustment_this_frame = input_frame_time * adjustment_per_sec;
      adjustment_this_frame = std::max(adjustment_this_frame, -curr_diff_in_seconds);
    } else if (curr_diff_in_ms < -min_offset) {
      adjustment_per_sec = get_clock_adjustment_amount(-curr_diff_in_ms);
      adjustment_this_frame = input_frame_time * adjustment_per_sec;
      adjustment_this_frame = std::min(adjustment_this_frame, -curr_diff_in_seconds);
    }

    adjust_average_difference_by(adjustment_this_frame);
  }

  if (pipes_clock_show_debug_info.get_value()) {
    if (_clock_correction_active && pipes_clock_correction.get_value()) {
      double high = -999.0, low = 999.0;
      int exact_diff = _tick_count - _server_tick;
      for (int i = 0; i < DRIFT_SAMPLE_COUNT; i++) {
        high = std::max(high, _clock_offsets[i]);
        low = std::min(low, _clock_offsets[i]);
      }
      pipes_cat.info()
        << "Clock drift: adjustment (per sec): "
        << adjustment_per_sec * 1000.0 << "ms, avg: "
        << get_current_clock_difference() << ", lo: " << low
        << ", hi: " << high << ", ex: " << exact_diff << "\n";
    } else {
      pipes_cat.info() << "Clock drift disabled.\n";
    }
  }

  return input_frame_time + adjustment_this_frame;
}

/**
 * Resets drift tracking state.
 */
void NetworkClock::
clear_drift() {
  for (int i = 0; i < DRIFT_SAMPLE_COUNT; i++) {
    _clock_offsets[i] = 0.0;
  }
  _current_clock_offset = 0;
  _server_tick = 0;
}

// -- private helpers ---------------------------------------------------------

double NetworkClock::
get_current_clock_difference() const {
  double total = 0.0;
  for (int i = 0; i < DRIFT_SAMPLE_COUNT; i++) {
    total += _clock_offsets[i];
  }
  return total / (double)DRIFT_SAMPLE_COUNT;
}

double NetworkClock::
get_clock_adjustment_amount(double curr_diff_in_ms) const {
  double min_off = (double)pipes_clock_correction_adjustment_min_offset.get_value();
  double max_off = (double)pipes_clock_correction_adjustment_max_offset.get_value();
  double max_amt = (double)pipes_clock_correction_adjustment_max_amount.get_value() / 1000.0;

  curr_diff_in_ms = std::max(min_off, std::min(max_off, curr_diff_in_ms));
  return remap_val(curr_diff_in_ms, min_off, max_off, 0.0, max_amt);
}

void NetworkClock::
adjust_average_difference_by(double amount_in_seconds) {
  double c = get_current_clock_difference();
  if (c < 0.05) {
    return;
  }
  double amount_in_ticks = amount_in_seconds / _interval_per_tick;
  double factor = 1.0 + amount_in_ticks / c;
  for (int i = 0; i < DRIFT_SAMPLE_COUNT; i++) {
    _clock_offsets[i] *= factor;
  }
}

double NetworkClock::
remap_val(double val, double a, double b, double c, double d) {
  if (a == b) {
    return (val >= b) ? d : c;
  }
  return c + (d - c) * (val - a) / (b - a);
}
