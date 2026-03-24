/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


/**
 *
 */
INLINE int NetworkClock::
get_tick_rate() const {
  return _ticks_per_sec;
}

/**
 *
 */
INLINE int NetworkClock::
get_tick_count() const {
  return _tick_count;
}

/**
 *
 */
INLINE void NetworkClock::
set_tick_count(int count) {
  _tick_count = count;
}

/**
 *
 */
INLINE int NetworkClock::
get_old_tick_count() const {
  return _old_tick_count;
}

/**
 *
 */
INLINE int NetworkClock::
get_current_ticks_this_frame() const {
  return _current_ticks_this_frame;
}

/**
 *
 */
INLINE double NetworkClock::
get_interval_per_tick() const {
  return _interval_per_tick;
}

/**
 *
 */
INLINE double NetworkClock::
get_remainder() const {
  return _remainder;
}

/**
 *
 */
INLINE double NetworkClock::
ticks_to_time(int ticks) const {
  return ticks * _interval_per_tick;
}

/**
 * Returns the current real time in seconds from the global ClockObject.
 */
INLINE double NetworkClock::
get_time() const {
  return ClockObject::get_global_clock()->get_real_time();
}

/**
 * Returns the client-side simulation time, which is advanced by advance().
 */
INLINE double NetworkClock::
get_client_time() const {
  return _client_time;
}

/**
 * Returns the simulation time delta for the current frame, excluding
 * any fractional tick remainder.  Useful for fixed-step simulation.
 */
INLINE double NetworkClock::
get_simulation_delta_no_remainder() const {
  return _current_ticks_this_frame * _interval_per_tick;
}

/**
 * Returns whether clock correction is currently active.
 */
INLINE bool NetworkClock::
get_clock_correction_enabled() const {
  return _clock_correction_active;
}

/**
 * Returns the singleton NetworkClock instance.
 */
INLINE NetworkClock *NetworkClock::
get_global_ptr() {
  if (_global_ptr == nullptr) {
    _global_ptr = new NetworkClock();
  }
  return _global_ptr;
}
