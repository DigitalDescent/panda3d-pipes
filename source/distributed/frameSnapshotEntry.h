/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


#ifndef FRAMESNAPSHOTENTRY_H
#define FRAMESNAPSHOTENTRY_H

#include "config_module.h"
#include "dcbase.h"
#include "deletedChain.h"
#include "typedObject.h"

class DCClass;
class PackedObject;

/**
 * Individual object data, did the object exist and what was its object id.
 * Also stores a handle to the absolute state of the object at the time of the
 * snapshot.
 */
class FrameSnapshotEntry : public TypedObject {
PUBLISHED:
  ALLOC_DELETED_CHAIN(FrameSnapshotEntry);

  INLINE FrameSnapshotEntry();

  INLINE void set_class(DCClass *dclass);
  INLINE DCClass *get_class() const;

  INLINE void set_do_id(DOID_TYPE do_id);
  INLINE DOID_TYPE get_do_id() const;

  INLINE void set_zone_id(ZONEID_TYPE zone_id);
  INLINE ZONEID_TYPE get_zone_id() const;

  INLINE void set_exists(bool exists);
  INLINE bool get_exists() const;

  INLINE void set_packed_object(PackedObject *obj);
  INLINE PackedObject *get_packed_object() const;

private:
  DCClass *_dclass;
  DOID_TYPE _do_id;
  ZONEID_TYPE _zone_id;
  bool _exists;
  PackedObject *_packed_data;

public:
  static TypeHandle get_class_type() {
    return _type_handle;
  }
  static void init_type() {
    TypedObject::init_type();
    register_type(_type_handle, "FrameSnapshotEntry",
                  TypedObject::get_class_type());
    }
  virtual TypeHandle get_type() const {
    return get_class_type();
  }
  virtual TypeHandle force_init_type() {init_type(); return get_class_type();}

private:
  static TypeHandle _type_handle;
};

#include "frameSnapshotEntry.I"

#endif // FRAMESNAPSHOTENTRY_H
