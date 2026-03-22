/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */

#ifndef DC_PYTHON_H
#define DC_PYTHON_H

#include "dtoolbase.h"
#include "dcClass.h"
#include "dcField.h"
#include "dcPacker.h"
#include "extension.h"
#include "pandaVersion.h"
#include "py_panda.h"

/**
 * Plain helper functions for packing/unpacking Python objects through the DC
 * system.  These replace the Extension<DCClass>, Extension<DCField>, and
 * Extension<DCPacker> templates that were previously used, so that this module
 * doesn't need to link against (or re-export) those Extension symbols from
 * Panda3D's libp3direct.
 */
namespace dc_python {

// --- DCClass helpers ---

bool dc_class_has_class_def(const DCClass *cls);
void dc_class_set_class_def(DCClass *cls, PyObject *class_def);
PyObject *dc_class_get_class_def(const DCClass *cls);

bool dc_class_has_owner_class_def(const DCClass *cls);
void dc_class_set_owner_class_def(DCClass *cls, PyObject *owner_class_def);
PyObject *dc_class_get_owner_class_def(const DCClass *cls);

bool dc_class_pack_required_field(const DCClass *cls, DCPacker &packer,
                                  PyObject *distobj, const DCField *field);

// --- DCField helpers ---

bool dc_field_pack_args(const DCField *field, DCPacker &packer,
                        PyObject *sequence);
PyObject *dc_field_unpack_args(const DCField *field, DCPacker &packer);

// --- DCPacker helpers ---

void dc_packer_pack_object(DCPacker *packer, PyObject *object);
PyObject *dc_packer_unpack_object(DCPacker *packer);

// --- Utility ---

std::string get_pystr(PyObject *value);

}  // namespace dc_python

// --------------------------------------------------------------------------
// Panda3D 1.11+ class-def storage
// --------------------------------------------------------------------------
#if PANDA_MINOR_VERSION >= 11

/**
 * Extension<DCClass> specialization used solely to access the private
 * PythonClassDefs / _python_class_defs members through the existing friend
 * declaration in dcClass.h.
 */
template<>
class Extension<DCClass> : public ExtensionBase<DCClass> {
public:
  /**
   * Concrete implementation of DCClass::PythonClassDefs that stores the two
   * Python class pointers (class_def and owner_class_def).
   */
  class Impl : public DCClass::PythonClassDefs {
  public:
    ~Impl() override {
      Py_XDECREF(_class_def);
      Py_XDECREF(_owner_class_def);
    }

    PyObject *_class_def = nullptr;
    PyObject *_owner_class_def = nullptr;
  };

  static Impl *get_class_defs(const DCClass *cls) {
    if (cls->_python_class_defs == nullptr) {
      const_cast<DCClass *>(cls)->_python_class_defs = new Impl;
    }
    return static_cast<Impl *>(cls->_python_class_defs.p());
  }

  static bool has_defs(const DCClass *cls) {
    return cls->_python_class_defs != nullptr;
  }
};

#endif  // PANDA_MINOR_VERSION >= 11

#endif  // DC_PYTHON_H
