//! MeshProduct: a mesh that carries the honesty axes into every output.
//!
//! Ported from Python `archphoto.mesh.product` + `archphoto.archaeo.surface`.
//! Two DISTINCT axes are kept apart so an unobserved region is never presented
//! as fact (05 §4):
//!   - [`OriginKind`] — WHERE the geometry came from: OBSERVED (measured from
//!     data) vs INTERPOLATED (filled / smoothed / guessed).
//!   - [`ProductKind`] — WHAT the model is FOR: SURVEY (measurement-grade
//!     record) vs DISPLAY (exhibition; explicitly NOT a survey record).
//!
//! A survey model may contain an interpolated region but MUST disclose it. A
//! display model must never be labelled as a survey record.
//!
//! Not yet ported (later slice): `mesh_sidecar` (export honesty metadata) and
//! `SurfaceProduct` (product naming wrapper).

use crate::crs::SpatialFrame;
use crate::{ContractResult, Point3D};

/// Data origin of a piece of geometry (Python `OriginKind`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum OriginKind {
    /// Directly supported by input measurements.
    Observed,
    /// Filled, smoothed, mirrored, or inferred.
    Interpolated,
}

impl OriginKind {
    pub fn label(self) -> &'static str {
        match self {
            OriginKind::Observed => "observed",
            OriginKind::Interpolated => "interpolated",
        }
    }
}

/// Intended use of the model (Python `ProductKind`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ProductKind {
    /// Measurement-grade record.
    Survey,
    /// Exhibition model — NOT a survey record.
    Display,
}

impl ProductKind {
    pub fn label(self) -> &'static str {
        match self {
            ProductKind::Survey => "survey",
            ProductKind::Display => "display",
        }
    }

    pub fn is_survey_record(self) -> bool {
        self == ProductKind::Survey
    }
}

/// A mesh with per-vertex provenance and a product purpose.
///
/// `origin.len() == vertices.len()` is enforced at construction (Python
/// `__post_init__`); Rust's exhaustive enums make the SURVEY/DISPLAY validity
/// check unrepresentable, so no runtime check is needed for it.
#[derive(Debug, Clone, PartialEq)]
pub struct MeshProduct {
    /// 3D vertices in `frame` units.
    pub vertices: Vec<Point3D>,
    /// Triangles as vertex-index triples.
    pub faces: Vec<[usize; 3]>,
    /// Per-vertex [`OriginKind`], same length as `vertices`.
    pub origin: Vec<OriginKind>,
    pub product_kind: ProductKind,
    pub frame: SpatialFrame,
}

/// (observed, interpolated) counts by origin.
pub type OriginCounts = (usize, usize);

impl MeshProduct {
    pub fn new(
        vertices: Vec<Point3D>,
        faces: Vec<[usize; 3]>,
        origin: Vec<OriginKind>,
        product_kind: ProductKind,
        frame: SpatialFrame,
    ) -> ContractResult<Self> {
        if origin.len() != vertices.len() {
            return Err("origin length must match vertices length".into());
        }
        Ok(MeshProduct {
            vertices,
            faces,
            origin,
            product_kind,
            frame,
        })
    }

    /// Fraction of vertices directly supported by measurements. An empty mesh
    /// reports 0.0 (nothing observed), matching Python.
    pub fn observed_fraction(&self) -> f64 {
        if self.origin.is_empty() {
            return 0.0;
        }
        self.count_by_origin().0 as f64 / self.origin.len() as f64
    }

    pub fn count_by_origin(&self) -> OriginCounts {
        let observed = self
            .origin
            .iter()
            .filter(|o| **o == OriginKind::Observed)
            .count();
        (observed, self.origin.len() - observed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::{LengthUnit, SpatialFrame};

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:t", LengthUnit::Millimeter).unwrap()
    }

    #[test]
    fn origin_length_must_match_vertices() {
        let err = MeshProduct::new(
            vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            vec![[0, 1, 2]],
            vec![OriginKind::Observed],
            ProductKind::Survey,
            frame(),
        )
        .unwrap_err();
        assert!(err.contains("origin length must match"), "{err}");
    }

    #[test]
    fn honesty_split_is_countable_and_disclosable() {
        let mesh = MeshProduct::new(
            vec![[0.0; 3]; 4],
            vec![],
            vec![
                OriginKind::Observed,
                OriginKind::Observed,
                OriginKind::Observed,
                OriginKind::Interpolated,
            ],
            ProductKind::Survey,
            frame(),
        )
        .unwrap();
        let (observed, interpolated) = mesh.count_by_origin();
        assert_eq!((observed, interpolated), (3, 1));
        assert!((mesh.observed_fraction() - 0.75).abs() < 1e-12);
        assert!(mesh.product_kind.is_survey_record());
    }

    #[test]
    fn empty_mesh_reports_nothing_observed() {
        let mesh = MeshProduct::new(vec![], vec![], vec![], ProductKind::Display, frame()).unwrap();
        assert_eq!(mesh.observed_fraction(), 0.0);
        assert!(!mesh.product_kind.is_survey_record());
    }
}
