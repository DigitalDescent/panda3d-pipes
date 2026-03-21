/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


#ifndef DCFIELD_EXT_H
#define DCFIELD_EXT_H

#include "dtoolbase.h"

#ifdef HAVE_PYTHON

#include "extension.h"
#include "dcField.h"
#include "dcPacker.h"
#include "py_panda.h"

template<>
class Extension<DCField> : public ExtensionBase<DCField> {
public:
  bool pack_args(DCPacker &packer, PyObject *sequence) const;
  PyObject *unpack_args(DCPacker &packer) const;

  static std::string get_pystr(PyObject *value);
};

#endif  // HAVE_PYTHON

#endif  // DCFIELD_EXT_H
