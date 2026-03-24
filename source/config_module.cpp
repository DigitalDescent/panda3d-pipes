
#include "config_module.h"
#include "dconfig.h"

#include "networkClock.h"
#include "packedObject.h"
#include "clientFrame.h"
#include "frameSnapshot.h"
#include "frameSnapshotEntry.h"

Configure(config_pipes);
NotifyCategoryDef(pipes , "");

ConfigureFn(config_pipes) {
  init_libpipes();
}

/**
 * Initializes the library.  This must be called at least once before any of
 * the functions or classes in this library can be used.  Normally it will be
 * called by the static initializers and need not be called explicitly, but
 * special cases exist.
 */
void
init_libpipes() {
  static bool initialized = false;
  if (initialized) {
    return;
  }
  initialized = true;

  ClientFrame::init_type();
  FrameSnapshot::init_type();
  FrameSnapshotEntry::init_type();
  NetworkClock::init_type();
  PackedObject::init_type();

  return;
}

