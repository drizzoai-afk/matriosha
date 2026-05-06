"""Shared retrieval ranking helpers.

The candidate source may differ by backend, but final local ranking should use
the same scoring policy everywhere so CLI behavior and benchmarks stay aligned.
"""

from __future__ import annotations

from collections.abc import Iterable

from matriosha.core.search_terms import extract_search_terms


def _unique_terms(value: object) -> set[str]:
    return set(extract_search_terms(value, max_terms=96))


def lexical_overlap_score(query: object, candidate_text: object) -> float:
    """Return normalized lexical overlap in [0, 1]."""

    query_terms = _unique_terms(query)
    if not query_terms:
        return 0.0
    candidate_terms = _unique_terms(candidate_text)
    if not candidate_terms:
        return 0.0
    return len(query_terms & candidate_terms) / len(query_terms)


def weighted_keyword_score(query_hashes: Iterable[str], candidate_hashes: Iterable[str]) -> float:
    """Return normalized keyed-token overlap in [0, 1]."""

    query_set = {str(value) for value in query_hashes if value}
    if not query_set:
        return 0.0
    candidate_set = {str(value) for value in candidate_hashes if value}
    if not candidate_set:
        return 0.0
    return len(query_set & candidate_set) / len(query_set)


def hybrid_retrieval_score(
    *,
    query: object,
    candidate_text: object,
    semantic_score: float,
    keyword_score: float | None = None,
) -> float:
    """Blend semantic similarity with lexical/keyed overlap for final ranking.

    Short title-like queries are lexical fragile, so they get stronger keyword
    weight. Longer queries retain stronger semantic weight.
    """

    lexical_score = (
        lexical_overlap_score(query, candidate_text)
        if keyword_score is None
        else float(keyword_score)
    )
    query_term_count = len(_unique_terms(query))

    if query_term_count <= 3:
        semantic_weight = 0.15
        lexical_weight = 0.85
    else:
        semantic_weight = 0.45
        lexical_weight = 0.55

    score = semantic_weight * float(semantic_score) + lexical_weight * max(
        0.0, min(1.0, lexical_score)
    )
    return round(score, 6)
