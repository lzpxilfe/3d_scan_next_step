//! Rigid transforms between explicitly stated frames.
//!
//! Ported from Python `archphoto.geom.crs.Transform3D`. 05 §3: the method,
//! parameters, and version used for a coordinate transform must be recorded so
//! results are reproducible — [`Transform3D::method`] and
//! [`Transform3D::software_version`] carry that provenance and default to
//! empty (never guessed).
//!
//! Convention (explicit, per Python reference):
//!   1. input interpreted in `source` axis order and unit;
//!   2. axis order normalized to East-North;
//!   3. coordinates converted `source.unit` → `target.unit`;
//!   4. unit-quaternion rotation applied, then `translation` (in
//!      `target.unit`) added;
//!   5. result written in `target` axis order.
//!
//! Vertical datums are NOT mixed silently: differing datums refuse
//! (`Err`), because converting ellipsoidal ↔ orthometric heights needs an
//! explicit geoid model that is not applied here.

use crate::crs::{AxisOrder, SpatialFrame};
use crate::{ContractResult, Point3D};

/// Rigid transform from frame `source` to frame `target`.
///
/// Rotation stored as a quaternion (**x, y, z, w**); translation expressed in
/// `target.unit`.
#[derive(Debug, Clone, PartialEq)]
pub struct Transform3D {
    pub source: SpatialFrame,
    pub target: SpatialFrame,
    pub quaternion_xyzw: [f64; 4],
    pub translation: Point3D,
    /// e.g. "Helmert-7param", "similarity-RANSAC" — provenance, not decoration.
    pub method: String,
    /// code/engine version that computed this transform.
    pub software_version: String,
}

impl Transform3D {
    #[must_use]
    pub fn new(
        source: SpatialFrame,
        target: SpatialFrame,
        quaternion_xyzw: [f64; 4],
        translation: Point3D,
    ) -> Self {
        Transform3D {
            source,
            target,
            quaternion_xyzw,
            translation,
            method: String::new(),
            software_version: String::new(),
        }
    }

    #[must_use]
    pub fn with_method(mut self, method: impl Into<String>) -> Self {
        self.method = method.into();
        self
    }

    #[must_use]
    pub fn with_software_version(mut self, software_version: impl Into<String>) -> Self {
        self.software_version = software_version.into();
        self
    }

    /// Map `point` — given in `source` coordinates — into the `target` frame.
    pub fn apply(&self, point: Point3D) -> ContractResult<Point3D> {
        if self.source.crs_id.is_empty() || self.target.crs_id.is_empty() {
            return Err("Transform3D frames must have explicit crs_id".into());
        }
        if self.source.vertical_datum != self.target.vertical_datum {
            return Err(
                "Vertical datums differ; a geoid/height transform is required and is not \
                 applied here. Refusing to mix height references silently."
                    .into(),
            );
        }
        if !point.iter().all(|v| v.is_finite())
            || !self.translation.iter().all(|v| v.is_finite())
            || !self.quaternion_xyzw.iter().all(|v| v.is_finite())
        {
            return Err("Transform3D point, quaternion, and translation must be finite".into());
        }

        let mut xyz = point;
        // 2. source axis order -> canonical East-North
        if self.source.axis_order == AxisOrder::NorthEast {
            xyz.swap(0, 1);
        }
        // 3. unit conversion source -> target
        let k = self.source.unit.factor_to(self.target.unit);
        let xyz = [xyz[0] * k, xyz[1] * k, xyz[2] * k];
        // 4. rotate + translate (translation is in target.unit)
        let r = rotate_quat(self.quaternion_xyzw, xyz)?;
        let xyz = [
            r[0] + self.translation[0],
            r[1] + self.translation[1],
            r[2] + self.translation[2],
        ];
        // 5. canonical East-North -> target axis order
        let mut xyz = xyz;
        if self.target.axis_order == AxisOrder::NorthEast {
            xyz.swap(0, 1);
        }
        Ok(xyz)
    }
}

/// Rotate vector `v` by a unit quaternion (x, y, z, w).
///
/// Ported verbatim from Python `_rotate_quat`: normalizes first, refuses a
/// zero-norm quaternion (`Err` for what Python raised ValueError), then
/// applies `v' = v + 2w(q×v) + 2q×(q×v)`.
pub fn rotate_quat(quaternion_xyzw: [f64; 4], v: Point3D) -> ContractResult<Point3D> {
    if !quaternion_xyzw.iter().all(|x| x.is_finite()) || !v.iter().all(|x| x.is_finite()) {
        return Err("Quaternion and vector components must be finite".into());
    }
    let [qx, qy, qz, qw] = quaternion_xyzw;
    let norm = (qx * qx + qy * qy + qz * qz + qw * qw).sqrt();
    if norm == 0.0 || !norm.is_finite() {
        return Err("Quaternion has zero norm".into());
    }
    let (qx, qy, qz, qw) = (qx / norm, qy / norm, qz / norm, qw / norm);

    let (vx, vy, vz) = (v[0], v[1], v[2]);
    // t = 2 * cross(q.xyz, v)
    let tx = 2.0 * (qy * vz - qz * vy);
    let ty = 2.0 * (qz * vx - qx * vz);

    let tz = 2.0 * (qx * vy - qy * vx);
    // v' = v + qw * t + cross(q.xyz, t)
    Ok([
        vx + qw * tx + (qy * tz - qz * ty),
        vy + qw * ty + (qz * tx - qx * tz),
        vz + qw * tz + (qx * ty - qy * tx),
    ])
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::{LengthUnit, VerticalDatum};

    const HALF_SQRT2: f64 = std::f64::consts::FRAC_1_SQRT_2;

    fn frame(crs: &str, unit: LengthUnit, datum: VerticalDatum) -> SpatialFrame {
        SpatialFrame::new(crs, unit)
            .unwrap()
            .with_vertical_datum(datum)
    }

    fn approx(a: Point3D, b: Point3D) {
        for (x, y) in a.iter().zip(b.iter()) {
            assert!((x - y).abs() < 1e-9, "{a:?} vs {b:?}");
        }
    }

    #[test]
    fn identity_transform_changes_nothing() {
        let t = Transform3D::new(
            frame("A", LengthUnit::Meter, VerticalDatum::Orthometric),
            frame("B", LengthUnit::Meter, VerticalDatum::Orthometric),
            [0.0, 0.0, 0.0, 1.0],
            [0.0, 0.0, 0.0],
        );
        approx(t.apply([3.5, -2.0, 7.25]).unwrap(), [3.5, -2.0, 7.25]);
    }

    #[test]
    fn pure_unit_conversion_scales_all_axes() {
        // m -> mm : ×1000, no rotation, no translation.
        let t = Transform3D::new(
            frame("A", LengthUnit::Meter, VerticalDatum::Orthometric),
            frame("B", LengthUnit::Millimeter, VerticalDatum::Orthometric),
            [0.0, 0.0, 0.0, 1.0],
            [0.0, 0.0, 0.0],
        );
        approx(
            t.apply([0.5, -1.25, 2.0]).unwrap(),
            [500.0, -1250.0, 2000.0],
        );
    }

    #[test]
    fn north_east_source_is_swapped_into_east_north() {
        // Stored (northing, easting) becomes (easting, northing).
        let source = SpatialFrame::new("NE", LengthUnit::Meter)
            .unwrap()
            .with_vertical_datum(VerticalDatum::Orthometric)
            .with_axis_order(AxisOrder::NorthEast);
        let target = frame("B", LengthUnit::Meter, VerticalDatum::Orthometric);
        let t = Transform3D::new(source, target, [0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0]);
        approx(t.apply([10.0, 20.0, 5.0]).unwrap(), [20.0, 10.0, 5.0]);
    }

    #[test]
    fn north_east_target_swaps_the_result_back() {
        let target = SpatialFrame::new("NE", LengthUnit::Meter)
            .unwrap()
            .with_vertical_datum(VerticalDatum::Orthometric)
            .with_axis_order(AxisOrder::NorthEast);
        let t = Transform3D::new(
            frame("A", LengthUnit::Meter, VerticalDatum::Orthometric),
            target,
            [0.0, 0.0, 0.0, 1.0],
            [0.0, 0.0, 0.0],
        );
        approx(t.apply([10.0, 20.0, 5.0]).unwrap(), [20.0, 10.0, 5.0]);
    }

    #[test]
    fn rotation_quaternion_90deg_about_z() {
        // +90° about z: (1,0,0) -> (0,1,0)
        let t = Transform3D::new(
            frame("A", LengthUnit::Meter, VerticalDatum::Orthometric),
            frame("B", LengthUnit::Meter, VerticalDatum::Orthometric),
            [0.0, 0.0, HALF_SQRT2, HALF_SQRT2],
            [0.0, 0.0, 0.0],
        );
        approx(t.apply([1.0, 0.0, 0.0]).unwrap(), [0.0, 1.0, 0.0]);
        approx(t.apply([0.0, 1.0, 0.0]).unwrap(), [-1.0, 0.0, 0.0]);
    }

    #[test]
    fn full_pipeline_axis_unit_rotation_translation() {
        // source: NE order, centimeter, LOCAL height (site grid)
        //   stored (200, 100, 50) cm -> EN meters (1.0, 2.0, 0.5)
        // rotate +90° about z: (1,2,0.5) -> (-2,1,0.5)
        // translate (10,0,0) m: -> (8.0, 1.0, 0.5)
        let source = SpatialFrame::new("LOCAL:site", LengthUnit::Centimeter)
            .unwrap()
            .with_vertical_datum(VerticalDatum::Local)
            .with_axis_order(AxisOrder::NorthEast);
        let target = frame("LOCAL:site-m", LengthUnit::Meter, VerticalDatum::Local);
        let t = Transform3D::new(
            source,
            target,
            [0.0, 0.0, HALF_SQRT2, HALF_SQRT2],
            [10.0, 0.0, 0.0],
        )
        .with_method("test-fixed-pose");
        approx(t.apply([200.0, 100.0, 50.0]).unwrap(), [8.0, 1.0, 0.5]);
    }

    #[test]
    fn differing_vertical_datums_are_refused() {
        let t = Transform3D::new(
            frame("A", LengthUnit::Meter, VerticalDatum::Orthometric),
            frame("B", LengthUnit::Meter, VerticalDatum::Ellipsoidal),
            [0.0, 0.0, 0.0, 1.0],
            [0.0, 0.0, 0.0],
        );
        let err = t.apply([0.0, 0.0, 0.0]).unwrap_err();
        assert!(err.contains("geoid"), "{err}");
        assert!(err.contains("Refusing to mix height references"), "{err}");
    }

    #[test]
    fn zero_or_nan_quaternion_is_refused() {
        let t = Transform3D::new(
            frame("A", LengthUnit::Meter, VerticalDatum::Orthometric),
            frame("B", LengthUnit::Meter, VerticalDatum::Orthometric),
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        );
        let err = t.apply([1.0, 1.0, 1.0]).unwrap_err();
        assert!(err.contains("zero norm"), "{err}");

        let t_nan = Transform3D::new(
            frame("A", LengthUnit::Meter, VerticalDatum::Orthometric),
            frame("B", LengthUnit::Meter, VerticalDatum::Orthometric),
            [f64::NAN, 0.0, 0.0, 1.0],
            [0.0, 0.0, 0.0],
        );
        assert!(t_nan.apply([1.0, 1.0, 1.0]).is_err());
    }

    #[test]
    fn non_unit_quaternion_is_normalized_automatically() {
        // A uniform scale of the 90°-about-z quaternion strictly preserves the
        // rotation (the 4-vector direction is unchanged).
        let t = Transform3D::new(
            frame("A", LengthUnit::Meter, VerticalDatum::Orthometric),
            frame("B", LengthUnit::Meter, VerticalDatum::Orthometric),
            [0.0, 0.0, 2.0 * HALF_SQRT2, 2.0 * HALF_SQRT2],
            [0.0, 0.0, 0.0],
        );
        approx(t.apply([1.0, 0.0, 0.0]).unwrap(), [0.0, 1.0, 0.0]);
    }
}
