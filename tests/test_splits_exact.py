"""Exact, hand-written answers for lab.validation.splits (TESTING.md 5.3, splits.py items).

Every expected fold below is written out by hand from the definitions, not computed by the code under test.
"""

from __future__ import annotations

import inspect
from itertools import combinations

import numpy as np
import pytest

from lab.validation.splits import cpcv, cpcv_paths, walk_forward


def folds_as_lists(folds):
    return [(train.tolist(), test.tolist()) for train, test in folds]


def splits_as_lists(splits):
    return [(train.tolist(), test.tolist(), groups) for train, test, groups in splits]


# ---------------------------------------------------------------- walk_forward


def test_walk_forward_rolling_n10_train4_test2():
    assert folds_as_lists(walk_forward(10, train_size=4, test_size=2)) == [
        ([0, 1, 2, 3], [4, 5]),
        ([2, 3, 4, 5], [6, 7]),
        ([4, 5, 6, 7], [8, 9]),
    ]


def test_walk_forward_step_1():
    # Test blocks of 2 start at 4 and move one row at a time; trains are the 4 rows right before each block.
    assert folds_as_lists(walk_forward(10, train_size=4, test_size=2, step=1)) == [
        ([0, 1, 2, 3], [4, 5]),
        ([1, 2, 3, 4], [5, 6]),
        ([2, 3, 4, 5], [6, 7]),
        ([3, 4, 5, 6], [7, 8]),
        ([4, 5, 6, 7], [8, 9]),
    ]


def test_walk_forward_purge_1():
    # Default start becomes train_size + purge = 5; one row (4, then 6) is skipped between train and test.
    # The next block would be [9, 10], which runs past row 9, so it is dropped.
    assert folds_as_lists(walk_forward(10, train_size=4, test_size=2, purge=1)) == [
        ([0, 1, 2, 3], [5, 6]),
        ([2, 3, 4, 5], [7, 8]),
    ]


def test_walk_forward_expanding():
    # Same test blocks as the rolling case; every train window starts at row 0.
    assert folds_as_lists(walk_forward(10, train_size=4, test_size=2, expanding=True)) == [
        ([0, 1, 2, 3], [4, 5]),
        ([0, 1, 2, 3, 4, 5], [6, 7]),
        ([0, 1, 2, 3, 4, 5, 6, 7], [8, 9]),
    ]


def test_walk_forward_expanding_start_2():
    # Expanding windows may start before train_size rows exist: the first train window is rows 0..1.
    assert folds_as_lists(walk_forward(10, train_size=4, test_size=2, expanding=True, start=2)) == [
        ([0, 1], [2, 3]),
        ([0, 1, 2, 3], [4, 5]),
        ([0, 1, 2, 3, 4, 5], [6, 7]),
        ([0, 1, 2, 3, 4, 5, 6, 7], [8, 9]),
    ]


def test_walk_forward_rolling_explicit_start():
    assert folds_as_lists(walk_forward(10, train_size=4, test_size=2, start=5)) == [
        ([1, 2, 3, 4], [5, 6]),
        ([3, 4, 5, 6], [7, 8]),
    ]


def test_walk_forward_everything_at_once():
    # n=12, train 3, test 2, step 3, purge 2, expanding from start 4: tests [4,5] [7,8] (next [10,11] fits too).
    assert folds_as_lists(walk_forward(12, 3, 2, step=3, purge=2, expanding=True, start=4)) == [
        ([0, 1], [4, 5]),
        ([0, 1, 2, 3, 4], [7, 8]),
        ([0, 1, 2, 3, 4, 5, 6, 7], [10, 11]),
    ]


def test_walk_forward_last_block_may_end_on_the_last_row():
    # n=9: blocks [4,5] [6,7]; [8,9] would need row 9, which doesn't exist.
    assert [test.tolist() for _, test in walk_forward(9, 4, 2)] == [[4, 5], [6, 7]]
    # n=10: [8,9] ends exactly on the last row and is kept (see the first test).
    assert walk_forward(10, 4, 2)[-1][1].tolist() == [8, 9]


def test_walk_forward_default_purge_is_zero_train_ends_right_before_test():
    assert inspect.signature(walk_forward).parameters["purge"].default == 0
    for train, test in walk_forward(20, 5, 3):
        assert train[-1] + 1 == test[0]
    for train, test in walk_forward(20, 5, 3, expanding=True):
        assert train[-1] + 1 == test[0]


def test_walk_forward_returns_int_arrays():
    train, test = walk_forward(10, 4, 2)[0]
    assert train.dtype == np.int64 and test.dtype == np.int64


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"train_size": 0}, r"^train_size must be >= 1, got 0$"),
        ({"test_size": 0}, r"^test_size must be >= 1, got 0$"),
        ({"step": 0}, r"^step must be >= 1, got 0$"),
        ({"purge": -1}, r"^purge must be >= 0, got -1$"),
        ({"n": 0}, r"^n must be >= 1, got 0$"),
        ({"start": -1}, r"^start must be >= 0, got -1$"),
        ({"start": 3}, r"^start must be >= train_size \+ purge \(rolling: .*\) = 4, got 3$"),
        ({"start": 3, "purge": 1}, r"^start must be >= train_size \+ purge \(rolling: .*\) = 5, got 3$"),
        (
            {"start": 1, "purge": 1, "expanding": True},
            r"^start must be >= purge \+ 1 \(expanding: .*\) = 2, got 1$",
        ),
        ({"start": 0, "expanding": True}, r"^start must be >= purge \+ 1 \(expanding: .*\) = 1, got 0$"),
        ({"n": 5}, r"^no fold fits: n=5 rows but the first test block needs rows 4\.\.5$"),
        ({"train_size": 2.5}, r"^train_size must be an integer, got 2\.5$"),
        ({"test_size": True}, r"^test_size must be an integer, got True$"),
        ({"n": 10.0}, r"^n must be an integer, got 10\.0$"),
        ({"step": 1.0}, r"^step must be an integer, got 1\.0$"),
    ],
)
def test_walk_forward_bad_arguments_raise(kwargs, match):
    args = {"n": 10, "train_size": 4, "test_size": 2} | kwargs
    with pytest.raises(ValueError, match=match):
        walk_forward(**args)


def test_walk_forward_boundary_arguments_are_accepted():
    # The smallest legal values of each argument.
    assert folds_as_lists(walk_forward(2, 1, 1)) == [([0], [1])]
    assert folds_as_lists(walk_forward(2, 1, 1, start=1)) == [([0], [1])]
    assert folds_as_lists(walk_forward(3, 1, 1, purge=1, expanding=True, start=2)) == [([0], [2])]
    assert len(walk_forward(np.int64(10), np.int64(4), np.int64(2))) == 3


# ---------------------------------------------------------------- cpcv


def test_cpcv_defaults_train_and_test_partition_every_row():
    for n, n_groups, n_test_groups in [(10, 5, 2), (11, 4, 1), (13, 6, 3), (7, 7, 6)]:
        splits = cpcv(n, n_groups, n_test_groups)
        assert len(splits) == len(list(combinations(range(n_groups), n_test_groups)))
        for train, test, _ in splits:
            assert np.intersect1d(train, test).size == 0
            assert sorted(np.concatenate([train, test]).tolist()) == list(range(n))


def test_cpcv_groups_are_contiguous_and_the_first_groups_get_the_extra_rows():
    # n=10 in 3 groups: sizes 4, 3, 3.
    assert splits_as_lists(cpcv(10, 3, 1)) == [
        ([4, 5, 6, 7, 8, 9], [0, 1, 2, 3], (0,)),
        ([0, 1, 2, 3, 7, 8, 9], [4, 5, 6], (1,)),
        ([0, 1, 2, 3, 4, 5, 6], [7, 8, 9], (2,)),
    ]


def test_cpcv_purge_and_embargo_one_test_group_by_hand():
    # Groups of 3: [0,1,2] [3,4,5] [6,7,8] [9,10,11]. horizon=2 purges the 2 rows before each test group,
    # embargo=1 drops the 1 row after it.
    assert splits_as_lists(cpcv(12, 4, 1, horizon=2, embargo=1)) == [
        ([4, 5, 6, 7, 8, 9, 10, 11], [0, 1, 2], (0,)),  # nothing before; row 3 embargoed
        ([0, 7, 8, 9, 10, 11], [3, 4, 5], (1,)),  # rows 1, 2 purged; row 6 embargoed
        ([0, 1, 2, 3, 10, 11], [6, 7, 8], (2,)),  # rows 4, 5 purged; row 9 embargoed
        ([0, 1, 2, 3, 4, 5, 6], [9, 10, 11], (3,)),  # rows 7, 8 purged; nothing after
    ]


def test_cpcv_purge_and_embargo_two_test_groups_by_hand():
    # Groups of 3, two test groups, horizon=1 (purge 1 row before each test group), embargo=1.
    assert splits_as_lists(cpcv(12, 4, 2, horizon=1, embargo=1)) == [
        ([7, 8, 9, 10, 11], [0, 1, 2, 3, 4, 5], (0, 1)),  # row 6 embargoed
        ([4, 10, 11], [0, 1, 2, 6, 7, 8], (0, 2)),  # 3 embargoed, 5 purged, 9 embargoed
        ([4, 5, 6, 7], [0, 1, 2, 9, 10, 11], (0, 3)),  # 3 embargoed, 8 purged
        ([0, 1, 10, 11], [3, 4, 5, 6, 7, 8], (1, 2)),  # 2 purged, 9 embargoed
        ([0, 1, 7], [3, 4, 5, 9, 10, 11], (1, 3)),  # 2 purged, 6 embargoed, 8 purged
        ([0, 1, 2, 3, 4], [6, 7, 8, 9, 10, 11], (2, 3)),  # 5 purged
    ]


def test_cpcv_purge_only_and_embargo_only():
    # n=8 in 4 groups of 2, test group 1 = rows [2, 3].
    split = cpcv(8, 4, 1, horizon=3)[1]
    assert (split[0].tolist(), split[1].tolist()) == (
        [4, 5, 6, 7],
        [2, 3],
    )  # rows 0, 1 purged (max(0, 2-3) = 0)
    split = cpcv(8, 4, 1, embargo=3)[1]
    assert (split[0].tolist(), split[1].tolist()) == ([0, 1, 7], [2, 3])  # rows 4, 5, 6 embargoed


def test_cpcv_returns_int_arrays():
    train, test, groups = cpcv(10, 5, 2)[0]
    assert train.dtype == np.int64 and test.dtype == np.int64 and groups == (0, 1)


@pytest.mark.parametrize(
    ("args", "kwargs", "match"),
    [
        ((10, 5, 0), {}, r"^n_test_groups must be >= 1, got 0$"),
        ((10, 1, 1), {}, r"^n_groups must be >= 2, got 1$"),
        ((10, 4, 4), {}, r"^n_test_groups must be < n_groups .*, got n_test_groups=4, n_groups=4$"),
        ((10, 4, 5), {}, r"^n_test_groups must be < n_groups .*, got n_test_groups=5, n_groups=4$"),
        ((3, 4, 1), {}, r"^n_groups must be <= n so no group is empty, got n_groups=4, n=3$"),
        ((0, 2, 1), {}, r"^n must be >= 1, got 0$"),
        ((10, 5, 2), {"horizon": -1}, r"^horizon must be >= 0, got -1$"),
        ((10, 5, 2), {"embargo": -1}, r"^embargo must be >= 0, got -1$"),
        ((10, 5.0, 2), {}, r"^n_groups must be an integer, got 5\.0$"),
        ((10, 5, 2), {"horizon": 1.5}, r"^horizon must be an integer, got 1\.5$"),
        # groups [0,1] [2,3]: testing group 1 purges rows 0 and 1, leaving nothing to train on.
        (
            (4, 2, 1),
            {"horizon": 10},
            r"^purge \(horizon=10\) and embargo=0 leave no train rows for test groups \(1,\)$",
        ),
        (
            (4, 2, 1),
            {"embargo": 2},
            r"^purge \(horizon=0\) and embargo=2 leave no train rows for test groups \(0,\)$",
        ),
    ],
)
def test_cpcv_bad_arguments_raise(args, kwargs, match):
    with pytest.raises(ValueError, match=match):
        cpcv(*args, **kwargs)


def test_cpcv_smallest_legal_shapes():
    assert splits_as_lists(cpcv(2, 2, 1)) == [([1], [0], (0,)), ([0], [1], (1,))]
    # horizon and embargo that leave exactly one train row still work.
    assert splits_as_lists(cpcv(4, 2, 1, horizon=1)) == [([2, 3], [0, 1], (0,)), ([0], [2, 3], (1,))]


# ---------------------------------------------------------------- cpcv_paths


def appearance_lists(n_groups, n_test_groups):
    """For each group, the indices of the splits that test it, in split order (independent of the code)."""
    combos = list(combinations(range(n_groups), n_test_groups))
    return [[s for s, combo in enumerate(combos) if g in combo] for g in range(n_groups)]


def test_cpcv_paths_by_hand_n12_4_groups_2_test():
    # Splits: 0:(0,1) 1:(0,2) 2:(0,3) 3:(1,2) 4:(1,3) 5:(2,3). Group 0 is tested by 0,1,2; group 1 by 0,3,4;
    # group 2 by 1,3,5; group 3 by 2,4,5. Path j takes each group's j-th appearance.
    splits = cpcv(12, 4, 2)
    preds = [np.full(len(test), s) for s, (_, test, _) in enumerate(splits)]
    paths = cpcv_paths(12, 4, 2, preds)
    assert paths.tolist() == [
        [0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2],
        [1, 1, 1, 3, 3, 3, 3, 3, 3, 4, 4, 4],
        [2, 2, 2, 4, 4, 4, 5, 5, 5, 5, 5, 5],
    ]
    assert paths.dtype == np.float64


@pytest.mark.parametrize(
    ("n", "n_groups", "n_test_groups"), [(12, 4, 2), (17, 6, 2), (10, 5, 3), (9, 3, 1), (23, 7, 4)]
)
def test_cpcv_paths_use_each_groups_jth_appearance(n, n_groups, n_test_groups):
    splits = cpcv(n, n_groups, n_test_groups)
    preds = [np.full(len(test), s) for s, (_, test, _) in enumerate(splits)]
    paths = cpcv_paths(n, n_groups, n_test_groups, preds)
    appearances = appearance_lists(n_groups, n_test_groups)
    groups = np.array_split(np.arange(n), n_groups)
    assert paths.shape == (len(appearances[0]), n)
    for j in range(paths.shape[0]):
        for g, rows in enumerate(groups):
            assert np.all(paths[j, rows] == appearances[g][j])


def test_cpcv_paths_keep_each_prediction_on_its_own_row():
    # Feed every split the row numbers of its test rows: every path must read 0..n-1 in order.
    n, n_groups, n_test_groups = 13, 5, 2
    preds = [test for _, test, _ in cpcv(n, n_groups, n_test_groups)]
    paths = cpcv_paths(n, n_groups, n_test_groups, preds)
    assert paths.shape == (4, n)
    assert np.all(paths == np.arange(n))


def test_cpcv_paths_number_of_paths():
    # C(n_groups - 1, n_test_groups - 1)
    for n_groups, n_test_groups, expected in [(6, 2, 5), (6, 3, 10), (5, 1, 1), (8, 7, 7)]:
        n = 3 * n_groups
        preds = [np.zeros(len(test)) for _, test, _ in cpcv(n, n_groups, n_test_groups)]
        assert cpcv_paths(n, n_groups, n_test_groups, preds).shape == (expected, n)


def test_cpcv_paths_bad_arguments_raise():
    preds = [np.zeros(len(test)) for _, test, _ in cpcv(12, 4, 2)]
    with pytest.raises(ValueError, match=r"^split_predictions must have one array per split \(6\), got 5$"):
        cpcv_paths(12, 4, 2, preds[:5])
    bad = [*preds[:2], np.zeros(5), *preds[3:]]
    with pytest.raises(
        ValueError, match=r"^split 2 needs 6 predictions \(one per test row\), got shape \(5,\)$"
    ):
        cpcv_paths(12, 4, 2, bad)
    bad = [*preds[:2], np.zeros((6, 1)), *preds[3:]]
    with pytest.raises(
        ValueError, match=r"^split 2 needs 6 predictions \(one per test row\), got shape \(6, 1\)$"
    ):
        cpcv_paths(12, 4, 2, bad)
    with pytest.raises(ValueError, match=r"^n_test_groups must be >= 1, got 0$"):
        cpcv_paths(12, 4, 0, preds)
