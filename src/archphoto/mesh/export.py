"""Mesh export: real OBJ / PLY writers + the mandatory honesty sidecar.

An export is complete only when it is reopenable in an external program (MeshLab,
CloudCompare, Blender, ...) AND records its coordinate/unit basis and honesty
axes. The sidecar is always written so interpolated geometry can never pass as
observed fact. PLY additionally embeds a per-vertex ``observed`` flag so the
distinction travels inside the mesh itself.

Fine mesh refinement is left to those external tools (DECISIONS D-2026-10-12-07);
this is the faithful hand-off.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from archphoto.archaeo.surface import OriginKind
from archphoto.mesh.product import MeshProduct, mesh_sidecar


class ExportFormat(Enum):
    OBJ = "obj"
    PLY = "ply"
    STL = "stl"  # not implemented (no provenance support in STL)
    GLTF = "gltf"  # not implemented
    E57 = "e57"  # not implemented (point-cloud interchange)


def export_mesh(mesh: MeshProduct, path, export_format: ExportFormat) -> Path:
    """Write ``mesh`` to ``path`` plus a ``<path>.sidecar.json`` honesty record.

    Implemented: OBJ, PLY. Others raise NotImplementedError. Returns the sidecar
    path so callers can confirm the honesty metadata was emitted.
    """
    p = Path(path)
    if export_format is ExportFormat.OBJ:
        _write_obj(mesh, p)
    elif export_format is ExportFormat.PLY:
        _write_ply(mesh, p)
    else:
        raise NotImplementedError(f"mesh.export: {export_format.value} writer not implemented yet")

    sidecar_path = p.with_suffix(p.suffix + ".sidecar.json")
    sidecar_path.write_text(json.dumps(mesh_sidecar(mesh), indent=2), encoding="utf-8")
    return sidecar_path


def _write_obj(mesh: MeshProduct, path: Path) -> None:
    rep = mesh.honesty_report()
    lines = [
        "# archphoto export",
        f"# product_kind: {rep['product_kind']}",
        f"# crs_id: {mesh.frame.crs_id}",
        f"# unit: {mesh.frame.unit.value}",
        f"# observed_fraction: {rep['observed_fraction']:.6f}",
    ]
    for v in mesh.vertices:
        lines.append(f"v {v[0]} {v[1]} {v[2]}")
    for f in mesh.faces:
        lines.append(f"f {f[0] + 1} {f[1] + 1} {f[2] + 1}")  # OBJ is 1-indexed
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_ply(mesh: MeshProduct, path: Path) -> None:
    n_v, n_f = len(mesh.vertices), len(mesh.faces)
    lines = [
        "ply",
        "format ascii 1.0",
        "comment archphoto export",
        f"comment product_kind {mesh.product_kind.value}",
        f"comment crs_id {mesh.frame.crs_id}",
        f"comment unit {mesh.frame.unit.value}",
        f"element vertex {n_v}",
        "property double x",
        "property double y",
        "property double z",
        "property uchar observed",  # honesty travels inside the mesh
        f"element face {n_f}",
        "property list uchar int vertex_indices",
        "end_header",
    ]
    for v, o in zip(mesh.vertices, mesh.origin):
        obs = 1 if o is OriginKind.OBSERVED else 0
        lines.append(f"{v[0]} {v[1]} {v[2]} {obs}")
    for f in mesh.faces:
        lines.append(f"3 {f[0]} {f[1]} {f[2]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
