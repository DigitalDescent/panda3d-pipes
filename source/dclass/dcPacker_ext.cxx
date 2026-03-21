/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


#include "dcPacker_ext.h"
#include "dcClass_ext.h"
#include "dcField_ext.h"

#include "dcClassParameter.h"

#ifdef HAVE_PYTHON

/**
 * Packs the Python object of whatever type into the packer.
 */
void Extension<DCPacker>::
pack_object(PyObject *object) {
  DCPackType pack_type = _this->get_pack_type();

  switch(pack_type) {
  case PT_int64:
    if (PyLong_Check(object)) {
      _this->pack_int64(PyLong_AsLongLong(object));
      return;
    }
    break;

  case PT_uint64:
    if (PyLong_Check(object)) {
      _this->pack_uint64(PyLong_AsUnsignedLongLong(object));
      return;
    }
    break;

  case PT_int:
    if (PyLong_Check(object)) {
      _this->pack_int(PyLong_AsLong(object));
      return;
    }
    break;

  case PT_uint:
    if (PyLong_Check(object)) {
      _this->pack_uint(PyLong_AsUnsignedLong(object));
      return;
    }
    break;

  default:
    break;
  }

  if (PyLong_Check(object)) {
    _this->pack_int(PyLong_AsLong(object));
  } else if (PyFloat_Check(object)) {
    _this->pack_double(PyFloat_AS_DOUBLE(object));
  } else if (PyUnicode_Check(object)) {
    const char *buffer;
    Py_ssize_t length;
    buffer = PyUnicode_AsUTF8AndSize(object, &length);
    if (buffer) {
      _this->pack_string(std::string(buffer, length));
    }
  } else if (PyBytes_Check(object)) {
    const unsigned char *buffer;
    Py_ssize_t length;
    PyBytes_AsStringAndSize(object, (char **)&buffer, &length);
    if (buffer) {
      _this->pack_blob(vector_uchar(buffer, buffer + length));
    }
  } else {
    bool is_sequence =
      (PySequence_Check(object) != 0) &&
      (PyObject_HasAttrString(object, "__len__") != 0);
    bool is_instance = false;

    const DCClass *dclass = nullptr;
    const DCPackerInterface *current_field = _this->get_current_field();
    if (current_field != nullptr) {
      const DCClassParameter *class_param = _this->get_current_field()->as_class_parameter();
      if (class_param != nullptr) {
        dclass = class_param->get_class();

        if (invoke_extension(dclass).has_class_def()) {
          PyObject *class_def = invoke_extension(dclass).get_class_def();
          is_instance = (PyObject_IsInstance(object, class_def) != 0);
          Py_DECREF(class_def);
        }
      }
    }

    if (dclass != nullptr && (is_instance || !is_sequence)) {
      pack_class_object(dclass, object);
    } else if (is_sequence) {
      _this->push();
      int size = (int)PySequence_Size(object);
      for (int i = 0; i < size; ++i) {
        PyObject *element = PySequence_GetItem(object, i);
        if (element != nullptr) {
          pack_object(element);
          Py_DECREF(element);
        } else {
          std::cerr << "Unable to extract item " << i << " from sequence.\n";
        }
      }
      _this->pop();
    } else {
      std::ostringstream strm;
      strm << "Don't know how to pack object: "
           << Extension<DCField>::get_pystr(object);
      nassert_raise(strm.str());
    }
  }
}

/**
 * Unpacks a Python object of the appropriate type from the stream for the
 * current field.
 */
PyObject *Extension<DCPacker>::
unpack_object() {
  PyObject *object = nullptr;

  DCPackType pack_type = _this->get_pack_type();

  switch (pack_type) {
  case PT_invalid:
    object = Py_NewRef(Py_None);
    _this->unpack_skip();
    break;

  case PT_double:
    {
      double value = _this->unpack_double();
      object = PyFloat_FromDouble(value);
    }
    break;

  case PT_int:
    {
      int value = _this->unpack_int();
      object = PyLong_FromLong(value);
    }
    break;

  case PT_uint:
    {
      unsigned int value = _this->unpack_uint();
      object = PyLong_FromUnsignedLong(value);
    }
    break;

  case PT_int64:
    {
      int64_t value = _this->unpack_int64();
      object = PyLong_FromLongLong(value);
    }
    break;

  case PT_uint64:
    {
      uint64_t value = _this->unpack_uint64();
      object = PyLong_FromUnsignedLongLong(value);
    }
    break;

  case PT_blob:
    {
      std::string str;
      _this->unpack_string(str);
      object = PyBytes_FromStringAndSize(str.data(), str.size());
    }
    break;

  case PT_string:
    {
      std::string str;
      _this->unpack_string(str);
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
        _this->get_current_field()->as_class_parameter();
      if (class_param != nullptr) {
        const DCClass *dclass = class_param->get_class();
        if (invoke_extension(dclass).has_class_def()) {
          object = unpack_class_object(dclass);
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

      _this->push();
      while (_this->more_nested_fields()) {
        PyObject *element = unpack_object();
        PyList_Append(object, element);
        Py_DECREF(element);
      }
      _this->pop();

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

/**
 * Packs a class object into the packer.
 */
void Extension<DCPacker>::
pack_class_object(const DCClass *dclass, PyObject *object) {
  _this->push();
  while (_this->more_nested_fields() && !_this->had_pack_error()) {
    const DCField *field = _this->get_current_field()->as_field();
    nassertv(field != nullptr);
    get_class_element(dclass, object, field);
  }
  _this->pop();
}

/**
 * Unpacks a class object from the packer.
 */
PyObject *Extension<DCPacker>::
unpack_class_object(const DCClass *dclass) {
  PyObject *class_def = invoke_extension(dclass).get_class_def();
  nassertr(class_def != nullptr, nullptr);

  PyObject *object = nullptr;

  if (!dclass->has_constructor()) {
    object = PyObject_CallNoArgs(class_def);
    if (object == nullptr) {
      return nullptr;
    }
  }

  _this->push();
  if (object == nullptr && _this->more_nested_fields()) {
    const DCField *field = _this->get_current_field()->as_field();
    nassertr(field != nullptr, object);
    nassertr(field == dclass->get_constructor(), object);

    set_class_element(class_def, object, field);

    if (object == nullptr) {
      return nullptr;
    }
  }
  while (_this->more_nested_fields()) {
    const DCField *field = _this->get_current_field()->as_field();
    nassertr(field != nullptr, object);

    set_class_element(class_def, object, field);
  }
  _this->pop();

  return object;
}

/**
 * Unpacks the current element and stuffs it on the Python class object.
 */
void Extension<DCPacker>::
set_class_element(PyObject *class_def, PyObject *&object,
                  const DCField *field) {
  std::string field_name = field->get_name();
  DCPackType pack_type = _this->get_pack_type();

  if (field_name.empty()) {
    switch (pack_type) {
    case PT_class:
    case PT_switch:
      _this->push();
      while (_this->more_nested_fields()) {
        const DCField *field = _this->get_current_field()->as_field();
        nassertv(field != nullptr);
        nassertv(object != nullptr);
        set_class_element(class_def, object, field);
      }
      _this->pop();
      break;

    default:
      _this->unpack_skip();
    }

  } else {
    PyObject *element = unpack_object();

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

/**
 * Gets the current element from the Python object and packs it.
 */
void Extension<DCPacker>::
get_class_element(const DCClass *dclass, PyObject *object,
                  const DCField *field) {
  std::string field_name = field->get_name();
  DCPackType pack_type = _this->get_pack_type();

  if (field_name.empty()) {
    switch (pack_type) {
    case PT_class:
    case PT_switch:
      _this->push();
      while (_this->more_nested_fields() && !_this->had_pack_error()) {
        const DCField *field = _this->get_current_field()->as_field();
        nassertv(field != nullptr);
        get_class_element(dclass, object, field);
      }
      _this->pop();
      break;

    default:
      _this->pack_default_value();
    }

  } else {
    invoke_extension(dclass).pack_required_field(*_this, object, field);
  }
}

#endif  // HAVE_PYTHON
