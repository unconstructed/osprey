"""Properties of lab.validation.splits (TESTING.md section 3).

Walk-forward and CPCV: no train/test overlap, purge and embargo gaps are exact, every row is tested the right number
of times, CPCV paths cover every row once, bad arguments raise. Expected values come from brute-force loops written
here, independent of the vectorised code.
"""

from __future__ import annotations

from itertools import combinations
from math import comb

import numpy as np
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from lab.validation.splits import cpcv, cpcv_paths, walk_forward

# ---------------------------------------------------------------- walk_forward


@st.composite
def walk_forward_args(draw):
    expanding = draw(st.booleans())
    train_size = draw(st.integers(1, 15))
    purge = draw(st.integers(0, 5))
    min_start = purge + 1 if expanding else train_size + purge
    return {
        "n": draw(st.integers(1, 60)),
        "train_size": train_size,
        "test_size": draw(st.integers(1, 10)),
        "step": draw(st.none() | st.integers(1, 12)),
        "purge": purge,
        "expanding": expanding,
        "start": draw(st.none() | st.integers(min_start, min_start + 10)),
    }


def expected_test_starts(n, train_size, test_size, step, purge, start):
    """Every complete test block start, by brute force."""
    first = train_size + purge if start is None else start
    step = test_size if step is None else step
    starts, s = [], first
    while s + test_size <= n:
        starts.append(s)
        s += step
    return starts


@given(walk_forward_args())
@example(
    {"n": 10, "train_size": 4, "test_size": 2, "step": None, "purge": 0, "expanding": False, "start": None}
)
def test_walk_forward_folds(args):
    starts = expected_test_starts(
        args["n"], args["train_size"], args["test_size"], args["step"], args["purge"], args["start"]
    )
    if not starts:
        with pytest.raises(ValueError, match="no fold fits"):
            walk_forward(**args)
        return
    folds = walk_forward(**args)
    assert [int(test[0]) for _, test in folds] == starts  # all complete blocks, in order, none skipped
    for train, test in folds:
        # Test block: contiguous, the right size, inside the data.
        assert test.tolist() == list(range(test[0], test[0] + args["test_size"]))
        assert test[-1] < args["n"]
        # Train window: contiguous, entirely before the test block, gap of exactly `purge` rows.
        assert train.tolist() == list(range(train[0], train[-1] + 1))
        assert np.intersect1d(train, test).size == 0
        assert test[0] - train[-1] - 1 == args["purge"]
        assert train[0] >= 0
        if args["expanding"]:
            assert train[0] == 0
        else:
            assert len(train) == args["train_size"]


@given(walk_forward_args())
def test_walk_forward_every_row_is_tested_the_right_number_of_times(args):
    starts = expected_test_starts(
        args["n"], args["train_size"], args["test_size"], args["step"], args["purge"], args["start"]
    )
    if not starts:
        return
    counts = np.zeros(args["n"], dtype=int)
    for _, test in walk_forward(**args):
        counts[test] += 1
    expected = [sum(s <= i < s + args["test_size"] for s in starts) for i in range(args["n"])]
    assert counts.tolist() == expected
    if (
        args["step"] is None
    ):  # back-to-back blocks: every row from the first test row on is tested at most once
        assert counts.max() == 1
        assert counts.sum() == len(starts) * args["test_size"]


@given(
    walk_forward_args(),
    st.sampled_from(["train_size", "test_size", "step", "purge", "start", "n"]),
    st.data(),
)
def test_walk_forward_bad_arguments_raise(args, field, data):
    bad = dict(args)
    if field == "start":
        min_start = args["purge"] + 1 if args["expanding"] else args["train_size"] + args["purge"]
        bad["start"] = data.draw(st.integers(0, min_start - 1))
        match = r"^start must be >= "
    else:
        minimum = 0 if field == "purge" else 1
        bad[field] = data.draw(st.integers(-5, minimum - 1))
        match = rf"^{field} must be >= {minimum}, got"
    with pytest.raises(ValueError, match=match):
        walk_forward(**bad)


@given(walk_forward_args(), st.sampled_from(["n", "train_size", "test_size", "step", "purge", "start"]))
def test_walk_forward_non_integer_arguments_raise(args, field):
    bad = dict(args)
    bad[field] = 2.5
    with pytest.raises(ValueError, match=rf"^{field} must be an integer, got 2\.5$"):
        walk_forward(**bad)


# ---------------------------------------------------------------- cpcv


@st.composite
def cpcv_args(draw):
    n_groups = draw(st.integers(2, 7))
    return {
        "n": draw(st.integers(n_groups, 40)),
        "n_groups": n_groups,
        "n_test_groups": draw(st.integers(1, n_groups - 1)),
        "horizon": draw(st.integers(0, 6)),
        "embargo": draw(st.integers(0, 6)),
    }


def brute_force_groups(n, n_groups):
    """Contiguous groups, sizes differing by at most one, the first n % n_groups groups one row longer."""
    sizes = [n // n_groups + (g < n % n_groups) for g in range(n_groups)]
    bounds = np.cumsum([0, *sizes])
    return [list(range(bounds[g], bounds[g + 1])) for g in range(n_groups)]


def brute_force_cpcv(n, n_groups, n_test_groups, horizon, embargo):
    groups = brute_force_groups(n, n_groups)
    out = []
    for combo in combinations(range(n_groups), n_test_groups):
        test = sorted(i for g in combo for i in groups[g])
        test_set = set(test)
        lasts = [groups[g][-1] for g in combo]
        train = [
            i
            for i in range(n)
            if i not in test_set
            and not any(i <= t <= i + horizon for t in test)  # purge: label window reaches a test row
            and not any(last < i <= last + embargo for last in lasts)  # embargo after each test group
        ]
        out.append((train, test, combo))
    return out


@given(cpcv_args())
@example({"n": 12, "n_groups": 4, "n_test_groups": 2, "horizon": 1, "embargo": 1})
@example({"n": 4, "n_groups": 2, "n_test_groups": 1, "horizon": 10, "embargo": 0})
def test_cpcv_matches_brute_force(args):
    expected = brute_force_cpcv(**args)
    if any(not train for train, _, _ in expected):
        with pytest.raises(ValueError, match="leave no train rows"):
            cpcv(**args)
        return
    got = [(train.tolist(), test.tolist(), groups) for train, test, groups in cpcv(**args)]
    assert got == expected


@given(cpcv_args())
def test_cpcv_no_overlap_and_exact_purge_and_embargo_gaps(args):
    n, horizon, embargo = args["n"], args["horizon"], args["embargo"]
    if any(not train for train, _, _ in brute_force_cpcv(**args)):
        return
    groups = brute_force_groups(n, args["n_groups"])
    for train, test, test_groups in cpcv(**args):
        assert np.intersect1d(train, test).size == 0
        assert test.tolist() == sorted(i for g in test_groups for i in groups[g])
        train_set, test_set = set(train.tolist()), set(test.tolist())
        # Purge is exact: no train row's label window [i, i + horizon] reaches a test row ...
        for i in train_set:
            assert not any(t in test_set for t in range(i, i + horizon + 1))
        for g in test_groups:
            first, last = groups[g][0], groups[g][-1]
            # ... and every one of the `horizon` rows before a test group is out of train (purged or test).
            assert not any(i in train_set for i in range(max(0, first - horizon), first))
            # Embargo is exact: the `embargo` rows after each test group are out of train ...
            assert not any(i in train_set for i in range(last + 1, last + 1 + embargo))
            # ... and the next row is back in train unless it is a test row or purged before a later test group.
            nxt = last + 1 + embargo
            purged = any(t in test_set for t in range(nxt, nxt + horizon + 1))
            embargoed = any(lst < nxt <= lst + embargo for lst in (groups[h][-1] for h in test_groups))
            if nxt < n and not purged and not embargoed:
                assert nxt in train_set


@given(cpcv_args())
def test_cpcv_every_row_is_tested_the_same_number_of_times(args):
    if any(not train for train, _, _ in brute_force_cpcv(**args)):
        return
    splits = cpcv(**args)
    assert len(splits) == comb(args["n_groups"], args["n_test_groups"])
    counts = np.zeros(args["n"], dtype=int)
    for _, test, _ in splits:
        counts[test] += 1
    assert np.all(counts == comb(args["n_groups"] - 1, args["n_test_groups"] - 1))


@given(cpcv_args())
def test_cpcv_without_purge_or_embargo_partitions_the_rows(args):
    for train, test, _ in cpcv(args["n"], args["n_groups"], args["n_test_groups"]):
        assert sorted(np.concatenate([train, test]).tolist()) == list(range(args["n"]))


@given(cpcv_args())
def test_cpcv_paths_cover_every_row_once_with_each_split_used_once(args):
    n, n_groups, n_test_groups = args["n"], args["n_groups"], args["n_test_groups"]
    splits = cpcv(n, n_groups, n_test_groups)
    # Prediction of split s on row i encodes both: s * n + i (unique per split and row).
    preds = [s * n + test for s, (_, test, _) in enumerate(splits)]
    paths = cpcv_paths(n, n_groups, n_test_groups, preds)
    n_paths = comb(n_groups - 1, n_test_groups - 1)
    assert paths.shape == (n_paths, n)
    assert not np.isnan(paths).any()  # every path covers every row
    rows = paths % n
    split_of = paths // n
    assert np.all(rows == np.arange(n))  # each value sits on its own row
    groups = brute_force_groups(n, n_groups)
    for g, members in enumerate(groups):
        testing = [s for s, (_, _, tg) in enumerate(splits) if g in tg]
        # A whole group comes from one split per path, the j-th split that tests it ...
        for j in range(n_paths):
            assert set(split_of[j, members].tolist()) == {testing[j]}
        # ... so across paths every split's prediction for the group is used exactly once.
        assert sorted(split_of[:, members[0]].tolist()) == testing


@given(cpcv_args(), st.data())
def test_cpcv_paths_accept_any_prediction_values(args, data):
    n, n_groups, n_test_groups = args["n"], args["n_groups"], args["n_test_groups"]
    splits = cpcv(n, n_groups, n_test_groups)
    preds = [
        np.array(data.draw(st.lists(st.floats(allow_nan=False), min_size=len(t), max_size=len(t))))
        for _, t, _ in splits
    ]
    paths = cpcv_paths(n, n_groups, n_test_groups, preds)
    for j in range(paths.shape[0]):
        for i in range(n):
            assert any(
                paths[j, i] == p[np.searchsorted(t, i)]
                for (_, t, _), p in zip(splits, preds, strict=True)
                if i in t
            )


@given(
    cpcv_args(),
    st.sampled_from(
        ["n_groups", "n_test_groups_low", "n_test_groups_high", "n_too_small", "horizon", "embargo"]
    ),
)
def test_cpcv_bad_arguments_raise(args, field):
    bad = dict(args)
    if field == "n_groups":
        bad["n_groups"], match = 1, r"^n_groups must be >= 2, got 1$"
    elif field == "n_test_groups_low":
        bad["n_test_groups"], match = 0, r"^n_test_groups must be >= 1, got 0$"
    elif field == "n_test_groups_high":
        bad["n_test_groups"], match = args["n_groups"], r"^n_test_groups must be < n_groups"
    elif field == "n_too_small":
        bad["n"], match = args["n_groups"] - 1, r"^n_groups must be <= n so no group is empty"
    else:
        bad[field], match = -1, rf"^{field} must be >= 0, got -1$"
    with pytest.raises(ValueError, match=match):
        cpcv(**bad)
    if field != "horizon" and field != "embargo":
        shape_only = {k: bad[k] for k in ("n", "n_groups", "n_test_groups")}
        with pytest.raises(ValueError, match=match):
            cpcv_paths(**shape_only, split_predictions=[])
