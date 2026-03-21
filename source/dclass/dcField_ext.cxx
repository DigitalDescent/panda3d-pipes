/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


#include "dcField_ext.h"
#include "dcPacker_ext.h"
#include "dcmsgtypes.h"

#include "datagram.h"
#include "pStatTimer.h"

#ifdef HAVE_PYTHON

/**
 * Packs the Python arguments from the indicated tuple into the packer.
 * Returns true on success, false on failure.
 *
 * It is assumed that the packer is currently positioned on this field.
 */
bool Extension<DCField>::
pack_args(DCPacker &packer, PyObject *sequence) const {
  nassertr(!packer.had_error(), false);
  nassertr(packer.get_current_field() == _this, false);

  invoke_extension(&packer).pack_object(sequence);
  if (!packer.had_error()) {
    return true;
  }

  if (!Notify::ptr()->has_assert_failed()) {
    std::ostringstream strm;
    PyObject *exc_type = PyExc_Exception;

    if (_this->as_parameter() != nullptr) {
      if (packer.had_pack_error()) {
        strm << "Incorrect arguments to field: " << _this->get_name()
             << " = " << get_pystr(sequence);
        exc_type = PyExc_TypeError;
      } else {
        strm << "Value out of range on field: " << _this->get_name()
             << " = " << get_pystr(sequence);
        exc_type = PyExc_ValueError;
      }
    } else {
      PyObject *tuple = PySequence_Tuple(sequence);
      if (tuple == nullptr) {
        strm << "Value for " << _this->get_name() << " not a sequence: "
             << get_pystr(sequence);
        exc_type = PyExc_TypeError;
      } else {
        if (packer.had_pack_error()) {
          strm << "Incorrect arguments to field: " << _this->get_name()
               << get_pystr(sequence);
          exc_type = PyExc_TypeError;
        } else {
          strm << "Value out of range on field: " << _this->get_name()
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

/**
 * Unpacks the values from the packer, beginning at the current point in the
 * unpack_buffer, into a Python tuple and returns the tuple.
 *
 * It is assumed that the packer is currently positioned on this field.
 */
PyObject *Extension<DCField>::
unpack_args(DCPacker &packer) const {
  nassertr(!packer.had_error(), nullptr);
  nassertr(packer.get_current_field() == _this, nullptr);

  size_t start_byte = packer.get_num_unpacked_bytes();
  PyObject *object = invoke_extension(&packer).unpack_object();

  if (!packer.had_error()) {
    return object;
  }

  if (!Notify::ptr()->has_assert_failed()) {
    std::ostringstream strm;
    PyObject *exc_type = PyExc_Exception;

    if (packer.had_pack_error()) {
      strm << "Data error unpacking field ";
      _this->output(strm, true);
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
           << _this->get_name() << ": " << get_pystr(object);
      exc_type = PyExc_ValueError;
    }

    std::string message = strm.str();
    PyErr_SetString(exc_type, message.c_str());
  }

  Py_XDECREF(object);
  return nullptr;
}

/**
 * Returns the string representation of the indicated Python object.
 */
std::string Extension<DCField>::
get_pystr(PyObject *value) {
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

#endif  // HAVE_PYTHON
