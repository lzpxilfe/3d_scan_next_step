//! Block / scan registration and stitching ("붙이기").
//!
//! Ported from Python `archphoto.recon.register`. The reconstruction focus
//! (DECISIONS D-2026-10-12-07): combine multiple blocks / scans / features into
//! one coherent, georeferenced whole — faithfully — and leave fine mesh
//! refinement to external tools.
//!
//! Provides:
//!   - [`SimilarityFit`]      — closed-form (Horn/Umeyama) rotation+translation
//!     (+optional uniform scale) from ≥3 non-degenerate correspondences.
//!   - [`register_blocks`]    — fit using tie points; every tie is recorded in a
//!     [`PointUsageLedger`] as ALIGNMENT so it can NEVER double as an
//!     independent check point (05 §2).
//!   - [`register_blocks_ransac`] — robust fit rejecting outlier ties; only
//!     inliers are marked as model-fitting use in the ledger. Sampling uses a
//!     seeded SplitMix64 sampler so a run is reproducible. NOTE: the sampling
//!     stream is intentionally Rust-local (Python's MT19937 stream is not
//!     replicated); reproducibility is per-language, as the reference also only
//!     guarantees per-seed determinism.
//!   - [`apply_similarity`] / `apply_transform` / [`merge_blocks`] — move a
//!     block and stitch registered blocks into one [`MeshProduct`], preserving
//!     observed/interpolated honesty.
//!
//! API-shape note vs Python: the reference passsed an unused `frame` argument
//! to register_blocks/register_blocks_ransac; here the frame enters at
//! `apply_transform`/`merge_blocks`, where it is actually used — no dead
//! parameters.

use std::collections::HashMap;

use crate::crs::SpatialFrame;
use crate::mesh::{MeshProduct, OriginKind, ProductKind};
use crate::quality::PointUsageLedger;
use crate::{ContractResult, Point3D};

/// One reconstructed piece in its own `frame`.
///
/// `origin` is per-vertex provenance (same length as `vertices`) and is carried
/// through registration and stitching so honesty survives.
#[derive(Debug, Clone, PartialEq)]
pub struct Block {
    pub block_id: String,
    pub frame: SpatialFrame,
    pub vertices: Vec<Point3D>,
    pub faces: Vec<[usize; 3]>,
    pub origin: Vec<OriginKind>,
}

impl Block {
    pub fn new(
        block_id: impl Into<String>,
        frame: SpatialFrame,
        vertices: Vec<Point3D>,
        faces: Vec<[usize; 3]>,
        origin: Vec<OriginKind>,
    ) -> ContractResult<Self> {
        if origin.len() != vertices.len() {
            return Err("origin length must match vertices length".into());
        }
        Ok(Block {
            block_id: block_id.into(),
            frame,
            vertices,
            faces,
            origin,
        })
    }
}

/// A correspondence: `src_point` in the source block maps to `dst_point`.
#[derive(Debug, Clone, PartialEq)]
pub struct TiePoint {
    pub tie_id: String,
    pub src_point: Point3D,
    pub dst_point: Point3D,
}

impl TiePoint {
    #[must_use]
    pub fn new(tie_id: impl Into<String>, src_point: Point3D, dst_point: Point3D) -> Self {
        TiePoint {
            tie_id: tie_id.into(),
            src_point,
            dst_point,
        }
    }
}

/// The fitted similarity transform (source → target) and its fit quality.
///
/// `inlier_ids` are ties consistent with the accepted model; `rejected_ids`
/// are ties treated as outliers (excluded from the fit). Only inliers are
/// marked as model-fitting use in the ledger.
#[derive(Debug, Clone, PartialEq)]
pub struct RegistrationResult {
    pub quaternion_xyzw: [f64; 4],
    pub translation: Point3D,
    pub scale: f64,
    /// tie_id → distance error at that tie.
    pub residuals: HashMap<String, f64>,
    pub rms: f64,
    pub inlier_ids: Vec<String>,
    pub rejected_ids: Vec<String>,
}

/// Result of the closed-form fit: best similarity mapping `src[i] → dst[i]`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SimilarityFit {
    pub quaternion_xyzw: [f64; 4],
    pub translation: Point3D,
    pub scale: f64,
}

/// Apply `scale * R * p + translation` (the fitted source→target map).
pub fn apply_similarity(
    quaternion_xyzw: [f64; 4],
    translation: Point3D,
    scale: f64,
    p: Point3D,
) -> Point3D {
    let rp = apply_rot(quat_xyzw_to_rot(quaternion_xyzw), p);
    [
        scale * rp[0] + translation[0],
        scale * rp[1] + translation[1],
        scale * rp[2] + translation[2],
    ]
}

fn apply_rot(r: [[f64; 3]; 3], p: Point3D) -> Point3D {
    [
        r[0][0] * p[0] + r[0][1] * p[1] + r[0][2] * p[2],
        r[1][0] * p[0] + r[1][1] * p[1] + r[1][2] * p[2],
        r[2][0] * p[0] + r[2][1] * p[1] + r[2][2] * p[2],
    ]
}

fn quat_xyzw_to_rot(q: [f64; 4]) -> [[f64; 3]; 3] {
    let [x, y, z, w] = q;
    [
        [
            1.0 - 2.0 * (y * y + z * z),
            2.0 * (x * y - z * w),
            2.0 * (x * z + y * w),
        ],
        [
            2.0 * (x * y + z * w),
            1.0 - 2.0 * (x * x + z * z),
            2.0 * (y * z - x * w),
        ],
        [
            2.0 * (x * z - y * w),
            2.0 * (y * z + x * w),
            1.0 - 2.0 * (x * x + y * y),
        ],
    ]
}

/// Dominant eigenvector of a symmetric 4×4 matrix (cyclic Jacobi).
///
/// Jacobi is used (not power iteration) so the rotation is recovered precisely
/// even when the dominant eigenvalue gap is small. Ported index-for-index from
/// Python `_dominant_eigenvector_sym4`.
fn dominant_eigenvector_sym4(n: [[f64; 4]; 4]) -> [f64; 4] {
    const SIZE: usize = 4;
    let mut a = n;
    let mut v = [[0.0; SIZE]; SIZE];
    for i in 0..SIZE {
        v[i][i] = 1.0;
    }
    for _ in 0..100 {
        let mut off = 0.0;
        for p in 0..SIZE {
            for q in (p + 1)..SIZE {
                off += a[p][q] * a[p][q];
            }
        }
        if off < 1e-30 {
            break;
        }
        for p in 0..(SIZE - 1) {
            for q in (p + 1)..SIZE {
                let apq = a[p][q];
                if apq.abs() < 1e-300 {
                    continue;
                }
                let theta = (a[q][q] - a[p][p]) / (2.0 * apq);
                let sgn = if theta >= 0.0 { 1.0 } else { -1.0 };
                let t = sgn / (theta.abs() + (theta * theta + 1.0).sqrt());
                let c = 1.0 / (t * t + 1.0).sqrt();
                let s = t * c;
                for i in 0..SIZE {
                    let (aip, aiq) = (a[i][p], a[i][q]);
                    a[i][p] = c * aip - s * aiq;
                    a[i][q] = s * aip + c * aiq;
                }
                for i in 0..SIZE {
                    let (api, aqi) = (a[p][i], a[q][i]);
                    a[p][i] = c * api - s * aqi;
                    a[q][i] = s * api + c * aqi;
                }
                for i in 0..SIZE {
                    let (vip, viq) = (v[i][p], v[i][q]);
                    v[i][p] = c * vip - s * viq;
                    v[i][q] = s * vip + c * viq;
                }
            }
        }
    }
    let eigvals = [a[0][0], a[1][1], a[2][2], a[3][3]];
    let k = eigvals
        .iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
        .map(|(i, _)| i)
        .unwrap_or(0);
    let vec = [v[0][k], v[1][k], v[2][k], v[3][k]];
    let norm: f64 = vec.iter().map(|x| x * x).sum::<f64>().sqrt();
    let norm = if norm > 0.0 { norm } else { 1.0 };
    vec.map(|x| x / norm)
}

/// Closed-form best similarity mapping `src[i] → dst[i]` (Horn / Umeyama).
///
/// Needs at least 3 non-degenerate correspondences. Returns
/// [`SimilarityFit`] whose `scale` is 1.0 when `with_scale` is false.
pub fn fit_rigid_transform(
    src: &[Point3D],
    dst: &[Point3D],
    with_scale: bool,
) -> ContractResult<SimilarityFit> {
    if src.len() != dst.len() {
        return Err("correspondence sets must have equal length".into());
    }
    let n = src.len();
    if n < 3 {
        return Err("need at least 3 correspondences".into());
    }

    let centroid = |pts: &[Point3D]| -> Point3D {
        let mut c = [0.0; 3];
        for p in pts {
            for i in 0..3 {
                c[i] += p[i];
            }
        }
        c.map(|x| x / n as f64)
    };
    let mu_s = centroid(src);
    let mu_d = centroid(dst);
    let src_c: Vec<Point3D> = src
        .iter()
        .map(|p| [p[0] - mu_s[0], p[1] - mu_s[1], p[2] - mu_s[2]])
        .collect();
    let dst_c: Vec<Point3D> = dst
        .iter()
        .map(|p| [p[0] - mu_d[0], p[1] - mu_d[1], p[2] - mu_d[2]])
        .collect();

    // cross-covariance H = mean of src_c (x) dst_c
    let mut h = [[0.0f64; 3]; 3];
    for (a, b) in src_c.iter().zip(dst_c.iter()) {
        for i in 0..3 {
            for j in 0..3 {
                h[i][j] += a[i] * b[j];
            }
        }
    }
    for row in &mut h {
        for v in row.iter_mut() {
            *v /= n as f64;
        }
    }
    let [hxx, hxy, hxz] = h[0];
    let [hyx, hyy, hyz] = h[1];
    let [hzx, hzy, hzz] = h[2];

    // Horn's symmetric 4×4 matrix
    let mat = [
        [hxx + hyy + hzz, hyz - hzy, hzx - hxz, hxy - hyx],
        [hyz - hzy, hxx - hyy - hzz, hxy + hyx, hzx + hxz],
        [hzx - hxz, hxy + hyx, -hxx + hyy - hzz, hyz + hzy],
        [hxy - hyx, hzx + hxz, hyz + hzy, -hxx - hyy + hzz],
    ];
    let q0123 = dominant_eigenvector_sym4(mat); // (qw, qx, qy, qz)
    let quat = [q0123[1], q0123[2], q0123[3], q0123[0]]; // → (x, y, z, w)

    let rot = quat_xyzw_to_rot(quat);
    let scale = if with_scale {
        let mut num = 0.0;
        let mut den = 0.0;
        for (a, b) in src_c.iter().zip(dst_c.iter()) {
            let ra = apply_rot(rot, *a);
            num += ra[0] * b[0] + ra[1] * b[1] + ra[2] * b[2];
            den += a[0] * a[0] + a[1] * a[1] + a[2] * a[2];
        }
        if den > 0.0 { num / den } else { 1.0 }
    } else {
        1.0
    };

    let rmu = apply_rot(rot, mu_s);
    let translation = [
        mu_d[0] - scale * rmu[0],
        mu_d[1] - scale * rmu[1],
        mu_d[2] - scale * rmu[2],
    ];
    Ok(SimilarityFit {
        quaternion_xyzw: quat,
        translation,
        scale,
    })
}

/// Fit the source block into the target frame using `ties` (source→target).
///
/// Every tie is recorded in `ledger` as ALIGNMENT use, so it can never later
/// be reused as an independent check point (05 §2). Residuals at the ties
/// report registration fit quality.
pub fn register_blocks(
    ties: &[TiePoint],
    ledger: &mut PointUsageLedger,
    with_scale: bool,
) -> ContractResult<RegistrationResult> {
    let src: Vec<Point3D> = ties.iter().map(|t| t.src_point).collect();
    let dst: Vec<Point3D> = ties.iter().map(|t| t.dst_point).collect();
    let fit = fit_rigid_transform(&src, &dst, with_scale)?;

    let mut residuals = HashMap::new();
    for t in ties {
        let predicted =
            apply_similarity(fit.quaternion_xyzw, fit.translation, fit.scale, t.src_point);
        residuals.insert(t.tie_id.clone(), dist(predicted, t.dst_point));
        ledger.mark_alignment(&t.tie_id);
    }

    let n = residuals.len().max(1) as f64;
    let rms = (residuals.values().map(|r| r * r).sum::<f64>() / n).sqrt();
    Ok(RegistrationResult {
        inlier_ids: ties.iter().map(|t| t.tie_id.clone()).collect(),
        rejected_ids: Vec::new(),
        quaternion_xyzw: fit.quaternion_xyzw,
        translation: fit.translation,
        scale: fit.scale,
        residuals,
        rms,
    })
}

/// Robust registration ("붙이기") that rejects outlier tie points.
///
/// Repeatedly fits to minimal 3-tie samples, keeps the model with the most
/// inliers (ties within `inlier_threshold`, frame units — MUST be chosen for
/// the data; not a validated default, tolerance is [O]), refits on the
/// inliers, and reports which ties were rejected. Sampling uses a seeded
/// SplitMix64 sampler so a run is reproducible here; the stream differs from
/// Python's `random.Random`, intentionally. Only inliers are marked as
/// model-fitting use in the ledger; rejected ties are not.
pub fn register_blocks_ransac(
    ties: &[TiePoint],
    inlier_threshold: f64,
    ledger: &mut PointUsageLedger,
    with_scale: bool,
    iterations: usize,
    seed: u64,
) -> ContractResult<RegistrationResult> {
    if ties.len() < 3 {
        return Err("need at least 3 tie points for RANSAC registration".into());
    }
    let mut rng = SplitMix64::new(seed);
    let n = ties.len();
    let mut best_inliers: Option<Vec<usize>> = None;
    let mut best_key: Option<(usize, f64)> = None; // (inlier_count, rms) to maximize count, then minimize rms

    for _ in 0..iterations {
        let sample = sample_3(n, &mut rng);
        let (src, dst): (Vec<Point3D>, Vec<Point3D>) = (0..3)
            .map(|k| (ties[sample[k]].src_point, ties[sample[k]].dst_point))
            .fold((Vec::new(), Vec::new()), |(mut s, mut d), (sp, dp)| {
                s.push(sp);
                d.push(dp);
                (s, d)
            });
        let Ok(fit) = fit_rigid_transform(&src, &dst, with_scale) else {
            continue;
        };
        let inliers: Vec<usize> = ties
            .iter()
            .enumerate()
            .filter(|(_, t)| {
                dist(
                    apply_similarity(fit.quaternion_xyzw, fit.translation, fit.scale, t.src_point),
                    t.dst_point,
                ) < inlier_threshold
            })
            .map(|(i, _)| i)
            .collect();
        if inliers.len() < 3 {
            continue;
        }
        let rms = (inliers
            .iter()
            .map(|&i| {
                dist(
                    apply_similarity(
                        fit.quaternion_xyzw,
                        fit.translation,
                        fit.scale,
                        ties[i].src_point,
                    ),
                    ties[i].dst_point,
                )
                .powi(2)
            })
            .sum::<f64>()
            / inliers.len() as f64)
            .sqrt();
        let better = match best_key {
            None => true,
            Some((bc, brms)) => inliers.len() > bc || (inliers.len() == bc && rms < brms),
        };
        if better {
            best_key = Some((inliers.len(), rms));
            best_inliers = Some(inliers);
        }
    }

    let Some(best_inliers) = best_inliers else {
        return Err("RANSAC found no model with enough inliers".into());
    };

    // Refit on the best inlier set.
    let inlier_ties: Vec<&TiePoint> = best_inliers.iter().map(|&i| &ties[i]).collect();
    let (isrc, idst): (Vec<Point3D>, Vec<Point3D>) = (
        inlier_ties.iter().map(|t| t.src_point).collect(),
        inlier_ties.iter().map(|t| t.dst_point).collect(),
    );
    let fit = fit_rigid_transform(&isrc, &idst, with_scale)?;

    let mut residuals = HashMap::new();
    let mut inlier_ids = Vec::new();
    let mut rejected_ids = Vec::new();
    for t in ties {
        let d = dist(
            apply_similarity(fit.quaternion_xyzw, fit.translation, fit.scale, t.src_point),
            t.dst_point,
        );
        residuals.insert(t.tie_id.clone(), d);
        if d < inlier_threshold {
            inlier_ids.push(t.tie_id.clone());
        } else {
            rejected_ids.push(t.tie_id.clone());
        }
    }
    let rms = if inlier_ids.is_empty() {
        0.0
    } else {
        (inlier_ids
            .iter()
            .map(|id| residuals[id].powi(2))
            .sum::<f64>()
            / inlier_ids.len() as f64)
            .sqrt()
    };
    for tid in &inlier_ids {
        ledger.mark_alignment(tid);
    }
    Ok(RegistrationResult {
        inlier_ids,
        rejected_ids,
        quaternion_xyzw: fit.quaternion_xyzw,
        translation: fit.translation,
        scale: fit.scale,
        residuals,
        rms,
    })
}

/// Return `block` moved into `frame` by the fitted registration transform.
#[must_use]
pub fn apply_transform(block: &Block, reg: &RegistrationResult, frame: SpatialFrame) -> Block {
    let vertices = block
        .vertices
        .iter()
        .map(|v| apply_similarity(reg.quaternion_xyzw, reg.translation, reg.scale, *v))
        .collect();
    Block {
        block_id: block.block_id.clone(),
        frame,
        vertices,
        faces: block.faces.clone(),
        origin: block.origin.clone(),
    }
}

/// Stitch registered blocks (all already in `frame`) into one [`MeshProduct`].
///
/// Per-vertex origin is concatenated, so the honesty split survives the merge.
/// A block whose frame differs from the target frame Crs id is refused —
/// register it first.
pub fn merge_blocks(
    blocks: &[Block],
    frame: SpatialFrame,
    product_kind: ProductKind,
) -> ContractResult<MeshProduct> {
    let mut vertices: Vec<Point3D> = Vec::new();
    let mut faces: Vec<[usize; 3]> = Vec::new();
    let mut origin: Vec<OriginKind> = Vec::new();
    let mut offset = 0usize;
    for b in blocks {
        if b.frame.crs_id != frame.crs_id {
            return Err(format!(
                "block {:?} is not in the target frame; register it first",
                b.block_id
            ));
        }
        vertices.extend(b.vertices.iter().copied());
        origin.extend(b.origin.iter().copied());
        for [i, j, k] in &b.faces {
            faces.push([i + offset, j + offset, k + offset]);
        }
        offset += b.vertices.len();
    }
    MeshProduct::new(vertices, faces, origin, product_kind, frame)
}

fn dist(a: Point3D, b: Point3D) -> f64 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
}

/// Minimal deterministic sampler (SplitMix64). Chosen over adding an RNG
/// dependency for this slice; documented stream difference vs Python above.
struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
    fn new(seed: u64) -> Self {
        SplitMix64 { state: seed }
    }

    fn next(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// Three distinct indices in `[0, n)` by rejection sampling.
    fn sample_3(&mut self, n: usize) -> [usize; 3] {
        let mut out = [usize::MAX; 3];
        let mut filled = 0;
        while filled < 3 {
            let idx = (self.next() % n as u64) as usize;
            if !out[..filled].contains(&idx) {
                out[filled] = idx;
                filled += 1;
            }
        }
        out
    }
}

fn sample_3(n: usize, rng: &mut SplitMix64) -> [usize; 3] {
    rng.sample_3(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::LengthUnit;
    use crate::quality::evaluate_check;
    use crate::sensing::{ControlPoint, SurveyRole};

    /// 90° about Z, quaternion (x, y, z, w).
    const Q90Z: [f64; 4] = [0.0, 0.0, 0.707_106_781_186_547_6, 0.707_106_781_186_547_6];

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:t", LengthUnit::Millimeter).unwrap()
    }

    const SRC: [Point3D; 6] = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [1.0, 1.0, 1.0],
        [2.0, 1.0, 3.0],
    ];

    fn approx_v(a: Point3D, b: Point3D, tol: f64) {
        for (x, y) in a.iter().zip(b.iter()) {
            assert!((x - y).abs() < tol, "{a:?} vs {b:?}");
        }
    }

    fn known_similarity(scale: f64) -> impl Fn(Point3D) -> Point3D {
        move |p| apply_similarity(Q90Z, [1.0, 2.0, 3.0], scale, p)
    }

    fn ties_transformed(scale: f64) -> Vec<TiePoint> {
        let f = known_similarity(scale);
        SRC.iter()
            .enumerate()
            .map(|(i, s)| TiePoint::new(format!("T{i}"), *s, f(*s)))
            .collect()
    }

    fn ties_with_outliers() -> Vec<TiePoint> {
        let mut ties = ties_transformed(1.0);
        // Corrupt two correspondences.
        ties[0] = TiePoint::new("T0", SRC[0], [100.0, 100.0, 100.0]);
        ties[1] = TiePoint::new("T1", SRC[1], [-50.0, 200.0, 0.0]);
        ties
    }

    #[test]
    fn fit_recovers_known_rigid_transform() {
        let f = known_similarity(1.0);
        let dst: Vec<Point3D> = SRC.iter().map(|p| f(*p)).collect();
        let fit = fit_rigid_transform(&SRC, &dst, false).unwrap();
        assert!((fit.scale - 1.0).abs() < 1e-12, "scale {}", fit.scale);
        for (s, d) in SRC.iter().zip(dst.iter()) {
            approx_v(
                apply_similarity(fit.quaternion_xyzw, fit.translation, fit.scale, *s),
                *d,
                1e-9,
            );
        }
    }

    #[test]
    fn fit_recovers_known_scale() {
        let f = known_similarity(2.0);
        let dst: Vec<Point3D> = SRC.iter().map(|p| f(*p)).collect();
        let fit = fit_rigid_transform(&SRC, &dst, true).unwrap();
        assert!((fit.scale - 2.0).abs() < 1e-9, "scale {}", fit.scale);
        for (s, d) in SRC.iter().zip(dst.iter()) {
            approx_v(
                apply_similarity(fit.quaternion_xyzw, fit.translation, fit.scale, *s),
                *d,
                1e-9,
            );
        }
    }

    #[test]
    fn fit_contract_refuses_mismatched_or_thin_correspondences() {
        assert!(fit_rigid_transform(&SRC[..3], &SRC[..2], false).is_err());
        assert!(fit_rigid_transform(&SRC[..2], &SRC[..2], false).is_err());
    }

    #[test]
    fn register_marks_ties_and_reports_rms() {
        let ties = ties_transformed(1.0);
        let mut ledger = PointUsageLedger::default();
        let reg = register_blocks(&ties, &mut ledger, false).unwrap();
        assert!(reg.rms < 1e-6, "rms {}", reg.rms);
        for t in &ties {
            assert!(
                ledger.fitted().contains(&t.tie_id),
                "{} not marked",
                t.tie_id
            );
        }
    }

    #[test]
    fn registration_tie_cannot_be_reused_as_check() {
        let ties = ties_transformed(1.0);
        let mut ledger = PointUsageLedger::default();
        register_blocks(&ties, &mut ledger, false).unwrap();
        // Reusing T0 as an independent check must be refused.
        let check = ControlPoint::new("T0", SurveyRole::Check, 0.0, 0.0, 0.0, frame()).unwrap();
        let mut model = HashMap::new();
        model.insert("T0".to_string(), [0.0f64, 0.0, 0.0]);
        let err = evaluate_check(&model, &[check], &mut ledger).unwrap_err();
        assert!(
            err.contains("cannot be reused as an independent evaluation point"),
            "{err}"
        );
    }

    #[test]
    fn block_origin_contract_is_enforced() {
        assert!(
            Block::new(
                "b1",
                frame(),
                vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                vec![[0, 1, 2]],
                vec![OriginKind::Observed; 3]
            )
            .is_ok()
        );
        assert!(
            Block::new(
                "b2",
                frame(),
                vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
                vec![[0, 1, 2]],
                vec![OriginKind::Observed]
            )
            .is_err()
        );
    }

    #[test]
    fn merge_preserves_honesty() {
        let f = frame();
        let b1 = Block::new(
            "b1",
            f.clone(),
            vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            vec![[0, 1, 2]],
            vec![OriginKind::Observed; 3],
        )
        .unwrap();
        let b2 = Block::new(
            "b2",
            f.clone(),
            vec![[2.0, 2.0, 2.0], [3.0, 2.0, 2.0], [2.0, 3.0, 2.0]],
            vec![[0, 1, 2]],
            vec![OriginKind::Interpolated; 3],
        )
        .unwrap();
        let merged = merge_blocks(&[b1, b2], f, ProductKind::Survey).unwrap();
        assert_eq!(merged.count_by_origin(), (3, 3));
        assert_eq!(merged.vertices.len(), 6);
        assert_eq!(merged.faces, vec![[0, 1, 2], [3, 4, 5]]);
    }

    #[test]
    fn merge_rejects_unregistered_block() {
        let f = frame();
        let other = SpatialFrame::new("LOCAL:other", LengthUnit::Millimeter).unwrap();
        let b1 = Block::new(
            "b1",
            f.clone(),
            vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            vec![[0, 1, 2]],
            vec![OriginKind::Observed; 3],
        )
        .unwrap();
        let b2 = Block::new(
            "b2",
            other,
            vec![[2.0, 2.0, 2.0], [3.0, 2.0, 2.0], [2.0, 3.0, 2.0]],
            vec![[0, 1, 2]],
            vec![OriginKind::Observed; 3],
        )
        .unwrap();
        let err = merge_blocks(&[b1, b2], f, ProductKind::Survey).unwrap_err();
        assert!(err.contains("register it first"), "{err}");
    }

    #[test]
    fn apply_transform_moves_vertices_and_keeps_provenance() {
        let ties = ties_transformed(1.0);
        let mut ledger = PointUsageLedger::default();
        let reg = register_blocks(&ties, &mut ledger, false).unwrap();
        let src_block = Block::new(
            "b1",
            frame(),
            SRC.to_vec(),
            vec![[0, 1, 2], [3, 4, 5]],
            vec![OriginKind::Observed; 6],
        )
        .unwrap();
        assert_eq!(src_block.frame.crs_id, "LOCAL:t");
        let moved = apply_transform(&src_block, &reg, frame());
        assert_eq!(moved.origin, src_block.origin);
        assert_eq!(moved.faces, src_block.faces);
        let f = known_similarity(1.0);
        for (v, s) in moved.vertices.iter().zip(SRC.iter()) {
            approx_v(*v, f(*s), 1e-9);
        }
    }

    #[test]
    fn ransac_rejects_outliers_and_recovers_transform() {
        let ties = ties_with_outliers();
        let mut ledger = PointUsageLedger::default();
        let reg = register_blocks_ransac(&ties, 0.1, &mut ledger, false, 300, 0).unwrap();
        assert_eq!(reg.rejected_ids, vec!["T0", "T1"]);
        assert_eq!(reg.inlier_ids, vec!["T2", "T3", "T4", "T5"]);
        // The recovered transform fits the clean ties closely.
        let clean = known_similarity(1.0);
        for t in &ties {
            if reg.inlier_ids.contains(&t.tie_id) {
                let pred =
                    apply_similarity(reg.quaternion_xyzw, reg.translation, reg.scale, t.src_point);
                approx_v(pred, clean(t.src_point), 1e-6);
            }
        }
    }

    #[test]
    fn ransac_is_reproducible_for_a_seed() {
        let ties = ties_with_outliers();
        let mut l1 = PointUsageLedger::default();
        let mut l2 = PointUsageLedger::default();
        let a = register_blocks_ransac(&ties, 0.1, &mut l1, false, 200, 7).unwrap();
        let b = register_blocks_ransac(&ties, 0.1, &mut l2, false, 200, 7).unwrap();
        assert_eq!(a.rejected_ids, b.rejected_ids);
        assert_eq!(a.translation, b.translation);
        assert_eq!(a.quaternion_xyzw, b.quaternion_xyzw);
    }

    #[test]
    fn ransac_marks_only_inliers_in_ledger() {
        let ties = ties_with_outliers();
        let mut ledger = PointUsageLedger::default();
        let reg = register_blocks_ransac(&ties, 0.1, &mut ledger, false, 300, 0).unwrap();
        for id in &reg.inlier_ids {
            assert!(ledger.fitted().contains(id), "{id} should be marked");
        }
        assert!(ledger.fitted().contains("T0") == false);
        assert!(ledger.fitted().contains("T1") == false);
    }

    /// Convenience: ties for the outlier scenario, returning the clean mapping.
    /// (Splits the helper used in `ties_with_outliers` so callers keep both.)
    #[test]
    fn worst_case_too_few_ties_is_refused() {
        let mut ledger = PointUsageLedger::default();
        let ties = vec![TiePoint::new("T0", [0.0; 3], [0.0; 3])];
        assert!(register_blocks_ransac(&ties, 0.1, &mut ledger, false, 10, 0).is_err());
    }
}
