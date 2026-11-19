"""Time-series train/test splitters: walk-forward and combinatorial purged cross-validation (CPCV).

Conventions
- Rows are time-ordered bars ``0 .. n-1``. Every index array returned here is a sorted ``int64`` numpy array.
- A row's *label window* is ``[i, i + horizon]``: the label (target) at row ``i`` is computed from rows up to
  ``i + horizon``. A training row whose label window reaches a test row leaks the test period into training.
- **Purge** removes those leaking training rows. In ``walk_forward`` it is a fixed number of rows skipped between the
  end of the train window and the start of the test block (set it to the label horizon). In ``cpcv`` it is derived
  from ``horizon``: a train row ``i`` is dropped when any test row lies in ``[i, i + horizon]``.
- **Embargo** (``cpcv`` only) drops the ``embargo`` rows right after each test group from training, so features
  computed from trailing windows that still contain test rows don't train the model.
- CPCV groups are contiguous, in time order, and differ in size by at most one row (the first ``n % n_groups``
  groups get the extra row). Splits come in ``itertools.combinations`` order of the test groups.

Every invalid argument raises ``ValueError`` with a message naming the argument.
"""

from __future__ import annotations

from itertools import combinations
from math import comb

import numpy as np

__all__ = ["cpcv", "cpcv_paths", "walk_forward"]


def _int_arg(name: str, value, minimum: int) -> int:
    """``value`` as a plain int, or ValueError if it isn't an integer >= ``minimum`` (bools are rejected)."""
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return int(value)


def walk_forward(
    n: int,
    train_size: int,
    test_size: int,
    step: int | None = None,
    purge: int = 0,
    expanding: bool = False,
    start: int | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Walk-forward folds ``[(train_idx, test_idx), ...]`` over ``n`` time-ordered rows.

    - Test blocks are ``test_size`` rows long. The first starts at row ``start`` (default ``train_size + purge``)
      and each next one ``step`` rows later (default ``test_size``: back-to-back blocks). A block that would run
      past row ``n - 1`` is dropped, so every block is complete.
    - The train window ends ``purge`` rows before its test block: exactly ``purge`` rows lie strictly between the
      last train row and the first test row. Rolling (default): the ``train_size`` rows ending there. Expanding:
      every row from 0 to the same end.

    Raises ValueError if ``n < 1``, ``train_size < 1``, ``test_size < 1``, ``step < 1``, ``purge < 0``,
    ``start < train_size + purge`` (rolling: the first train window must fit), ``start < purge + 1`` (expanding:
    the first train window must not be empty), or no fold fits in ``n`` rows.
    """
    n = _int_arg("n", n, 1)
    train_size = _int_arg("train_size", train_size, 1)
    test_size = _int_arg("test_size", test_size, 1)
    step = test_size if step is None else _int_arg("step", step, 1)
    purge = _int_arg("purge", purge, 0)
    start = train_size + purge if start is None else _int_arg("start", start, 0)
    if expanding:
        min_start, why = purge + 1, "purge + 1 (expanding: the first train window must not be empty)"
    else:
        min_start, why = train_size + purge, "train_size + purge (rolling: the first train window must fit)"
    if start < min_start:
        raise ValueError(f"start must be >= {why} = {min_start}, got {start}")

    folds = []
    for test_start in range(start, n - test_size + 1, step):
        train_end = test_start - purge  # exclusive
        train_start = 0 if expanding else train_end - train_size
        folds.append((np.arange(train_start, train_end), np.arange(test_start, test_start + test_size)))
    if not folds:
        raise ValueError(
            f"no fold fits: n={n} rows but the first test block needs rows {start}..{start + test_size - 1}"
        )
    return folds


def _groups(n: int, n_groups: int, n_test_groups: int) -> list[np.ndarray]:
    """Validate the CPCV shape arguments and return the ``n_groups`` contiguous row groups."""
    n = _int_arg("n", n, 1)
    n_groups = _int_arg("n_groups", n_groups, 2)
    n_test_groups = _int_arg("n_test_groups", n_test_groups, 1)
    if n_test_groups >= n_groups:
        raise ValueError(
            f"n_test_groups must be < n_groups so every split keeps a train group, "
            f"got n_test_groups={n_test_groups}, n_groups={n_groups}"
        )
    if n_groups > n:
        raise ValueError(f"n_groups must be <= n so no group is empty, got n_groups={n_groups}, n={n}")
    return np.array_split(np.arange(n), n_groups)


def cpcv(
    n: int,
    n_groups: int,
    n_test_groups: int,
    horizon: int = 0,
    embargo: int = 0,
) -> list[tuple[np.ndarray, np.ndarray, tuple[int, ...]]]:
    """Combinatorial purged cross-validation splits ``[(train_idx, test_idx, test_groups), ...]``.

    The ``n`` rows are cut into ``n_groups`` contiguous groups; every combination of ``n_test_groups`` groups is a
    test set (``C(n_groups, n_test_groups)`` splits, in ``itertools.combinations`` order). Training uses every
    other row except:

    - purge: train rows ``i`` with a test row in ``[i, i + horizon]`` (their label window reaches the test set);
    - embargo: the ``embargo`` rows right after the last row of each test group.

    With ``horizon=0`` and ``embargo=0`` the train and test rows of each split partition all ``n`` rows.

    Raises ValueError if ``n_groups < 2``, ``n_test_groups < 1``, ``n_test_groups >= n_groups``,
    ``n_groups > n``, ``horizon < 0``, ``embargo < 0``, or purge and embargo leave a split with no train rows.
    """
    groups = _groups(n, n_groups, n_test_groups)
    horizon = _int_arg("horizon", horizon, 0)
    embargo = _int_arg("embargo", embargo, 0)

    splits = []
    for test_groups in combinations(range(len(groups)), n_test_groups):
        is_test = np.zeros(n, dtype=bool)
        keep = np.ones(n, dtype=bool)
        for g in test_groups:
            first, last = groups[g][0], groups[g][-1]
            is_test[first : last + 1] = True
            # Groups are contiguous, so a label window [i, i + horizon] from a row before this group reaches a
            # test row of the group exactly when it reaches the group's first row.
            keep[max(0, first - horizon) : first] = False
            keep[last + 1 : last + 1 + embargo] = False
        keep &= ~is_test
        train_idx = np.flatnonzero(keep)
        if train_idx.size == 0:
            raise ValueError(
                f"purge (horizon={horizon}) and embargo={embargo} leave no train rows "
                f"for test groups {test_groups}"
            )
        splits.append((train_idx, np.flatnonzero(is_test), test_groups))
    return splits


def cpcv_paths(n: int, n_groups: int, n_test_groups: int, split_predictions) -> np.ndarray:
    """Assemble CPCV out-of-sample predictions into full backtest paths, shape ``(n_paths, n)``.

    ``split_predictions[s]`` holds split ``s``'s predictions for its test rows (``cpcv(...)[s][1]``, ascending),
    with splits in ``cpcv`` order. Each group is a test group in exactly ``n_paths = C(n_groups - 1,
    n_test_groups - 1)`` splits; path ``j`` takes each group's rows from the ``j``-th of those splits (in split
    order). Every path therefore covers every row exactly once. Returns float64.

    Raises ValueError for the shape errors ``cpcv`` raises, if the number of prediction arrays isn't
    ``C(n_groups, n_test_groups)``, or if an array's length doesn't match its split's test rows.
    """
    groups = _groups(n, n_groups, n_test_groups)
    all_test_groups = list(combinations(range(len(groups)), n_test_groups))
    if len(split_predictions) != len(all_test_groups):
        raise ValueError(
            f"split_predictions must have one array per split ({len(all_test_groups)}), "
            f"got {len(split_predictions)}"
        )
    n_paths = comb(len(groups) - 1, n_test_groups - 1)
    paths = np.full((n_paths, n), np.nan)
    appearances = [0] * len(groups)  # how many earlier splits tested each group
    for s, (test_groups, preds) in enumerate(zip(all_test_groups, split_predictions, strict=True)):
        preds = np.asarray(preds, dtype=float)
        n_test = sum(len(groups[g]) for g in test_groups)
        if preds.shape != (n_test,):
            raise ValueError(
                f"split {s} needs {n_test} predictions (one per test row), got shape {preds.shape}"
            )
        offset = 0
        for g in test_groups:
            rows = groups[g]
            paths[appearances[g], rows] = preds[offset : offset + len(rows)]
            offset += len(rows)
            appearances[g] += 1
    return paths
