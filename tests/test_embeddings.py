"""Tests for embeddings helpers (no model loading required)."""

import json
import struct

import numpy as np

from endnote_mcp.embeddings import (
    build_search_text,
    cosine_similarity,
    has_embeddings,
    _blob_to_array,
)


def _make_embedding(values):
    """Create a float32 bytes blob from a list of values."""
    arr = np.array(values, dtype=np.float32)
    return arr.tobytes()


def test_build_search_text_full():
    ref = {
        "title": "Test Title",
        "abstract": "Test abstract about something.",
        "keywords": json.dumps(["keyword1", "keyword2"]),
    }
    text = build_search_text(ref)
    assert "Test Title" in text
    assert "Test abstract" in text
    assert "Keywords: keyword1, keyword2" in text


def test_build_search_text_keywords_as_list():
    ref = {
        "title": "Test Title",
        "abstract": "",
        "keywords": ["alpha", "beta"],
    }
    text = build_search_text(ref)
    assert "Keywords: alpha, beta" in text


def test_build_search_text_minimal():
    ref = {"title": "Only Title", "abstract": "", "keywords": "[]"}
    text = build_search_text(ref)
    assert text == "Only Title"


def test_build_search_text_empty():
    ref = {"title": "", "abstract": "", "keywords": "[]"}
    text = build_search_text(ref)
    assert text == ""


def test_cosine_similarity_identical():
    vec = _make_embedding([1.0, 0.0, 0.0])
    sim = cosine_similarity(vec, vec)
    assert abs(sim - 1.0) < 0.001


def test_cosine_similarity_orthogonal():
    a = _make_embedding([1.0, 0.0, 0.0])
    b = _make_embedding([0.0, 1.0, 0.0])
    sim = cosine_similarity(a, b)
    assert abs(sim) < 0.001


def test_cosine_similarity_opposite():
    a = _make_embedding([1.0, 0.0])
    b = _make_embedding([-1.0, 0.0])
    sim = cosine_similarity(a, b)
    assert sim < -0.9


def test_blob_to_array():
    original = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    blob = original.tobytes()
    result = _blob_to_array(blob)
    np.testing.assert_array_almost_equal(result, original)


def test_has_embeddings_empty(db_conn):
    assert has_embeddings(db_conn) is False


def test_semantic_filters_before_ranking_and_single_vector(populated_db):
    from endnote_mcp.db import upsert_embedding
    from endnote_mcp.embeddings import search_semantic
    for n, values in ((1, [1.0, 0.0]), (2, [0.8, 0.6]), (5, [0.6, 0.8])):
        upsert_embedding(populated_db, n, _make_embedding(values), 'all-MiniLM-L6-v2')
    # The highest scoring unfiltered hit is excluded before taking top one.
    result = search_semantic(populated_db, _make_embedding([1.0, 0.0]), year_from='2020', limit=1)
    assert [r['rec_number'] for r in result] == [5]
    result = search_semantic(populated_db, _make_embedding([1.0, 0.0]), limit=1, offset=1)
    assert [r['rec_number'] for r in result] == [2]


def test_model_loading_is_offline_by_default(monkeypatch):
    import sys
    import types
    from endnote_mcp import embeddings
    calls = []
    monkeypatch.setitem(sys.modules, 'sentence_transformers', types.SimpleNamespace(
        SentenceTransformer=lambda *args, **kw: calls.append(kw) or object()))
    monkeypatch.setattr(embeddings, '_model', None)
    embeddings.load_model()
    assert calls == [{'local_files_only': True}]
