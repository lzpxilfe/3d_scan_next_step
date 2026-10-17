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
//! Also provides [`SurfaceProduct`], [`HonestyReport`], and [`mesh_sidecar`]
//! (the honesty + spatial metadata that MUST accompany any mesh export).

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

/// A surface product carrying the whole-model purpose and a description
/// (ported from Python `archphoto.archaeo.surface.SurfaceProduct`).
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub struct SurfaceProduct {
    pub product_kind: ProductKind,
    pub description: String,
}

impl SurfaceProduct {
    #[must_use]
    pub fn new(product_kind: ProductKind, description: impl Into<String>) -> Self {
        SurfaceProduct {
            product_kind,
            description: description.into(),
        }
    }

    pub fn is_survey_record(&self) -> bool {
        self.product_kind.is_survey_record()
    }
}

/// Truthfulness summary: product purpose + observed/interpolated split
/// (ported from Python `MeshProduct.honesty_report`).
#[derive(Debug, Clone, PartialEq)]
pub struct HonestyReport {
    pub product_kind: &'static str,
    pub is_survey_record: bool,
    pub vertex_count: usize,
    pub observed_vertices: usize,
    pub interpolated_vertices: usize,
    pub observed_fraction: f64,
    pub interpolated_fraction: f64,
}

/// The honesty + spatial metadata that MUST accompany any mesh export
/// (ported from Python `mesh_sidecar`).
#[derive(Debug, Clone, PartialEq)]
pub struct MeshSidecar {
    pub product_kind: &'static str,
    pub is_survey_record: bool,
    pub crs_id: String,
    pub unit: &'static str,
    pub vertical_datum: &'static str,
    pub vertex_count: usize,
    pub face_count: usize,
    pub observed_vertices: usize,
    pub interpolated_vertices: usize,
    pub observed_fraction: f64,
    pub interpolated_fraction: f64,
}

impl MeshSidecar {
    /// Serialize the sidecar record as formatted UTF-8 JSON matching
    /// Python `json.dumps(mesh_sidecar(mesh), indent=2)`.
    #[must_use]
    pub fn to_json_pretty(&self) -> String {
        let escaped_crs = escape_json_str(&self.crs_id);
        format!(
            "{{\n  \
             \"product_kind\": \"{}\",\n  \
             \"is_survey_record\": {},\n  \
             \"crs_id\": \"{}\",\n  \
             \"unit\": \"{}\",\n  \
             \"vertical_datum\": \"{}\",\n  \
             \"vertex_count\": {},\n  \
             \"face_count\": {},\n  \
             \"observed_vertices\": {},\n  \
             \"interpolated_vertices\": {},\n  \
             \"observed_fraction\": {},\n  \
             \"interpolated_fraction\": {}\n\
             }}",
            self.product_kind,
            self.is_survey_record,
            escaped_crs,
            self.unit,
            self.vertical_datum,
            self.vertex_count,
            self.face_count,
            self.observed_vertices,
            self.interpolated_vertices,
            format_json_float(self.observed_fraction),
            format_json_float(self.interpolated_fraction),
        )
    }
}

fn escape_json_str(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c.is_control() => {
                use std::fmt::Write as _;
                let _ = write!(&mut out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out
}

fn format_json_float(v: f64) -> String {
    if !v.is_finite() {
        return "0.0".to_string();
    }
    if v.fract() == 0.0 {
        format!("{v:.1}")
    } else {
        format!("{v}")
    }
}

/// A mesh with per-vertex provenance and a product purpose.
///
/// `origin.len() == vertices.len()`, finite vertex coordinates, and in-bounds
/// triangle face indices are enforced at construction.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
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
        if !vertices.iter().all(|v| v.iter().all(|c| c.is_finite())) {
            return Err("mesh vertex coordinates must be finite".into());
        }
        let n_v = vertices.len();
        for [i, j, k] in &faces {
            if *i >= n_v || *j >= n_v || *k >= n_v {
                return Err(format!(
                    "face vertex index out of bounds [{i}, {j}, {k}] for {n_v} vertices"
                ));
            }
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

    /// Truthfulness summary: product purpose + observed/interpolated split.
    #[must_use]
    pub fn honesty_report(&self) -> HonestyReport {
        let (observed, interpolated) = self.count_by_origin();
        let total = self.origin.len();
        let interpolated_fraction = if total > 0 {
            interpolated as f64 / total as f64
        } else {
            0.0
        };
        HonestyReport {
            product_kind: self.product_kind.label(),
            is_survey_record: self.product_kind.is_survey_record(),
            vertex_count: total,
            observed_vertices: observed,
            interpolated_vertices: interpolated,
            observed_fraction: self.observed_fraction(),
            interpolated_fraction,
        }
    }
}

/// Produce the honesty + spatial metadata that MUST accompany any mesh export
/// (ported from Python `archphoto.mesh.product.mesh_sidecar`).
#[must_use]
pub fn mesh_sidecar(mesh: &MeshProduct) -> MeshSidecar {
    let report = mesh.honesty_report();
    MeshSidecar {
        product_kind: report.product_kind,
        is_survey_record: report.is_survey_record,
        crs_id: mesh.frame.crs_id.clone(),
        unit: mesh.frame.unit.label(),
        vertical_datum: mesh.frame.vertical_datum.label(),
        vertex_count: report.vertex_count,
        face_count: mesh.faces.len(),
        observed_vertices: report.observed_vertices,
        interpolated_vertices: report.interpolated_vertices,
        observed_fraction: report.observed_fraction,
        interpolated_fraction: report.interpolated_fraction,
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
            vec![],
            vec![OriginKind::Observed],
            ProductKind::Survey,
            frame(),
        )
        .unwrap_err();
        assert!(err.contains("origin length must match"), "{err}");
    }

    #[test]
    fn face_index_out_of_bounds_or_non_finite_vertex_is_refused() {
        let err = MeshProduct::new(
            vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            vec![[0, 1, 2]],
            vec![OriginKind::Observed; 2],
            ProductKind::Survey,
            frame(),
        )
        .unwrap_err();
        assert!(err.contains("out of bounds"), "{err}");

        let nan_err = MeshProduct::new(
            vec![[f64::NAN, 0.0, 0.0]],
            vec![],
            vec![OriginKind::Observed],
            ProductKind::Survey,
            frame(),
        )
        .unwrap_err();
        assert!(nan_err.contains("finite"), "{nan_err}");
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

    #[test]
    fn sidecar_and_honesty_report_carry_frame_and_honesty() {
        let mesh = MeshProduct::new(
            vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            vec![[0, 1, 2]],
            vec![
                OriginKind::Observed,
                OriginKind::Observed,
                OriginKind::Interpolated,
            ],
            ProductKind::Survey,
            frame(),
        )
        .unwrap();
        let rep = mesh.honesty_report();
        assert_eq!(rep.product_kind, "survey");
        assert!(rep.is_survey_record);
        assert_eq!(rep.observed_vertices, 2);
        assert_eq!(rep.interpolated_vertices, 1);
        assert!((rep.interpolated_fraction - 1.0 / 3.0).abs() < 1e-12);

        let sidecar = mesh_sidecar(&mesh);
        assert_eq!(sidecar.product_kind, "survey");
        assert_eq!(sidecar.crs_id, "LOCAL:t");
        assert_eq!(sidecar.unit, "mm");
        assert_eq!(sidecar.vertical_datum, "unknown");
        assert_eq!(sidecar.face_count, 1);
        assert_eq!(sidecar.interpolated_vertices, 1);

        let json = sidecar.to_json_pretty();
        assert!(json.contains("\"product_kind\": \"survey\""));
        assert!(json.contains("\"is_survey_record\": true"));
        assert!(json.contains("\"crs_id\": \"LOCAL:t\""));
        assert!(json.contains("\"unit\": \"mm\""));
        assert!(json.contains("\"interpolated_vertices\": 1"));

        let display_mesh = MeshProduct::new(
            vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            vec![[0, 1, 2]],
            vec![OriginKind::Observed; 3],
            ProductKind::Display,
            frame(),
        )
        .unwrap();
        let display_sidecar = mesh_sidecar(&display_mesh);
        assert_eq!(display_sidecar.product_kind, "display");
        assert!(!display_sidecar.is_survey_record);

        let surf = SurfaceProduct::new(ProductKind::Survey, "pit-1");
        assert!(surf.is_survey_record());
    }
}
