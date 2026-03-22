/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


#include "dcClass_ext.h"
#include "dcField_ext.h"
#include "dcAtomicField.h"
#include "dcPacker.h"

#ifdef HAVE_PYTHON

#if PANDA_MINOR_VERSION >= 11
// Panda3D 1.11+: class_def storage moved into PythonClassDefsImpl attached to
// DCClass::_python_class_defs.  The base DCClass no longer has direct
// has_class_def / set_class_def / get_class_def methods.

Extension<DCClass>::PythonClassDefsImpl *Extension<DCClass>::
do_get_defs() const {
  if (_this->_python_class_defs == nullptr) {
    ((DCClass *)_this)->_python_class_defs = new PythonClassDefsImpl;
  }
  return (PythonClassDefsImpl *)_this->_python_class_defs.p();
}

bool Extension<DCClass>::
has_class_def() const {
  if (_this->_python_class_defs == nullptr) {
    return false;
  }
  return do_get_defs()->_class_def != nullptr;
}

void Extension<DCClass>::
set_class_def(PyObject *class_def) {
  PythonClassDefsImpl *defs = do_get_defs();
  Py_XDECREF(defs->_class_def);
  Py_XINCREF(class_def);
  defs->_class_def = class_def;
}

PyObject *Extension<DCClass>::
get_class_def() const {
  PyObject *result = do_get_defs()->_class_def;
  Py_XINCREF(result);
  return result;
}

bool Extension<DCClass>::
has_owner_class_def() const {
  if (_this->_python_class_defs == nullptr) {
    return false;
  }
  return do_get_defs()->_owner_class_def != nullptr;
}

void Extension<DCClass>::
set_owner_class_def(PyObject *owner_class_def) {
  PythonClassDefsImpl *defs = do_get_defs();
  Py_XDECREF(defs->_owner_class_def);
  Py_XINCREF(owner_class_def);
  defs->_owner_class_def = owner_class_def;
}

PyObject *Extension<DCClass>::
get_owner_class_def() const {
  PyObject *result = do_get_defs()->_owner_class_def;
  Py_XINCREF(result);
  return result;
}

#else
// Panda3D 1.10: DCClass has direct has_class_def / set_class_def /
// get_class_def methods that are dllexport-ed.

bool Extension<DCClass>::
has_class_def() const {
  return _this->has_class_def();
}

void Extension<DCClass>::
set_class_def(PyObject *class_def) {
  _this->set_class_def(class_def);
}

PyObject *Extension<DCClass>::
get_class_def() const {
  return _this->get_class_def();
}

bool Extension<DCClass>::
has_owner_class_def() const {
  return _this->has_owner_class_def();
}

void Extension<DCClass>::
set_owner_class_def(PyObject *owner_class_def) {
  _this->set_owner_class_def(owner_class_def);
}

PyObject *Extension<DCClass>::
get_owner_class_def() const {
  return _this->get_owner_class_def();
}

#endif  // PANDA_MINOR_VERSION >= 11

/**
 * Looks up the current value of the indicated field by calling the
 * appropriate get*() function, then packs that value into the packer.
 *
 * Returns true on success, false on failure.
 */
bool Extension<DCClass>::
pack_required_field(DCPacker &packer, PyObject *distobj,
                    const DCField *field) const {
  using std::ostringstream;

  const DCParameter *parameter = field->as_parameter();
  if (parameter != nullptr) {
    std::string field_name = field->get_name();

    if (!PyObject_HasAttrString(distobj, (char *)field_name.c_str())) {
      if (field->has_default_value()) {
        packer.pack_default_value();
        return true;
      }

      ostringstream strm;
      strm << "Data element " << field_name
           << ", required by dc file for dclass " << _this->get_name()
           << ", not defined on object";
      nassert_raise(strm.str());
      return false;
    }
    PyObject *result =
      PyObject_GetAttrString(distobj, (char *)field_name.c_str());
    nassertr(result != nullptr, false);

    bool pack_ok = invoke_extension((DCField *)parameter).pack_args(packer, result);
    Py_DECREF(result);

    return pack_ok;
  }

  if (field->as_molecular_field() != nullptr) {
    std::ostringstream strm;
    strm << "Cannot pack molecular field " << field->get_name()
         << " for generate";
    nassert_raise(strm.str());
    return false;
  }

  const DCAtomicField *atom = field->as_atomic_field();
  nassertr(atom != nullptr, false);

  std::string setter_name = atom->get_name();

  if (setter_name.empty()) {
    std::ostringstream strm;
    strm << "Required field is unnamed!";
    nassert_raise(strm.str());
    return false;
  }

  if (atom->get_num_elements() == 0) {
    std::ostringstream strm;
    strm << "Required field " << setter_name << " has no parameters!";
    nassert_raise(strm.str());
    return false;
  }

  std::string getter_name = setter_name;
  if (setter_name.substr(0, 3) == "set") {
    getter_name[0] = 'g';
  } else {
    getter_name = "get" + setter_name;
    getter_name[3] = toupper(getter_name[3]);
  }

  if (!PyObject_HasAttrString(distobj, (char *)getter_name.c_str())) {
    if (field->has_default_value()) {
      packer.pack_default_value();
      return true;
    }

    std::ostringstream strm;
    strm << "Distributed class " << _this->get_name()
         << " doesn't have getter named " << getter_name
         << " to match required field " << setter_name;
    nassert_raise(strm.str());
    return false;
  }
  PyObject *func =
    PyObject_GetAttrString(distobj, (char *)getter_name.c_str());
  nassertr(func != nullptr, false);

  PyObject *result = PyObject_CallNoArgs(func);
  Py_DECREF(func);
  if (result == nullptr) {
    std::cerr << "Error when calling " << getter_name << "\n";
    return false;
  }

  if (atom->get_num_elements() == 1) {
    PyObject *tuple = PyTuple_New(1);
    PyTuple_SET_ITEM(tuple, 0, result);
    result = tuple;
  } else {
    if (!PySequence_Check(result)) {
      std::ostringstream strm;
      strm << "Since dclass " << _this->get_name() << " method " << setter_name
           << " is declared to have multiple parameters, Python function "
           << getter_name << " must return a list or tuple.\n";
      nassert_raise(strm.str());
      return false;
    }
  }

  bool pack_ok = invoke_extension((DCField *)atom).pack_args(packer, result);
  Py_DECREF(result);

  return pack_ok;
}

#endif  // HAVE_PYTHON
