//! Section / profile computation and the computed-vs-interpreted distinction.
//!
//! Ported from `archphoto.archaeo.section`. Separates the COMPUTED section line
//! (derived from the model by cutting with a plane) from the researcher's
//! INTERPRETED line (e.g. a stratigraphic reading). Both are kept as
//! [`SectionLine`] with an explicit [`LineOrigin`], so a reader can never
//! mistake interpretation for measurement.
//!
//! When a section is cut from a mesh that carries per-vertex origin, each
//! segment is also tagged [`OriginKind::Observed`] only when ALL three vertices
//! of the cut triangle are observed; any interpolated vertex on the face tags
//! the segment [`OriginKind::Interpolated`].

use crate::crs::SpatialFrame;
use crate::mesh::OriginKind;
use crate::plane::Plane;
use crate::{ContractResult, Point3D};

/// A 3D line segment `(start, end)`.
pub type Segment = (Point3D, Point3D);

/// Where a line came from — measurement-derived vs human interpretation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LineOrigin {
    /// 계산된 단면선 (cut from the model).
    Computed,
    /// 연구자 해석선 (e.g. 토층 판독선).
    Interpreted,
}

impl LineOrigin {
    pub fn label(self) -> &'static str {
        match self {
            Self::Computed => "computed",
            Self::Interpreted => "interpreted",
        }
    }
}

/// A set of 3D segments with an explicit origin and spatial frame.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct SectionLine {
    pub segments: Vec<Segment>,
    pub origin: LineOrigin,
    pub frame: SpatialFrame,
    pub segment_origin: Vec<OriginKind>,
}

impl SectionLine {
    pub fn new(
        segments: Vec<Segment>,
        origin: LineOrigin,
        frame: SpatialFrame,
        segment_origin: Vec<OriginKind>,
    ) -> ContractResult<Self> {
        if !segment_origin.is_empty() && segment_origin.len() != segments.len() {
            return Err("segment_origin length must match segments length".into());
        }
        Ok(Self {
            segments,
            origin,
            frame,
            segment_origin,
        })
    }

    pub fn is_computed(&self) -> bool {
        self.origin == LineOrigin::Computed
    }

    pub fn is_interpreted(&self) -> bool {
        self.origin == LineOrigin::Interpreted
    }
}

/// Cut `faces` with `plane` and return the computed section line.
///
/// Each triangle that straddles the plane contributes one segment. If
/// `vertex_origin` is given, a segment is tagged [`OriginKind::Observed`] only
/// when ALL three vertices of the cut triangle are observed; any interpolated
/// vertex on the face tags the segment [`OriginKind::Interpolated`]. Coplanar
/// triangles lying entirely in the plane are skipped rather than emitting an
/// arbitrary single edge.
pub fn compute_section(
    vertices: &[Point3D],
    faces: &[[usize; 3]],
    plane: &Plane,
    vertex_origin: Option<&[OriginKind]>,
    tol: f64,
) -> ContractResult<SectionLine> {
    if !tol.is_finite() || tol < 0.0 {
        return Err("tol must be finite and >= 0".into());
    }
    if let Some(vo) = vertex_origin
        && vo.len() != vertices.len()
    {
        return Err("vertex_origin length must match vertices length".into());
    }
    let n_verts = vertices.len();
    for f in faces {
        if f[0] >= n_verts || f[1] >= n_verts || f[2] >= n_verts {
            return Err(format!(
                "face vertex index out of bounds ({}, {}, {}) for {} vertices",
                f[0], f[1], f[2], n_verts
            ));
        }
    }

    let mut segments = Vec::new();
    let mut seg_origin = Vec::new();
    for f in faces {
        let (v0, v1, v2) = (vertices[f[0]], vertices[f[1]], vertices[f[2]]);
        let pts = dedupe(&tri_plane_points(v0, v1, v2, plane, tol), tol);
        if pts.len() >= 2 {
            segments.push((pts[0], pts[1]));
            if let Some(vo) = vertex_origin {
                let all_observed = vo[f[0]] == OriginKind::Observed
                    && vo[f[1]] == OriginKind::Observed
                    && vo[f[2]] == OriginKind::Observed;
                seg_origin.push(if all_observed {
                    OriginKind::Observed
                } else {
                    OriginKind::Interpolated
                });
            }
        }
    }
    SectionLine::new(
        segments,
        LineOrigin::Computed,
        plane.frame.clone(),
        seg_origin,
    )
}

/// Wrap a researcher's interpretive strokes as an [`LineOrigin::Interpreted`] section line.
pub fn interpretation_line(strokes: Vec<Segment>, frame: SpatialFrame) -> SectionLine {
    SectionLine {
        segments: strokes,
        origin: LineOrigin::Interpreted,
        frame,
        segment_origin: Vec::new(),
    }
}

fn tri_plane_points(
    v0: Point3D,
    v1: Point3D,
    v2: Point3D,
    plane: &Plane,
    tol: f64,
) -> Vec<Point3D> {
    let verts = [v0, v1, v2];
    let d = [
        plane.signed_distance(v0),
        plane.signed_distance(v1),
        plane.signed_distance(v2),
    ];
    // Skip triangles that are entirely coplanar with the cutting plane.
    if d[0].abs() <= tol && d[1].abs() <= tol && d[2].abs() <= tol {
        return Vec::new();
    }
    let mut pts = Vec::new();
    for i in 0..3 {
        let j = (i + 1) % 3;
        let (di, dj) = (d[i], d[j]);
        if di.abs() <= tol && dj.abs() <= tol {
            pts.push(verts[i]);
            pts.push(verts[j]);
        } else if di.abs() <= tol {
            pts.push(verts[i]);
        } else if di * dj < 0.0 {
            let t = di / (di - dj);
            let (pi, pj) = (verts[i], verts[j]);
            pts.push([
                pi[0] + t * (pj[0] - pi[0]),
                pi[1] + t * (pj[1] - pi[1]),
                pi[2] + t * (pj[2] - pi[2]),
            ]);
        }
    }
    pts
}

fn dedupe(pts: &[Point3D], tol: f64) -> Vec<Point3D> {
    let mut out: Vec<Point3D> = Vec::new();
    for &p in pts {
        if !out.iter().any(|q| {
            (p[0] - q[0]).abs() <= tol && (p[1] - q[1]).abs() <= tol && (p[2] - q[2]).abs() <= tol
        }) {
            out.push(p);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::LengthUnit;

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:test", LengthUnit::Millimeter).unwrap()
    }

    #[test]
    fn triangle_straddling_plane_produces_one_segment() {
        let f = frame();
        let plane = Plane::new([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], f).unwrap();
        let verts = vec![[0.0, 0.0, -1.0], [2.0, 0.0, 1.0], [0.0, 2.0, 1.0]];
        let faces = vec![[0, 1, 2]];
        let sec = compute_section(&verts, &faces, &plane, None, 1e-9).unwrap();
        assert!(sec.is_computed());
        assert!(!sec.is_interpreted());
        assert_eq!(sec.segments.len(), 1);
        let (a, b) = sec.segments[0];
        assert!(a[2].abs() < 1e-9 && b[2].abs() < 1e-9);
    }

    #[test]
    fn any_interpolated_vertex_tags_segment_interpolated() {
        let f = frame();
        let plane = Plane::new([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], f).unwrap();
        let verts = vec![[0.0, 0.0, -1.0], [2.0, 0.0, 1.0], [0.0, 2.0, 1.0]];
        let faces = vec![[0, 1, 2]];
        let origins = vec![
            OriginKind::Observed,
            OriginKind::Observed,
            OriginKind::Interpolated,
        ];
        let sec = compute_section(&verts, &faces, &plane, Some(&origins), 1e-9).unwrap();
        assert_eq!(sec.segment_origin, vec![OriginKind::Interpolated]);
    }

    #[test]
    fn coplanar_triangle_is_skipped() {
        let f = frame();
        let plane = Plane::new([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], f).unwrap();
        let verts = vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]];
        let faces = vec![[0, 1, 2]];
        let sec = compute_section(&verts, &faces, &plane, None, 1e-9).unwrap();
        assert!(sec.segments.is_empty());
    }

    #[test]
    fn interpretation_line_is_never_computed() {
        let f = frame();
        let line = interpretation_line(vec![([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])], f);
        assert!(line.is_interpreted());
        assert!(!line.is_computed());
    }
}
