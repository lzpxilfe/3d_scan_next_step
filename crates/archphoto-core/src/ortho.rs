//! Orthophoto projection and grid (고고학 산출물: 정사영상).
//!
//! Ported from `archphoto.archaeo.ortho`. Provides the geometric core for
//! metric orthographic projections:
//! - [`OrthoSpec`] — projection plane and orthogonal in-plane `(u, v)` unit axes.
//! - [`OrthoGrid`] — pixel grid with real-unit resolution (`pixels <-> units`).
//! - [`OrthoProduct`] — projected points carrying the honesty axes (`OriginKind`
//!   and `ProductKind`).

use crate::crs::{LengthUnit, SpatialFrame};
use crate::mesh::{OriginKind, ProductKind};
use crate::{ContractResult, Point3D};

/// 2D metric or pixel coordinate `(u, v)` / `(col, row)`.
pub type Point2D = [f64; 2];

fn normalize(v: Point3D) -> ContractResult<Point3D> {
    if !v.iter().all(|c| c.is_finite()) {
        return Err("axis vector components must be finite".into());
    }
    let n = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
    if n == 0.0 || !n.is_finite() {
        return Err("axis vector must be non-zero".into());
    }
    Ok([v[0] / n, v[1] / n, v[2] / n])
}

/// Projection plane given by `origin` and orthogonal in-plane unit axes `u_axis`/`v_axis`.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct OrthoSpec {
    pub origin: Point3D,
    pub u_axis: Point3D,
    pub v_axis: Point3D,
    pub frame: SpatialFrame,
}

impl OrthoSpec {
    pub fn new(
        origin: Point3D,
        u_axis: Point3D,
        v_axis: Point3D,
        frame: SpatialFrame,
    ) -> ContractResult<Self> {
        if !origin.iter().all(|c| c.is_finite()) {
            return Err("OrthoSpec origin coordinates must be finite".into());
        }
        let u = normalize(u_axis)?;
        let v = normalize(v_axis)?;
        let dot = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
        if dot.abs() > 1e-6 {
            return Err("OrthoSpec u_axis and v_axis must be orthogonal".into());
        }
        Ok(Self {
            origin,
            u_axis: u,
            v_axis: v,
            frame,
        })
    }

    /// Orthographic projection onto `(u_axis, v_axis)` in `frame` units.
    pub fn project(&self, p: Point3D) -> Point2D {
        let dx = p[0] - self.origin[0];
        let dy = p[1] - self.origin[1];
        let dz = p[2] - self.origin[2];
        let u = dx * self.u_axis[0] + dy * self.u_axis[1] + dz * self.u_axis[2];
        let v = dx * self.v_axis[0] + dy * self.v_axis[1] + dz * self.v_axis[2];
        [u, v]
    }
}

/// Pixel grid with a metric resolution (`frame` units per pixel).
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct OrthoGrid {
    pub origin_uv: Point2D,
    pub resolution: f64,
    pub width_px: u32,
    pub height_px: u32,
    pub frame: SpatialFrame,
}

impl OrthoGrid {
    pub fn new(
        origin_uv: Point2D,
        resolution: f64,
        width_px: u32,
        height_px: u32,
        frame: SpatialFrame,
    ) -> ContractResult<Self> {
        if !origin_uv.iter().all(|c| c.is_finite()) || !resolution.is_finite() {
            return Err("OrthoGrid origin_uv and resolution must be finite".into());
        }
        if resolution <= 0.0 {
            return Err("resolution must be positive".into());
        }
        if width_px == 0 || height_px == 0 {
            return Err("grid size must be positive".into());
        }
        Ok(Self {
            origin_uv,
            resolution,
            width_px,
            height_px,
            frame,
        })
    }

    pub fn uv_to_pixel(&self, u: f64, v: f64) -> Point2D {
        let col = (u - self.origin_uv[0]) / self.resolution;
        let row = (v - self.origin_uv[1]) / self.resolution;
        [col, row]
    }

    pub fn pixel_to_uv(&self, col: f64, row: f64) -> Point2D {
        let u = self.origin_uv[0] + col * self.resolution;
        let v = self.origin_uv[1] + row * self.resolution;
        [u, v]
    }

    /// Axis-aligned bounds `([u_min, v_min], [u_max, v_max])` of the grid.
    pub fn extent(&self) -> (Point2D, Point2D) {
        let [u0, v0] = self.pixel_to_uv(0.0, 0.0);
        let [u1, v1] = self.pixel_to_uv(f64::from(self.width_px), f64::from(self.height_px));
        ([u0.min(u1), v0.min(v1)], [u0.max(u1), v0.max(v1)])
    }
}

/// Honesty summary for an [`OrthoProduct`].
#[derive(Debug, Clone, PartialEq)]
pub struct OrthoHonestyReport {
    pub product_kind: ProductKind,
    pub is_survey_record: bool,
    pub point_count: usize,
    pub observed_points: usize,
    pub interpolated_points: usize,
    pub observed_fraction: f64,
    pub unit: LengthUnit,
    pub crs_id: String,
}

/// Projected 2D points with per-point provenance and product purpose.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct OrthoProduct {
    pub points_uv: Vec<Point2D>,
    pub origin: Vec<OriginKind>,
    pub product_kind: ProductKind,
    pub spec: OrthoSpec,
    pub grid: OrthoGrid,
}

impl OrthoProduct {
    pub fn new(
        points_uv: Vec<Point2D>,
        origin: Vec<OriginKind>,
        product_kind: ProductKind,
        spec: OrthoSpec,
        grid: OrthoGrid,
    ) -> ContractResult<Self> {
        if origin.len() != points_uv.len() {
            return Err("origin length must match points_uv length".into());
        }
        if points_uv
            .iter()
            .any(|p| !p[0].is_finite() || !p[1].is_finite())
        {
            return Err("OrthoProduct points_uv coordinates must be finite".into());
        }
        if spec.frame != grid.frame {
            return Err("OrthoProduct spec.frame and grid.frame must match".into());
        }
        Ok(Self {
            points_uv,
            origin,
            product_kind,
            spec,
            grid,
        })
    }

    pub fn honesty_report(&self) -> OrthoHonestyReport {
        let total = self.origin.len();
        let observed = self
            .origin
            .iter()
            .filter(|&&o| o == OriginKind::Observed)
            .count();
        OrthoHonestyReport {
            product_kind: self.product_kind,
            is_survey_record: self.product_kind == ProductKind::Survey,
            point_count: total,
            observed_points: observed,
            interpolated_points: total - observed,
            observed_fraction: if total > 0 {
                observed as f64 / total as f64
            } else {
                0.0
            },
            unit: self.grid.frame.unit,
            crs_id: self.grid.frame.crs_id.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:test", LengthUnit::Millimeter).unwrap()
    }

    #[test]
    fn orthographic_projection_drops_normal_and_enforces_orthogonal_axes() {
        let f = frame();
        let spec =
            OrthoSpec::new([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], f.clone()).unwrap();
        assert_eq!(spec.project([10.0, 20.0, 999.0]), [10.0, 20.0]);

        // Non-orthogonal axes must be refused.
        assert!(OrthoSpec::new([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], f).is_err());
    }

    #[test]
    fn grid_roundtrip_and_product_frame_match() {
        let f = frame();
        let spec =
            OrthoSpec::new([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], f.clone()).unwrap();
        let grid = OrthoGrid::new([0.0, 0.0], 2.0, 100, 50, f.clone()).unwrap();
        assert_eq!(grid.uv_to_pixel(10.0, 20.0), [5.0, 10.0]);
        assert_eq!(grid.pixel_to_uv(5.0, 10.0), [10.0, 20.0]);
        assert_eq!(grid.extent(), ([0.0, 0.0], [200.0, 100.0]));

        let prod = OrthoProduct::new(
            vec![[10.0, 20.0], [30.0, 40.0]],
            vec![OriginKind::Observed, OriginKind::Interpolated],
            ProductKind::Survey,
            spec.clone(),
            grid,
        )
        .unwrap();
        let rep = prod.honesty_report();
        assert!(rep.is_survey_record);
        assert_eq!(rep.observed_points, 1);
        assert_eq!(rep.interpolated_points, 1);

        // Mismatched frame between spec and grid must be refused.
        let other_frame = SpatialFrame::new("LOCAL:other", LengthUnit::Meter).unwrap();
        let other_grid = OrthoGrid::new([0.0, 0.0], 2.0, 100, 50, other_frame).unwrap();
        assert!(OrthoProduct::new(vec![], vec![], ProductKind::Survey, spec, other_grid).is_err());
    }
}
