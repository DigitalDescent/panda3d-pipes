/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */

#include "dc_python.h"
#include "dcAtomicField.h"
#include "dcClassParameter.h"
#include "dcmsgtypes.h"
#include "datagram.h"

namespace dc_python {

// =========================================================================
// DCClass helpers
// =========================================================================

#if PANDA_MINOR_VERSION >= 11

// Panda3D 1.11+: class_def storage is in PythonClassDefsImpl, attached to
// DCClass::_python_class_defs.

typedef Extension<DCClass> DCClassAccess;
typedef DCClassAccess::Impl DCClassDefs;

bool dc_class_has_class_def(const DCClass *cls) {
  if (!DCClassAccess::has_defs(cls)) {
    return false;
  }
  return DCClassAccess::get_class_defs(cls)->_class_def != nullptr;
}

void dc_class_set_class_def(DCClass *cls, PyObject *class_def) {
  DCClassDefs *defs = DCClassAccess::get_class_defs(cls);
  Py_XDECREF(defs->_class_def);
  Py_XINCREF(class_def);
  defs->_class_def = class_def;
}

PyObject *dc_class_get_class_def(const DCClass *cls) {
  PyObject *result = DCClassAccess::get_class_defs(cls)->_class_def;
  Py_XINCREF(result);
  return result;
}

bool dc_class_has_owner_class_def(const DCClass *cls) {
  if (!DCClassAccess::has_defs(cls)) {
    return false;
  }
  return DCClassAccess::get_class_defs(cls)->_owner_class_def != nullptr;
}

void dc_class_set_owner_class_def(DCClass *cls, PyObject *owner_class_def) {
  DCClassDefs *defs = DCClassAccess::get_class_defs(cls);
  Py_XDECREF(defs->_owner_class_def);
  Py_XINCREF(owner_class_def);
  defs->_owner_class_def = owner_class_def;
}

PyObject *dc_class_get_owner_class_def(const DCClass *cls) {
  PyObject *result = DCClassAccess::get_class_defs(cls)->_owner_class_def;
  Py_XINCREF(result);
  return result;
}

#else
// Panda3D 1.10: DCClass has direct methods that are dllexport-ed.

bool dc_class_has_class_def(const DCClass *cls) {
  return cls->has_class_def();
}

void dc_class_set_class_def(DCClass *cls, PyObject *class_def) {
  cls->set_class_def(class_def);
}

PyObject *dc_class_get_class_def(const DCClass *cls) {
  return cls->get_class_def();
}

bool dc_class_has_owner_class_def(const DCClass *cls) {
  return cls->has_owner_class_def();
}

void dc_class_set_owner_class_def(DCClass *cls, PyObject *owner_class_def) {
  cls->set_owner_class_def(owner_class_def);
}

PyObject *dc_class_get_owner_class_def(const DCClass *cls) {
  return cls->get_owner_class_def();
}

#endif  // PANDA_MINOR_VERSION >= 11

bool dc_class_pack_required_field(const DCClass *cls, DCPacker &packer,
                                  PyObject *distobj, const DCField *field) {
  const DCParameter *parameter = field->as_parameter();
  if (parameter != nullptr) {
    std::string field_name = field->get_name();

    if (!PyObject_HasAttrString(distobj, (char *)field_name.c_str())) {
      if (field->has_default_value()) {
        packer.pack_default_value();
        return true;
      }

      std::ostringstream strm;
      strm << "Data element " << field_name
           << ", required by dc file for dclass " << cls->get_name()
           << ", not defined on object";
      nassert_raise(strm.str());
      return false;
    }
    PyObject *result =
      PyObject_GetAttrString(distobj, (char *)field_name.c_str());
    nassertr(result != nullptr, false);

    bool pack_ok = dc_field_pack_args((const DCField *)parameter, packer, result);
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
    strm << "Distributed class " << cls->get_name()
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
      strm << "Since dclass " << cls->get_name() << " method " << setter_name
           << " is declared to have multiple parameters, Python function "
           << getter_name << " must return a list or tuple.\n";
      nassert_raise(strm.str());
      return false;
    }
  }

  bool pack_ok = dc_field_pack_args((const DCField *)atom, packer, result);
  Py_DECREF(result);

  return pack_ok;
}

// =========================================================================
// DCField helpers
// =========================================================================

bool dc_field_pack_args(const DCField *field, DCPacker &packer,
                        PyObject *sequence) {
  nassertr(!packer.had_error(), false);
  nassertr(packer.get_current_field() == field, false);

  dc_packer_pack_object(&packer, sequence);
  if (!packer.had_error()) {
    return true;
  }

  if (!Notify::ptr()->has_assert_failed()) {
    std::ostringstream strm;
    PyObject *exc_type = PyExc_Exception;

    if (field->as_parameter() != nullptr) {
      if (packer.had_pack_error()) {
        strm << "Incorrect arguments to field: " << field->get_name()
             << " = " << get_pystr(sequence);
        exc_type = PyExc_TypeError;
      } else {
        strm << "Value out of range on field: " << field->get_name()
             << " = " << get_pystr(sequence);
        exc_type = PyExc_ValueError;
      }
    } else {
      PyObject *tuple = PySequence_Tuple(sequence);
      if (tuple == nullptr) {
        strm << "Value for " << field->get_name() << " not a sequence: "
             << get_pystr(sequence);
        exc_type = PyExc_TypeError;
      } else {
        if (packer.had_pack_error()) {
          strm << "Incorrect arguments to field: " << field->get_name()
               << get_pystr(sequence);
          exc_type = PyExc_TypeError;
        } else {
          strm << "Value out of range on field: " << field->get_name()
               << get_pystr(sequence);
          exc_type = PyExc_ValueError;
        }
        Py_DECREF(tuple);
      }
    }

    std::string message = strm.str();
    PyErr_SetString(exc_type, message.c_str());
  }
  return false;
}

PyObject *dc_field_unpack_args(const DCField *field, DCPacker &packer) {
  nassertr(!packer.had_error(), nullptr);
  nassertr(packer.get_current_field() == field, nullptr);

  size_t start_byte = packer.get_num_unpacked_bytes();
  PyObject *object = dc_packer_unpack_object(&packer);

  if (!packer.had_error()) {
    return object;
  }

  if (!Notify::ptr()->has_assert_failed()) {
    std::ostringstream strm;
    PyObject *exc_type = PyExc_Exception;

    if (packer.had_pack_error()) {
      strm << "Data error unpacking field ";
      field->output(strm, true);
      size_t length = packer.get_unpack_length() - start_byte;
      strm << "\nGot data (" << (int)length << " bytes):\n";
      Datagram dg(packer.get_unpack_data() + start_byte, length);
      dg.dump_hex(strm);
      size_t error_byte = packer.get_num_unpacked_bytes() - start_byte;
      strm << "Error detected on byte " << error_byte
           << " (" << std::hex << error_byte << std::dec << " hex)";
      exc_type = PyExc_RuntimeError;
    } else {
      strm << "Value outside specified range when unpacking field "
           << field->get_name() << ": " << get_pystr(object);
      exc_type = PyExc_ValueError;
    }

    std::string message = strm.str();
    PyErr_SetString(exc_type, message.c_str());
  }

  Py_XDECREF(object);
  return nullptr;
}

// =========================================================================
// DCPacker helpers — internal forward declarations
// =========================================================================

static void pack_class_object(DCPacker *packer, const DCClass *dclass,
                              PyObject *object);
static PyObject *unpack_class_object(DCPacker *packer, const DCClass *dclass);
static void set_class_element(DCPacker *packer, PyObject *class_def,
                              PyObject *&object, const DCField *field);
static void get_class_element(DCPacker *packer, const DCClass *dclass,
                              PyObject *object, const DCField *field);

// =========================================================================
// DCPacker helpers — implementation
// =========================================================================

void dc_packer_pack_object(DCPacker *packer, PyObject *object) {
  DCPackType pack_type = packer->get_pack_type();

  switch (pack_type) {
  case PT_int64:
    if (PyLong_Check(object)) {
      packer->pack_int64(PyLong_AsLongLong(object));
      return;
    }
    break;

  case PT_uint64:
    if (PyLong_Check(object)) {
      packer->pack_uint64(PyLong_AsUnsignedLongLong(object));
      return;
    }
    break;

  case PT_int:
    if (PyLong_Check(object)) {
      packer->pack_int(PyLong_AsLong(object));
      return;
    }
    break;

  case PT_uint:
    if (PyLong_Check(object)) {
      packer->pack_uint(PyLong_AsUnsignedLong(object));
      return;
    }
    break;

  default:
    break;
  }

  if (PyLong_Check(object)) {
    packer->pack_int(PyLong_AsLong(object));
  } else if (PyFloat_Check(object)) {
    packer->pack_double(PyFloat_AS_DOUBLE(object));
  } else if (PyUnicode_Check(object)) {
    const char *buffer;
    Py_ssize_t length;
    buffer = PyUnicode_AsUTF8AndSize(object, &length);
    if (buffer) {
      packer->pack_string(std::string(buffer, length));
    }
  } else if (PyBytes_Check(object)) {
    const unsigned char *buffer;
    Py_ssize_t length;
    PyBytes_AsStringAndSize(object, (char **)&buffer, &length);
    if (buffer) {
      packer->pack_blob(vector_uchar(buffer, buffer + length));
    }
  } else {
    bool is_sequence =
      (PySequence_Check(object) != 0) &&
      (PyObject_HasAttrString(object, "__len__") != 0);
    bool is_instance = false;

    const DCClass *dclass = nullptr;
    const DCPackerInterface *current_field = packer->get_current_field();
    if (current_field != nullptr) {
      const DCClassParameter *class_param = current_field->as_class_parameter();
      if (class_param != nullptr) {
        dclass = class_param->get_class();

        if (dc_class_has_class_def(dclass)) {
          PyObject *class_def = dc_class_get_class_def(dclass);
          is_instance = (PyObject_IsInstance(object, class_def) != 0);
          Py_DECREF(class_def);
        }
      }
    }

    if (dclass != nullptr && (is_instance || !is_sequence)) {
      pack_class_object(packer, dclass, object);
    } else if (is_sequence) {
      packer->push();
      int size = (int)PySequence_Size(object);
      for (int i = 0; i < size; ++i) {
        PyObject *element = PySequence_GetItem(object, i);
        if (element != nullptr) {
          dc_packer_pack_object(packer, element);
          Py_DECREF(element);
        } else {
          std::cerr << "Unable to extract item " << i << " from sequence.\n";
        }
      }
      packer->pop();
    } else {
      std::ostringstream strm;
      strm << "Don't know how to pack object: " << get_pystr(object);
      nassert_raise(strm.str());
    }
  }
}

PyObject *dc_packer_unpack_object(DCPacker *packer) {
  PyObject *object = nullptr;

  DCPackType pack_type = packer->get_pack_type();

  switch (pack_type) {
  case PT_invalid:
    object = Py_NewRef(Py_None);
    packer->unpack_skip();
    break;

  case PT_double:
    {
      double value = packer->unpack_double();
      object = PyFloat_FromDouble(value);
    }
    break;

  case PT_int:
    {
      int value = packer->unpack_int();
      object = PyLong_FromLong(value);
    }
    break;

  case PT_uint:
    {
      unsigned int value = packer->unpack_uint();
      object = PyLong_FromUnsignedLong(value);
    }
    break;

  case PT_int64:
    {
      int64_t value = packer->unpack_int64();
      object = PyLong_FromLongLong(value);
    }
    break;

  case PT_uint64:
    {
      uint64_t value = packer->unpack_uint64();
      object = PyLong_FromUnsignedLongLong(value);
    }
    break;

  case PT_blob:
    {
      std::string str;
      packer->unpack_string(str);
      object = PyBytes_FromStringAndSize(str.data(), str.size());
    }
    break;

  case PT_string:
    {
      std::string str;
      packer->unpack_string(str);
      object = PyUnicode_FromStringAndSize(str.data(), str.size());
      if (object == nullptr) {
        nassert_raise("Unable to decode UTF-8 string; use blob type for binary data");
        return nullptr;
      }
    }
    break;

  case PT_class:
    {
      const DCClassParameter *class_param =
        packer->get_current_field()->as_class_parameter();
      if (class_param != nullptr) {
        const DCClass *dclass = class_param->get_class();
        if (dc_class_has_class_def(dclass)) {
          object = unpack_class_object(packer, dclass);
          if (object == nullptr) {
            std::cerr << "Unable to construct object of class "
                 << dclass->get_name() << "\n";
          } else {
            break;
          }
        }
      }
    }
    // Fall through (if no constructor)

  default:
    {
      object = PyList_New(0);

      packer->push();
      while (packer->more_nested_fields()) {
        PyObject *element = dc_packer_unpack_object(packer);
        PyList_Append(object, element);
        Py_DECREF(element);
      }
      packer->pop();

      if (pack_type != PT_array) {
        PyObject *tuple = PyList_AsTuple(object);
        Py_DECREF(object);
        object = tuple;
      }
    }
    break;
  }

  nassertr(object != nullptr, nullptr);
  return object;
}

// =========================================================================
// Internal helpers
// =========================================================================

static void pack_class_object(DCPacker *packer, const DCClass *dclass,
                              PyObject *object) {
  packer->push();
  while (packer->more_nested_fields() && !packer->had_pack_error()) {
    const DCField *field = packer->get_current_field()->as_field();
    nassertv(field != nullptr);
    get_class_element(packer, dclass, object, field);
  }
  packer->pop();
}

static PyObject *unpack_class_object(DCPacker *packer,
                                     const DCClass *dclass) {
  PyObject *class_def = dc_class_get_class_def(dclass);
  nassertr(class_def != nullptr, nullptr);

  PyObject *object = nullptr;

  if (!dclass->has_constructor()) {
    object = PyObject_CallNoArgs(class_def);
    if (object == nullptr) {
      return nullptr;
    }
  }

  packer->push();
  if (object == nullptr && packer->more_nested_fields()) {
    const DCField *field = packer->get_current_field()->as_field();
    nassertr(field != nullptr, object);
    nassertr(field == dclass->get_constructor(), object);

    set_class_element(packer, class_def, object, field);

    if (object == nullptr) {
      return nullptr;
    }
  }
  while (packer->more_nested_fields()) {
    const DCField *field = packer->get_current_field()->as_field();
    nassertr(field != nullptr, object);

    set_class_element(packer, class_def, object, field);
  }
  packer->pop();

  return object;
}

static void set_class_element(DCPacker *packer, PyObject *class_def,
                              PyObject *&object, const DCField *field) {
  std::string field_name = field->get_name();
  DCPackType pack_type = packer->get_pack_type();

  if (field_name.empty()) {
    switch (pack_type) {
    case PT_class:
    case PT_switch:
      packer->push();
      while (packer->more_nested_fields()) {
        const DCField *nested = packer->get_current_field()->as_field();
        nassertv(nested != nullptr);
        nassertv(object != nullptr);
        set_class_element(packer, class_def, object, nested);
      }
      packer->pop();
      break;

    default:
      packer->unpack_skip();
    }

  } else {
    PyObject *element = dc_packer_unpack_object(packer);

    if (pack_type == PT_field) {
      if (object == nullptr) {
        object = PyObject_CallObject(class_def, element);
      } else {
        if (PyObject_HasAttrString(object, (char *)field_name.c_str())) {
          PyObject *func = PyObject_GetAttrString(object, (char *)field_name.c_str());
          if (func != nullptr) {
            PyObject *result = PyObject_CallObject(func, element);
            Py_XDECREF(result);
            Py_DECREF(func);
          }
        }
      }
    } else {
      nassertv(object != nullptr);
      PyObject_SetAttrString(object, (char *)field_name.c_str(), element);
    }

    Py_DECREF(element);
  }
}

static void get_class_element(DCPacker *packer, const DCClass *dclass,
                              PyObject *object, const DCField *field) {
  std::string field_name = field->get_name();
  DCPackType pack_type = packer->get_pack_type();

  if (field_name.empty()) {
    switch (pack_type) {
    case PT_class:
    case PT_switch:
      packer->push();
      while (packer->more_nested_fields() && !packer->had_pack_error()) {
        const DCField *nested = packer->get_current_field()->as_field();
        nassertv(nested != nullptr);
        get_class_element(packer, dclass, object, nested);
      }
      packer->pop();
      break;

    default:
      packer->pack_default_value();
    }

  } else {
    dc_class_pack_required_field(dclass, *packer, object, field);
  }
}

// =========================================================================
// Utility
// =========================================================================

std::string get_pystr(PyObject *value) {
  if (value == nullptr) {
    return "(null)";
  }

  PyObject *str = PyObject_Str(value);
  if (str != nullptr) {
    std::string result = PyUnicode_AsUTF8(str);
    Py_DECREF(str);
    return result;
  }

  PyObject *repr = PyObject_Repr(value);
  if (repr != nullptr) {
    std::string result = PyUnicode_AsUTF8(repr);
    Py_DECREF(repr);
    return result;
  }

  PyTypeObject *type = Py_TYPE(value);
  if (type != nullptr) {
    PyObject *typestr = PyObject_Str((PyObject *)type);
    if (typestr != nullptr) {
      std::string result = PyUnicode_AsUTF8(typestr);
      Py_DECREF(typestr);
      return result;
    }
  }

  return "(invalid object)";
}

}  // namespace dc_python
