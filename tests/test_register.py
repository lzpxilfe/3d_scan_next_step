"""Synthetic tests for block/scan registration ("붙이기"). SYNTHETIC only.

Proves the closed-form fit recovers a known transform, that stitching preserves
observed/interpolated honesty, and that registration ties can never be reused as
independent checks (05 §2).
"""

from __future__ import annotations

import pytest

from archphoto.archaeo.surface import OriginKind, ProductKind
from archphoto.geom import LengthUnit, SpatialFrame
from archphoto.quality import PointUsageLedger, evaluate_check
from archphoto.recon.register import (
    Block,
    TiePoint,
    apply_similarity,
    fit_rigid_transform,
    merge_blocks,
    register_blocks,
    register_blocks_ransac,
)
from archphoto.sensing import ControlPoint, ControlRole

Q90Z = (0.0, 0.0, 0.7071067811865476, 0.7071067811865476)  # 90° about Z
T = (1.0, 2.0, 3.0)
SRC = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 1.0), (2.0, 1.0, 3.0)]


def _frame() -> SpatialFrame:
    return SpatialFrame(crs_id="LOCAL:t", unit=LengthUnit.MILLIMETER)


def test_fit_recovers_known_rigid_transform() -> None:
    dst = [apply_similarity(Q90Z, T, 1.0, p) for p in SRC]
    quat, trans, scale = fit_rigid_transform(SRC, dst, with_scale=False)
    assert scale == pytest.approx(1.0)
    for s, d in zip(SRC, dst):
        assert apply_similarity(quat, trans, scale, s) == pytest.approx(d, abs=1e-9)


def test_fit_recovers_known_scale() -> None:
    dst = [apply_similarity(Q90Z, T, 2.0, p) for p in SRC]
    quat, trans, scale = fit_rigid_transform(SRC, dst, with_scale=True)
    assert scale == pytest.approx(2.0, abs=1e-9)
    for s, d in zip(SRC, dst):
        assert apply_similarity(quat, trans, scale, s) == pytest.approx(d, abs=1e-9)


def test_register_marks_ties_and_reports_rms() -> None:
    dst = [apply_similarity(Q90Z, T, 1.0, p) for p in SRC]
    ties = [TiePoint(f"T{i}", s, d) for i, (s, d) in enumerate(zip(SRC, dst))]
    ledger = PointUsageLedger()
    reg = register_blocks(ties, _frame(), ledger=ledger)
    assert reg.rms < 1e-6
    assert ledger.alignment == {f"T{i}" for i in range(len(SRC))}


def test_registration_tie_cannot_be_reused_as_check() -> None:
    dst = [apply_similarity(Q90Z, T, 1.0, p) for p in SRC]
    ties = [TiePoint(f"T{i}", s, d) for i, (s, d) in enumerate(zip(SRC, dst))]
    ledger = PointUsageLedger()
    register_blocks(ties, _frame(), ledger=ledger)
    # Reusing T0 as an independent check must be refused.
    with pytest.raises(ValueError):
        evaluate_check({"T0": (0.0, 0.0, 0.0)}, [ControlPoint("T0", ControlRole.CHECK, 0, 0, 0, _frame())], ledger)


def test_merge_preserves_honesty() -> None:
    f = _frame()
    b1 = Block("b1", f, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)], [OriginKind.OBSERVED] * 3)
    b2 = Block("b2", f, [(2, 2, 2), (3, 2, 2), (2, 3, 2)], [(0, 1, 2)], [OriginKind.INTERPOLATED] * 3)
    merged = merge_blocks([b1, b2], f)
    counts = merged.count_by_origin()
    assert counts["observed"] == 3 and counts["interpolated"] == 3
    assert len(merged.vertices) == 6 and merged.faces == [(0, 1, 2), (3, 4, 5)]


def test_merge_rejects_unregistered_block() -> None:
    f = _frame()
    other = SpatialFrame(crs_id="LOCAL:other", unit=LengthUnit.MILLIMETER)
    b1 = Block("b1", f, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)], [OriginKind.OBSERVED] * 3)
    b2 = Block("b2", other, [(2, 2, 2), (3, 2, 2), (2, 3, 2)], [(0, 1, 2)], [OriginKind.OBSERVED] * 3)
    with pytest.raises(ValueError):
        merge_blocks([b1, b2], f)


def _ties_with_outliers() -> list[TiePoint]:
    dst = [apply_similarity(Q90Z, T, 1.0, p) for p in SRC]
    ties = [TiePoint(f"T{i}", s, d) for i, (s, d) in enumerate(zip(SRC, dst))]
    # corrupt two correspondences
    ties[0] = TiePoint("T0", SRC[0], (100.0, 100.0, 100.0))
    ties[1] = TiePoint("T1", SRC[1], (-50.0, 200.0, 0.0))
    return ties


def test_ransac_rejects_outliers_and_recovers_transform() -> None:
    ties = _ties_with_outliers()
    reg = register_blocks_ransac(ties, _frame(), inlier_threshold=0.1, iterations=300, seed=0)
    assert set(reg.rejected_ids) == {"T0", "T1"}
    assert set(reg.inlier_ids) == {"T2", "T3", "T4", "T5"}
    # recovered transform fits the clean ties
    clean_dst = {f"T{i}": apply_similarity(Q90Z, T, 1.0, SRC[i]) for i in range(2, 6)}
    for t in ties:
        if t.tie_id in reg.inlier_ids:
            pred = apply_similarity(reg.quaternion_xyzw, reg.translation, reg.scale, t.src_point)
            assert pred == pytest.approx(clean_dst[t.tie_id], abs=1e-6)


def test_ransac_is_reproducible_for_a_seed() -> None:
    ties = _ties_with_outliers()
    a = register_blocks_ransac(ties, _frame(), inlier_threshold=0.1, iterations=200, seed=7)
    b = register_blocks_ransac(ties, _frame(), inlier_threshold=0.1, iterations=200, seed=7)
    assert a.rejected_ids == b.rejected_ids
    assert a.translation == pytest.approx(b.translation)


def test_ransac_marks_only_inliers_in_ledger() -> None:
    ties = _ties_with_outliers()
    ledger = PointUsageLedger()
    reg = register_blocks_ransac(ties, _frame(), inlier_threshold=0.1, iterations=300, seed=0, ledger=ledger)
    assert set(reg.inlier_ids) <= ledger.alignment
    assert "T0" not in ledger.alignment and "T1" not in ledger.alignment
