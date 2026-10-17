"""Synthetic tests for reproducibility / determinism utilities. SYNTHETIC only."""

from __future__ import annotations

import random

from archphoto.reproducibility import (
    DeterminismSettings,
    compare_point_maps,
    compare_point_sequences,
    set_global_seed,
)


def test_set_global_seed_makes_rng_repeatable() -> None:
    set_global_seed(42)
    a = [random.random() for _ in range(6)]
    set_global_seed(42)
    b = [random.random() for _ in range(6)]
    assert a == b


def test_different_seeds_differ() -> None:
    set_global_seed(1)
    a = random.random()
    set_global_seed(2)
    assert random.random() != a


def test_compare_point_sequences_within_tolerance() -> None:
    a = [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]
    b = [(0.0, 0.0, 0.005), (1.0, 1.0, 1.0)]  # 0.005 mm apart
    ok = compare_point_sequences(a, b, tol=0.01)
    assert ok.within_tolerance is True and ok.max_deviation < 0.01 and ok.mismatches == []


def test_compare_point_sequences_detects_mismatch() -> None:
    a = [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]
    b = [(0.0, 0.0, 0.0), (1.0, 1.0, 5.0)]  # 4.0 apart
    bad = compare_point_sequences(a, b, tol=0.1)
    assert bad.within_tolerance is False and bad.mismatches == [1]


def test_compare_point_sequences_size_mismatch() -> None:
    r = compare_point_sequences([(0, 0, 0)], [(0, 0, 0), (1, 1, 1)], tol=1.0)
    assert r.within_tolerance is False and r.count_a == 1 and r.count_b == 2


def test_compare_point_maps_missing_id() -> None:
    a = {"P1": (0, 0, 0), "P2": (1, 1, 1)}
    b = {"P1": (0, 0, 0)}
    r = compare_point_maps(a, b, tol=0.1)
    assert r.within_tolerance is False and "P2" in r.mismatches


def test_determinism_settings_provenance() -> None:
    s = DeterminismSettings(seed=7, code_version="archphoto 0.0.1", engine_version="colmap x")
    p = s.as_run_parameters()
    assert p["seed"] == 7 and p["code_version"] == "archphoto 0.0.1"
    assert p["engine_version"] == "colmap x" and "input_hashes" in p
