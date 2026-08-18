"""Reciprocal rank fusion — pure math, hand-computed expectations.

Scores below are written out so a reader can check them without running the
code: ``score(d) = Σ 1 / (k + rank + 1)`` with zero-based ranks.
"""

from __future__ import annotations

from search.services import RRF_K, rrf_merge


def test_rrf_merge_fuses_two_overlapping_lists() -> None:
    # k=60. 10: 1/61 + 1/63 = 0.032266 | 20: 1/62 + 1/61 = 0.032522
    #       30: 1/63       = 0.015873 | 40: 1/62        = 0.016129
    assert rrf_merge([[10, 20, 30], [20, 40, 10]]) == [20, 10, 40, 30]


def test_rrf_merge_scores_match_the_formula() -> None:
    ranked = rrf_merge([[10, 20, 30], [20, 40, 10]], k=RRF_K)
    scores = {
        10: 1 / 61 + 1 / 63,
        20: 1 / 62 + 1 / 61,
        30: 1 / 63,
        40: 1 / 62,
    }
    assert ranked == sorted(scores, key=lambda document: -scores[document])


def test_rrf_merge_breaks_ties_by_first_appearance() -> None:
    # 1 and 3 both score 1/61, 2 and 4 both score 1/62; the earlier list wins.
    assert rrf_merge([[1, 2], [3, 4]]) == [1, 3, 2, 4]
    assert rrf_merge([[3, 4], [1, 2]]) == [3, 1, 4, 2]


def test_rrf_merge_is_deterministic_across_calls() -> None:
    lists = [[7, 8, 9], [9, 7, 8]]
    assert rrf_merge(lists) == rrf_merge(lists) == rrf_merge([list(x) for x in lists])


def test_k_decides_between_one_strong_hit_and_two_mediocre_ones() -> None:
    lists = [[1, 2, 3, 9], [4, 5, 6, 9]]
    # k=60: doc 9 scores 2/64 = 0.03125, twice any single-list hit (1/61).
    assert rrf_merge(lists, k=60) == [9, 1, 4, 2, 5, 3, 6]
    # k=1: the rank-0 hits dominate — 1/2 = 0.5 beats doc 9's 2/5 = 0.4.
    assert rrf_merge(lists, k=1) == [1, 4, 9, 2, 5, 3, 6]


def test_rrf_merge_counts_a_repeat_within_one_list_once() -> None:
    # Double counting would give doc 1 (1/62 + 1/63) > doc 2 (1/61) and flip it.
    assert rrf_merge([[2, 1, 1]]) == [2, 1]


def test_rrf_merge_handles_empty_input() -> None:
    assert rrf_merge([]) == []
    assert rrf_merge([[], []]) == []
    assert rrf_merge([[5, 6], []]) == [5, 6]
