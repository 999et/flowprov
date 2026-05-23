"""Tests for the embedding utilities — pure-Python, no DB needed."""
from __future__ import annotations

import pytest

from flowprov.embeddings import (
    HashEmbeddingBackend,
    canonical_input_hash,
    cosine_distance,
    embed,
)


def test_canonical_hash_is_stable() -> None:
    a = {"foo": 1, "bar": "x"}
    b = {"bar": "x", "foo": 1}
    assert canonical_input_hash(a) == canonical_input_hash(b)


def test_canonical_hash_ignores_volatile_keys() -> None:
    a = {"x": 1, "_ts": 123}
    b = {"x": 1, "_ts": 999}
    assert canonical_input_hash(a) == canonical_input_hash(b)


def test_canonical_hash_changes_when_data_changes() -> None:
    assert canonical_input_hash({"x": 1}) != canonical_input_hash({"x": 2})


def test_cosine_distance_identical_is_zero() -> None:
    v = [1.0, 0.0, 0.0]
    assert cosine_distance(v, v) == pytest.approx(0.0, abs=1e-6)


def test_cosine_distance_orthogonal_is_one() -> None:
    assert cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0, abs=1e-6)


def test_cosine_distance_zero_vec() -> None:
    # By convention, distance against a zero vector returns 1 (max distance).
    assert cosine_distance([0.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


# ─── Hash backend specifics ─────────────────────────────────────────────────

def test_hash_embed_returns_correct_dim() -> None:
    v = embed("Severity: P1. Likely component: api. Recommended owner: @team-platform.")
    assert len(v) == 384
    assert all(isinstance(x, float) for x in v)


def test_hash_embed_is_deterministic() -> None:
    text = "Category: fraud. Confidence: 87%."
    assert embed(text) == embed(text)


def test_hash_embed_empty_string() -> None:
    v = embed("")
    assert v == [0.0] * 384


def test_hash_embed_similar_strings_close() -> None:
    """Two near-paraphrases should sit closer than two unrelated strings."""
    a = "Severity: P1. Component: payments. Owner: @team-platform."
    b = "Severity: P1. Component: payments. Owner: @team-trading."  # 1 token diff
    c = "Route to team: compliance. Priority: low. ETA: next-business-day."  # different
    d_ab = cosine_distance(embed(a), embed(b))
    d_ac = cosine_distance(embed(a), embed(c))
    assert d_ab < d_ac, f"expected near-paraphrase closer; got d_ab={d_ab}, d_ac={d_ac}"


def test_hash_embed_normalised() -> None:
    """Vectors should be L2-normalised (or zero)."""
    import numpy as np

    v = np.array(embed("hello world test"))
    norm = float(np.linalg.norm(v))
    assert 0.99 < norm < 1.01


def test_hash_backend_direct_instantiation() -> None:
    """The backend class should also be usable standalone (no settings dep)."""
    b = HashEmbeddingBackend()
    assert b.dim == 384
    v = b.embed("test")
    assert len(v) == 384
