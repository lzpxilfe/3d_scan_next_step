//! A plane primitive for section/profile cutting.
//!
//! Ported from Python `archphoto.geom.plane`. A plane is a point plus a unit
//! normal in a stated SpatialFrame — used to cut meshes into archaeological
//! sections (05 §4: 계산된 단면선).

use crate::crs::SpatialFrame;
use crate::{ContractResult, Point3D};

/// A plane: `normal` (normalized on construction) at `point`, all in `frame`
/// coordinates.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct Plane {
    pub point: Point3D,
    pub normal: Point3D,
    pub frame: SpatialFrame,
}

impl Plane {
    /// Refuses a zero-length or non-finite normal and normalizes in place,
    /// mirroring Python `Plane.__post_init__`.
    pub fn new(point: Point3D, normal: Point3D, frame: SpatialFrame) -> ContractResult<Self> {
        if !point.iter().all(|v| v.is_finite()) || !normal.iter().all(|v| v.is_finite()) {
            return Err("Plane point and normal coordinates must be finite".into());
        }
        let (nx, ny, nz) = (normal[0], normal[1], normal[2]);
        let n = (nx * nx + ny * ny + nz * nz).sqrt();
        if n == 0.0 || !n.is_finite() {
            return Err("Plane normal must be non-zero".into());
        }
        Ok(Plane {
            point,
            normal: [nx / n, ny / n, nz / n],
            frame,
        })
    }

    /// Positive on the normal side, negative on the other, 0 on the plane.
    pub fn signed_distance(&self, p: Point3D) -> f64 {
        self.normal[0] * (p[0] - self.point[0])
            + self.normal[1] * (p[1] - self.point[1])
            + self.normal[2] * (p[2] - self.point[2])
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::{LengthUnit, SpatialFrame};

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:test", LengthUnit::Meter).unwrap()
    }

    #[test]
    fn normal_is_normalized_and_zero_or_non_finite_is_refused() {
        let plane = Plane::new([0.0, 0.0, 0.0], [0.0, 0.0, 5.0], frame()).unwrap();
        assert!((plane.normal[2] - 1.0).abs() < 1e-12);
        let err = Plane::new([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], frame()).unwrap_err();
        assert!(err.contains("must be non-zero"), "{err}");
        assert!(Plane::new([0.0, 0.0, 0.0], [f64::NAN, 0.0, 1.0], frame()).is_err());
        assert!(Plane::new([f64::INFINITY, 0.0, 0.0], [0.0, 0.0, 1.0], frame()).is_err());
    }

    #[test]
    fn signed_distance_side_convention() {
        // z = 0 plane with +z normal: z>0 positive, z<0 negative, on-plane 0.
        let plane = Plane::new([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], frame()).unwrap();
        assert!((plane.signed_distance([1.0, 2.0, 3.0]) - 3.0).abs() < 1e-12);
        assert!(plane.signed_distance([0.5, -0.5, -0.25]) < 0.0);
        assert!(plane.signed_distance([0.5, -0.5, 0.0]).abs() < 1e-12);
    }

    #[test]
    fn signed_distance_is_dot_product_not_norm() {
        // z = 10 plane, +z normal: point (3, 4, 15) → 15 − 10 = 5.
        let plane = Plane::new([0.0, 0.0, 10.0], [0.0, 0.0, 1.0], frame()).unwrap();
        assert!((plane.signed_distance([3.0, 4.0, 15.0]) - 5.0).abs() < 1e-12);
        // With a diagonal normal the value is the projection (dot product),
        // not the 3D distance: (1,1,9)·n̂ where n̂ = (√2/2, √2/2, 0) → √2.
        let diag = Plane::new([0.0, 0.0, 0.0], [1.0, 1.0, 0.0], frame()).unwrap();
        assert!((diag.signed_distance([1.0, 1.0, 9.0]) - std::f64::consts::SQRT_2).abs() < 1e-12);
    }
}
