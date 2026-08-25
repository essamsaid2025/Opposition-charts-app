"""Preprocessing pipeline for the Internal xG model (Checkpoint 3).

A single sklearn ``ColumnTransformer`` that encapsulates ALL feature handling so
it is saved with the estimator and applied identically at inference:

  * numeric   -> median impute + standardise
  * categorical -> constant "missing" impute + one-hot (unknown-safe)
  * binary    -> constant 0 impute, passthrough (kept in raw 0/1 units)

Nothing is preprocessed outside this transformer, so inference cannot silently
skip a step.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from . import features as F


def _to_float(X):
    """Cast boolean/other flags to float 0/1 so SimpleImputer accepts them.

    Module-level (not a lambda) so the fitted pipeline pickles/joblib-dumps.
    """
    if isinstance(X, pd.DataFrame):
        return X.astype(float)
    return np.asarray(X, dtype=float)


def build_preprocessor(feature_set: str = "A") -> ColumnTransformer:
    return build_preprocessor_for(F.feature_columns(feature_set))


def build_preprocessor_for(cols) -> ColumnTransformer:
    """Preprocessor for an arbitrary subset of known features.

    Columns are partitioned into numeric / categorical / binary by membership
    in the feature-group definitions from ``features.py``. Used for the
    reduced-feature experiments so the exact same encoding is reproduced.
    """
    cols = list(cols)
    F.assert_no_leakage(cols)
    num = [c for c in cols if c in F.NUMERIC_A + F.NUMERIC_B]
    cat = [c for c in cols if c in F.CATEGORICAL_A + F.CATEGORICAL_B]
    binary = [c for c in cols if c in F.BINARY_A + F.BINARY_B]

    numeric_pipe = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    categorical_pipe = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="constant", fill_value="missing")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    # Binary flags: impute any gaps to 0 (False); keep as 0/1 (no scaling) so
    # their logistic coefficients read as odds ratios directly.
    binary_pipe = Pipeline(
        steps=[
            ("to_float", FunctionTransformer(_to_float, feature_names_out="one-to-one")),
            ("impute", SimpleImputer(strategy="constant", fill_value=0)),
        ]
    )

    pre = ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, num),
            ("cat", categorical_pipe, cat),
            ("bin", binary_pipe, binary),
        ],
        remainder="drop",
        verbose_feature_names_out=True,
    )
    return pre
