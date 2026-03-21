/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


/**
 * Returns the number of fields in the list.
 */
INLINE int ChangeFrameList::
get_num_fields() const {
  return (int)_change_ticks.size();
}
