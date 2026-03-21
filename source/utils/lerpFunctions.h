/**
 * PANDA 3D SOFTWARE
 * Copyright (c) Carnegie Mellon University.  All rights reserved.
 *
 * All use of this software is subject to the terms of the revised BSD
 * license.  You should have received a copy of this license along
 * with this source code in a file named "LICENSE."
 *
 * @file lerpFunctions.h
 * @author brian
 * @date 2021-05-03
 */

#ifndef LERP_FUNCTIONS_H
#define LERP_FUNCTIONS_H

#include <cmath>
#include "mathutil_misc.h"
#include "luse.h"

/**
 * Manual quaternion slerp since LQuaternion::slerp is not available
 * in Panda3D 1.11.0.
 */
template<class Q>
INLINE Q quat_slerp(const Q &q1, const Q &q2, float t) {
  typedef decltype(q1.get_r()) FT;
  FT dot = q1.get_r() * q2.get_r() + q1.get_i() * q2.get_i() +
           q1.get_j() * q2.get_j() + q1.get_k() * q2.get_k();
  Q q2b = q2;
  if (dot < 0) {
    dot = -dot;
    q2b = Q(-q2.get_r(), -q2.get_i(), -q2.get_j(), -q2.get_k());
  }
  if (dot > (FT)0.9999) {
    // Very close, use linear interpolation
    Q result = Q(
      q1.get_r() + t * (q2b.get_r() - q1.get_r()),
      q1.get_i() + t * (q2b.get_i() - q1.get_i()),
      q1.get_j() + t * (q2b.get_j() - q1.get_j()),
      q1.get_k() + t * (q2b.get_k() - q1.get_k()));
    result.normalize();
    return result;
  }
  FT theta = std::acos(dot);
  FT sin_theta = std::sin(theta);
  FT w1 = std::sin(((FT)1 - t) * theta) / sin_theta;
  FT w2 = std::sin(t * theta) / sin_theta;
  return Q(
    w1 * q1.get_r() + w2 * q2b.get_r(),
    w1 * q1.get_i() + w2 * q2b.get_i(),
    w1 * q1.get_j() + w2 * q2b.get_j(),
    w1 * q1.get_k() + w2 * q2b.get_k());
}

BEGIN_PUBLISH

template <class T>
inline T LoopingLerp( float flPercent, T flFrom, T flTo )
{
	T s = flTo * flPercent + flFrom * ( 1.0f - flPercent );
	return s;
}

inline float LoopingLerp( float flPercent, float flFrom, float flTo )
{
	if ( std::fabs( flTo - flFrom ) >= 0.5f )
	{
		if ( flFrom < flTo )
			flFrom += 1.0f;
		else
			flTo += 1.0f;
	}

	float s = flTo * flPercent + flFrom * ( 1.0f - flPercent );

	s = s - (int)( s );
	if ( s < 0.0f )
		s = s + 1.0f;

	return s;
}

template <class T>
inline T Lerp_Hermite( float t, const T& p0, const T& p1, const T& p2 )
{
	T d1 = p1 - p0;
	T d2 = p2 - p1;

	T output;
	float tSqr = t * t;
	float tCube = t * tSqr;

	output = p1 * ( 2 * tCube - 3 * tSqr + 1 );
	output += p2 * ( -2 * tCube + 3 * tSqr );
	output += d1 * ( tCube - 2 * tSqr + t );
	output += d2 * ( tCube - tSqr );

	return output;
}

#ifndef CPPPARSER
/**
 * Specialization of tlerp for quaternions.
 */
template<>
INLINE LQuaternionf
tlerp<LQuaternionf>(float perct, const LQuaternionf &q1, const LQuaternionf &q2) {
  if (q1 == q2) {
    return q1;
  }

  LQuaternionf dest = quat_slerp(q1, q2, perct);
  return dest;
}

/**
 * Specialization of tlerp for quaternions.
 */
template<>
INLINE LQuaterniond
tlerp<LQuaterniond>(float perct, const LQuaterniond &q1, const LQuaterniond &q2) {
  if (q1 == q2) {
    return q1;
  }

  LQuaterniond dest = quat_slerp(q1, q2, perct);
  return dest;
}
#endif  // CPPPARSER

template<class T>
INLINE T tlerp_angles(float perct, const T &a, const T &b) {
	return tlerp(perct, a, b);
}

/**
 * Interpolates euler angles with quaternions.
 */
INLINE LVecBase3f
tlerp_angles(float perct, const LVecBase3f &a, const LVecBase3f &b) {
  if (a == b) {
    return a;
  }

  LQuaternionf quat_a;
  quat_a.set_hpr(a);

  LQuaternionf quat_b;
  quat_b.set_hpr(b);

  LQuaternionf dest = quat_slerp(quat_a, quat_b, perct);
  return dest.get_hpr();
}

/**
 * Interpolates euler angles with quaternions.
 */
INLINE LVecBase3d
tlerp_angles(float perct, const LVecBase3d &a, const LVecBase3d &b) {
  if (a == b) {
    return a;
  }

  LQuaterniond quat_a;
  quat_a.set_hpr(a);

  LQuaterniond quat_b;
  quat_b.set_hpr(b);

  LQuaterniond dest = quat_slerp(quat_a, quat_b, (double)perct);
  return dest.get_hpr();
}

#ifndef CPPPARSER
template<>
inline LQuaternionf Lerp_Hermite<LQuaternionf>(float t, const LQuaternionf &p0, const LQuaternionf &p1, const LQuaternionf &p2) {
	return tlerp(t, p1, p2);
}

template<>
inline LQuaterniond Lerp_Hermite<LQuaterniond>(float t, const LQuaterniond &p0, const LQuaterniond &p1, const LQuaterniond &p2) {
	return tlerp(t, p1, p2);
}
#endif  // CPPPARSER

template <class T>
inline T Derivative_Hermite( float t, const T& p0, const T& p1, const T& p2 )
{
	T d1 = p1 - p0;
	T d2 = p2 - p1;

	T output;
	float tSqr = t * t;

	output = p1 * ( 6 * tSqr - 6 * t );
	output += p2 * ( -6 * tSqr + 6 * t );
	output += d1 * ( 3 * tSqr - 4 * t + 1 );
	output += d2 * ( 3 * tSqr - 2 * t );

	return output;
}

template<class Type>
inline void Lerp_Clamp(const Type &val) {
}

inline void Lerp_Clamp( int val )
{
}

inline void Lerp_Clamp( float val )
{
}

inline void Lerp_Clamp( const LVector3f& val )
{
}

inline void Lerp_Clamp( const LVector4f &val )
{
}

inline void Lerp_Clamp( const LVector2f &val )
{
}

// If we have a range checked var, then we can clamp to its limits.
//template <class T, int minValue, int maxValue, int startValue>
//inline void Lerp_Clamp( CRangeCheckedVar<T, minValue, maxValue, startValue>& val )
//{
//	val.Clamp();
//}

template <class T>
inline T LoopingLerp_Hermite( float t, T p0, T p1, T p2 )
{
	return Lerp_Hermite( t, p0, p1, p2 );
}

inline float LoopingLerp_Hermite( float t, float p0, float p1, float p2 )
{
	if ( fabs( p1 - p0 ) > 0.5f )
	{
		if ( p0 < p1 )
			p0 += 1.0f;
		else
			p1 += 1.0f;
	}

	if ( fabs( p2 - p1 ) > 0.5f )
	{
		if ( p1 < p2 )
		{
			p1 += 1.0f;

			// see if we need to fix up p0
			// important for vars that are decreasing from p0->p1->p2 where
			// p1 is fixed up relative to p2, eg p0 = 0.2, p1 = 0.1, p2 = 0.9
			if ( abs( p1 - p0 ) > 0.5 )
			{
				if ( p0 < p1 )
					p0 += 1.0f;
				else
					p1 += 1.0f;
			}
		}
		else
		{
			p2 += 1.0f;
		}
	}

	float s = Lerp_Hermite( t, p0, p1, p2 );

	s = s - (int)( s );
	if ( s < 0.0f )
	{
		s = s + 1.0f;
	}

	return s;
}

END_PUBLISH

// NOTE: C_AnimationLayer has its own versions of these functions in animationlayer.h.

#endif // LERP_FUNCTIONS_H