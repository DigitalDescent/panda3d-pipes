/**
 * Copyright (c) 2026, Digital Descent LLC
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 */


#include "interpolatedVariable.h"

ConfigVariableDouble iv_extrapolate_amount
("iv-extrapolate-amount", 0.25,
 PRC_DESC("Set how many seconds the client will extrapolate variables for."));

InterpolationContext *InterpolationContext::_head = nullptr;
bool InterpolationContext::_allow_extrapolation = false;
double InterpolationContext::_last_timestamp = 0;