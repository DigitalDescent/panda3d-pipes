/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


#ifndef DCPACKER_EXT_H
#define DCPACKER_EXT_H

#include "dtoolbase.h"

#ifdef HAVE_PYTHON

#include "extension.h"
#include "dcPacker.h"
#include "py_panda.h"

template<>
class Extension<DCPacker> : public ExtensionBase<DCPacker> {
public:
  void pack_object(PyObject *object);
  PyObject *unpack_object();

private:
  void pack_class_object(const DCClass *dclass, PyObject *object);
  PyObject *unpack_class_object(const DCClass *dclass);
  void set_class_element(PyObject *class_def, PyObject *&object,
                         const DCField *field);
  void get_class_element(const DCClass *dclass, PyObject *object,
                         const DCField *field);
};

#endif  // HAVE_PYTHON

#endif  // DCPACKER_EXT_H
