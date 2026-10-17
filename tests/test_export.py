"""Synthetic tests for mesh export (OBJ, PLY + mandatory honesty sidecar). SYNTHETIC only."""

from __future__ import annotations

import json

import pytest

from archphoto.archaeo.surface import OriginKind, ProductKind
from archphoto.geom import LengthUnit, SpatialFrame
from archphoto.mesh import ExportFormat, MeshProduct, export_mesh


def _mesh(product: ProductKind = ProductKind.SURVEY) -> MeshProduct:
    frame = SpatialFrame(crs_id="EPSG:5186", unit=LengthUnit.METER)
    return MeshProduct(
        vertices=[
            (123456.789, 4123456.125, 10.5),
            (123457.789, 4123456.125, 10.5),
            (123456.789, 4123457.125, 10.5),
        ],
        faces=[(0, 1, 2)],
        origin=[OriginKind.OBSERVED, OriginKind.OBSERVED, OriginKind.INTERPOLATED],
        product_kind=product,
        frame=frame,
    )


def test_export_obj_writes_1_indexed_faces_and_sidecar(tmp_path) -> None:
    out = tmp_path / "model.obj"
    sidecar = export_mesh(_mesh(), out, ExportFormat.OBJ)
    assert out.exists() and sidecar.exists()
    assert sidecar.name == "model.obj.sidecar.json"

    obj_text = out.read_text(encoding="utf-8")
    assert "# product_kind: survey" in obj_text
    assert "# crs_id: EPSG:5186" in obj_text
    assert "v 123456.789 4123456.125 10.5" in obj_text
    assert "f 1 2 3" in obj_text

    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["product_kind"] == "survey"
    assert meta["is_survey_record"] is True
    assert meta["observed_vertices"] == 2
    assert meta["interpolated_vertices"] == 1
    assert meta["crs_id"] == "EPSG:5186"


def test_export_ply_uses_double_precision_and_observed_flag(tmp_path) -> None:
    out = tmp_path / "model.ply"
    sidecar = export_mesh(_mesh(ProductKind.DISPLAY), out, ExportFormat.PLY)
    assert out.exists() and sidecar.exists()

    ply_text = out.read_text(encoding="utf-8")
    assert "property double x" in ply_text
    assert "property double y" in ply_text
    assert "property double z" in ply_text
    assert "property uchar observed" in ply_text
    assert "123456.789 4123456.125 10.5 1" in ply_text
    assert "123456.789 4123457.125 10.5 0" in ply_text
    assert "3 0 1 2" in ply_text

    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["product_kind"] == "display"
    assert meta["is_survey_record"] is False


@pytest.mark.parametrize("fmt", [ExportFormat.STL, ExportFormat.GLTF, ExportFormat.E57])
def test_unimplemented_export_formats_raise_honestly(tmp_path, fmt: ExportFormat) -> None:
    with pytest.raises(NotImplementedError):
        export_mesh(_mesh(), tmp_path / f"model.{fmt.value}", fmt)
