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
#include "pandaVersion.h"
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

#if PANDA_MINOR_VERSION >= 11
private:
  /**
   * Implementation of DCClass::PythonClassDefs which actually stores the
   * Python pointers.  This needs to be defined here rather than on DCClass
   * itself, since DCClass cannot include Python.h or call Python functions.
   */
  class PythonClassDefsImpl : public DCClass::PythonClassDefs {
  public:
    virtual ~PythonClassDefsImpl() {
      Py_XDECREF(_class_def);
      Py_XDECREF(_owner_class_def);
    }

    PyObject *_class_def = nullptr;
    PyObject *_owner_class_def = nullptr;
  };

  PythonClassDefsImpl *do_get_defs() const;
#endif
};

#endif  // HAVE_PYTHON

#endif  // DCCLASS_EXT_H
