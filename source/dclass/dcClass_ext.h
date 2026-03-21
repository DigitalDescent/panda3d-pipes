/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


#ifndef DCCLASS_EXT_H
#define DCCLASS_EXT_H

#include "dtoolbase.h"

#ifdef HAVE_PYTHON

#include "extension.h"
#include "dcClass.h"
#include "dcPacker.h"
#include "py_panda.h"

template<>
class Extension<DCClass> : public ExtensionBase<DCClass> {
public:
  bool has_class_def() const;
  void set_class_def(PyObject *class_def);
  PyObject *get_class_def() const;

  bool has_owner_class_def() const;
  void set_owner_class_def(PyObject *owner_class_def);
  PyObject *get_owner_class_def() const;

  bool pack_required_field(DCPacker &packer, PyObject *distobj,
                           const DCField *field) const;
};

#endif  // HAVE_PYTHON

#endif  // DCCLASS_EXT_H
