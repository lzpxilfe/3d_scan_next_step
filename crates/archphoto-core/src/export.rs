//! Mesh export: real OBJ / PLY writers + the mandatory honesty sidecar.
//!
//! Ported from `archphoto.mesh.export`. An export is complete only when it is
//! reopenable in an external program (MeshLab, CloudCompare, Blender, ...) AND
//! records its coordinate/unit basis and honesty axes. The sidecar is always
//! written so interpolated geometry can never pass as observed fact. PLY
//! additionally embeds a per-vertex `observed` flag (`uchar`) and `double`
//! coordinates so survey precision and provenance travel inside the mesh.

use std::fs;
use std::path::{Path, PathBuf};

use crate::ContractResult;
use crate::mesh::{MeshProduct, OriginKind, mesh_sidecar};

/// Supported and declared mesh export formats.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExportFormat {
    Obj,
    Ply,
    /// Not implemented (no provenance support in STL).
    Stl,
    /// Not implemented.
    Gltf,
    /// Not implemented (point-cloud interchange).
    E57,
}

impl ExportFormat {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Obj => "obj",
            Self::Ply => "ply",
            Self::Stl => "stl",
            Self::Gltf => "gltf",
            Self::E57 => "e57",
        }
    }
}

/// Write `mesh` to `path` plus a `<path>.sidecar.json` honesty record.
///
/// Implemented: [`ExportFormat::Obj`], [`ExportFormat::Ply`]. Others return an
/// honest `Err` rather than writing a stub file. Returns the sidecar path so
/// callers can confirm the honesty metadata was emitted.
pub fn export_mesh(
    mesh: &MeshProduct,
    path: &Path,
    export_format: ExportFormat,
) -> ContractResult<PathBuf> {
    let body = match export_format {
        ExportFormat::Obj => write_obj_string(mesh),
        ExportFormat::Ply => write_ply_string(mesh),
        other => {
            return Err(format!(
                "mesh.export: {} writer not implemented yet",
                other.as_str()
            ));
        }
    };

    fs::write(path, body).map_err(|e| format!("failed to write {}: {e}", path.display()))?;

    let mut sidecar_os = path.as_os_str().to_os_string();
    sidecar_os.push(".sidecar.json");
    let sidecar_path = PathBuf::from(sidecar_os);
    let sidecar_json = mesh_sidecar(mesh).to_json_pretty();
    fs::write(&sidecar_path, sidecar_json)
        .map_err(|e| format!("failed to write {}: {e}", sidecar_path.display()))?;

    Ok(sidecar_path)
}

/// Format `mesh` as an ASCII Wavefront OBJ string (1-indexed faces).
pub fn write_obj_string(mesh: &MeshProduct) -> String {
    let rep = mesh.honesty_report();
    let mut lines = Vec::with_capacity(5 + mesh.vertices.len() + mesh.faces.len());
    lines.push("# archphoto export".to_string());
    lines.push(format!("# product_kind: {}", rep.product_kind));
    lines.push(format!("# crs_id: {}", mesh.frame.crs_id));
    lines.push(format!("# unit: {}", mesh.frame.unit.label()));
    lines.push(format!("# observed_fraction: {:.6}", rep.observed_fraction));
    for v in &mesh.vertices {
        lines.push(format!("v {} {} {}", v[0], v[1], v[2]));
    }
    for f in &mesh.faces {
        lines.push(format!("f {} {} {}", f[0] + 1, f[1] + 1, f[2] + 1));
    }
    lines.join("\n") + "\n"
}

/// Format `mesh` as an ASCII PLY string with `double` coordinates and `uchar observed`.
pub fn write_ply_string(mesh: &MeshProduct) -> String {
    let n_v = mesh.vertices.len();
    let n_f = mesh.faces.len();
    let mut lines = Vec::with_capacity(14 + n_v + n_f);
    lines.push("ply".to_string());
    lines.push("format ascii 1.0".to_string());
    lines.push("comment archphoto export".to_string());
    lines.push(format!(
        "comment product_kind {}",
        mesh.product_kind.label()
    ));
    lines.push(format!("comment crs_id {}", mesh.frame.crs_id));
    lines.push(format!("comment unit {}", mesh.frame.unit.label()));
    lines.push(format!("element vertex {n_v}"));
    lines.push("property double x".to_string());
    lines.push("property double y".to_string());
    lines.push("property double z".to_string());
    lines.push("property uchar observed".to_string());
    lines.push(format!("element face {n_f}"));
    lines.push("property list uchar int vertex_indices".to_string());
    lines.push("end_header".to_string());
    for (v, &o) in mesh.vertices.iter().zip(mesh.origin.iter()) {
        let obs = if o == OriginKind::Observed { 1 } else { 0 };
        lines.push(format!("{} {} {} {}", v[0], v[1], v[2], obs));
    }
    for f in &mesh.faces {
        lines.push(format!("3 {} {} {}", f[0], f[1], f[2]));
    }
    lines.join("\n") + "\n"
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::{LengthUnit, SpatialFrame};
    use crate::mesh::ProductKind;

    fn sample_mesh() -> MeshProduct {
        let frame = SpatialFrame::new("EPSG:5186", LengthUnit::Meter).unwrap();
        MeshProduct::new(
            vec![
                [123456.789, 4123456.125, 10.5],
                [123457.789, 4123456.125, 10.5],
                [123456.789, 4123457.125, 10.5],
            ],
            vec![[0, 1, 2]],
            vec![
                OriginKind::Observed,
                OriginKind::Observed,
                OriginKind::Interpolated,
            ],
            ProductKind::Survey,
            frame,
        )
        .unwrap()
    }

    #[test]
    fn obj_and_ply_strings_preserve_double_precision_and_provenance() {
        let m = sample_mesh();
        let obj = write_obj_string(&m);
        assert!(obj.contains("# product_kind: survey"));
        assert!(obj.contains("v 123456.789 4123456.125 10.5"));
        assert!(obj.contains("f 1 2 3"));

        let ply = write_ply_string(&m);
        assert!(ply.contains("property double x"));
        assert!(ply.contains("property uchar observed"));
        assert!(ply.contains("123456.789 4123456.125 10.5 1"));
        assert!(ply.contains("123456.789 4123457.125 10.5 0"));
        assert!(ply.contains("3 0 1 2"));
    }

    #[test]
    fn export_mesh_writes_file_and_sidecar_and_refuses_unimplemented() {
        let m = sample_mesh();
        let dir = std::env::temp_dir();
        let pid = std::process::id();
        let obj_path = dir.join(format!("archphoto_test_{pid}.obj"));
        let sidecar = export_mesh(&m, &obj_path, ExportFormat::Obj).unwrap();
        assert!(obj_path.exists());
        assert!(sidecar.exists());
        let sidecar_text = fs::read_to_string(&sidecar).unwrap();
        assert!(sidecar_text.contains("\"crs_id\": \"EPSG:5186\""));
        assert!(sidecar_text.contains("\"is_survey_record\": true"));
        let _ = fs::remove_file(&obj_path);
        let _ = fs::remove_file(&sidecar);

        assert!(export_mesh(&m, &obj_path, ExportFormat::Stl).is_err());
        assert!(export_mesh(&m, &obj_path, ExportFormat::Gltf).is_err());
        assert!(export_mesh(&m, &obj_path, ExportFormat::E57).is_err());
    }
}
