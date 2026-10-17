//! Dimension / distance measurement (고고학 산출물: 치수).
//!
//! Ported from `archphoto.archaeo.measure`. Computes metric distances between
//! 3D points in a stated [`SpatialFrame`], for artifact dimensions, wall
//! thickness, and independent length checks (`CHECK_LENGTH`). A distance
//! computed from the model is a DERIVED measurement (`derived == true`), not a
//! direct tape measurement.

use crate::crs::{LengthUnit, SpatialFrame};
use crate::{ContractResult, Point3D};

/// A distance between two 3D points, in `unit`.
///
/// `derived == true` means it was computed from the reconstructed model (not a
/// direct field measurement). `sigma` is a propagated uncertainty if known; it
/// is NOT the model's accuracy claim.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct Measurement {
    pub value: f64,
    pub unit: LengthUnit,
    pub point_a: Point3D,
    pub point_b: Point3D,
    pub derived: bool,
    pub sigma: Option<f64>,
}

impl Measurement {
    pub fn new(
        value: f64,
        unit: LengthUnit,
        point_a: Point3D,
        point_b: Point3D,
        derived: bool,
        sigma: Option<f64>,
    ) -> ContractResult<Self> {
        if !value.is_finite() || value < 0.0 {
            return Err("Measurement.value must be finite and >= 0".into());
        }
        if !point_a.iter().all(|c| c.is_finite()) || !point_b.iter().all(|c| c.is_finite()) {
            return Err("Measurement endpoint coordinates must be finite".into());
        }
        if let Some(s) = sigma
            && (!s.is_finite() || s < 0.0)
        {
            return Err("Measurement.sigma must be finite and >= 0".into());
        }
        Ok(Self {
            value,
            unit,
            point_a,
            point_b,
            derived,
            sigma,
        })
    }
}

/// Euclidean distance between `a` and `b`, in `frame` units.
pub fn measure_distance(
    a: Point3D,
    b: Point3D,
    frame: &SpatialFrame,
) -> ContractResult<Measurement> {
    if !a.iter().all(|c| c.is_finite()) || !b.iter().all(|c| c.is_finite()) {
        return Err("measure_distance endpoints must be finite".into());
    }
    let dx = b[0] - a[0];
    let dy = b[1] - a[1];
    let dz = b[2] - a[2];
    let d = (dx * dx + dy * dy + dz * dz).sqrt();
    Measurement::new(d, frame.unit, a, b, true, None)
}

/// Signed residual `measured - reference` (frame units).
///
/// Used to validate a model dimension against an independent reference length
/// (`CHECK_LENGTH`). The reference must come from independent surveying, never
/// from the same points used to fit the model.
pub fn length_residual(measured: &Measurement, reference_value: f64) -> ContractResult<f64> {
    if !reference_value.is_finite() || reference_value <= 0.0 {
        return Err("reference_value must be finite and positive".into());
    }
    Ok(measured.value - reference_value)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:test", LengthUnit::Millimeter).unwrap()
    }

    #[test]
    fn euclidean_distance_is_marked_derived_with_frame_unit() {
        let m = measure_distance([0.0, 0.0, 0.0], [3.0, 4.0, 0.0], &frame()).unwrap();
        assert!((m.value - 5.0).abs() < 1e-12);
        assert_eq!(m.unit, LengthUnit::Millimeter);
        assert!(m.derived);
    }

    #[test]
    fn length_residual_computes_signed_difference_and_rejects_nonpositive() {
        let m = measure_distance([0.0, 0.0, 0.0], [3.0, 4.0, 0.0], &frame()).unwrap();
        assert!((length_residual(&m, 5.0).unwrap() - 0.0).abs() < 1e-12);
        assert!((length_residual(&m, 4.5).unwrap() - 0.5).abs() < 1e-12);
        assert!(length_residual(&m, 0.0).is_err());
        assert!(length_residual(&m, -1.0).is_err());
        assert!(length_residual(&m, f64::NAN).is_err());
    }

    #[test]
    fn non_finite_endpoints_are_refused() {
        assert!(measure_distance([f64::NAN, 0.0, 0.0], [1.0, 0.0, 0.0], &frame()).is_err());
    }
}
