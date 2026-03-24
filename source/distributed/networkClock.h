/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


#ifndef NETWORKCLOCK_H
#define NETWORKCLOCK_H

#include "config_module.h"
#include "asyncTaskManager.h"
#include "clockObject.h"
#include "configVariableBool.h"
#include "configVariableInt.h"
#include "genericAsyncTask.h"
#include "referenceCount.h"
#include "pointerTo.h"

/**
 * Manages tick-based simulation timing and client-server clock drift
 * correction for networked sessions.
 *
 * A single NetworkClock instance is shared between the ServerRepository and
 * ClientRepository when they live in the same process (hosted/listen server).
 * It owns the tick counter, accumulator, all conversion helpers, and the
 * clock-drift manager that keeps client ticks aligned with the server.
 *
 * The advance() method should be called once per frame with the frame's
 * delta-time.  It accumulates time and increments the tick counter as needed.
 */
class NetworkClock : public TypedReferenceCount {
PUBLISHED:
  static const int DRIFT_SAMPLE_COUNT = 16;

  NetworkClock();

  // -- tick management -------------------------------------------------------

  void set_tick_rate(int rate);
  INLINE int get_tick_rate() const;

  INLINE int get_tick_count() const;
  INLINE void set_tick_count(int count);

  INLINE int get_old_tick_count() const;
  INLINE int get_current_ticks_this_frame() const;

  INLINE double get_interval_per_tick() const;
  INLINE double get_remainder() const;

  INLINE double ticks_to_time(int ticks) const;
  int time_to_ticks(double time_val) const;

  INLINE double get_time() const;
  INLINE double get_client_time() const;
  double network_to_client_time(double server_time) const;
  INLINE double get_simulation_delta_no_remainder() const;

  void reset_simulation(int tick_count);
  void advance(double dt);
  void start();
  void stop();

  // -- clock drift correction ------------------------------------------------

  void set_clock_correction_enabled(bool enabled);
  INLINE bool get_clock_correction_enabled() const;

  void set_server_tick(int tick);
  double adjust_frame_time(double input_frame_time);
  void clear_drift();

  INLINE static NetworkClock *get_global_ptr();

private:
  double get_current_clock_difference() const;
  double get_clock_adjustment_amount(double curr_diff_in_ms) const;
  void adjust_average_difference_by(double amount_in_seconds);
  static double remap_val(double val, double a, double b, double c, double d);

  // -- tick state ------------------------------------------------------------
  int _tick_count;
  int _old_tick_count;
  int _current_ticks_this_frame;
  int _ticks_per_sec;
  double _interval_per_tick;
  double _remainder;
  double _tick_accum;
  double _client_time;

  // -- task state -------------------------------------------------------------
  PT(GenericAsyncTask) _task;
  static AsyncTask::DoneStatus advance_task(GenericAsyncTask *task, void *data);

  // -- drift state -----------------------------------------------------------
  double _clock_offsets[DRIFT_SAMPLE_COUNT];
  int _current_clock_offset;
  int _server_tick;
  bool _clock_correction_active;

  static PT(NetworkClock) _global_ptr;

public:
  static TypeHandle get_class_type() {
    return _type_handle;
  }
  static void init_type() {
    TypedReferenceCount::init_type();
    register_type(_type_handle, "NetworkClock",
                  TypedReferenceCount::get_class_type());
  }
  virtual TypeHandle get_type() const {
    return get_class_type();
  }
  virtual TypeHandle force_init_type() { init_type(); return get_class_type(); }

private:
  static TypeHandle _type_handle;
};

#include "networkClock.I"

#endif // NETWORKCLOCK_H
