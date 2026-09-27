from __future__ import annotations

from typing import Any, Dict, Sequence, Tuple
import pandas as pd


class ResourceRegistry:
    """Registry for external resources (frequency lists, scores)."""

    def __init__(self) -> None:
        self._frequency_lists: Dict[str, Tuple[pd.DataFrame, Dict[str, Any]]] = {}
        self._scores: Dict[str, Tuple[pd.DataFrame, Dict[str, Any]]] = {}

    def register_frequency_list(
        self,
        name: str,
        df: pd.DataFrame,
        sample_size: int | None = None,
        complete: bool | None = None,
        info: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(df, pd.DataFrame):
            raise TypeError("Frequency list must be a pandas DataFrame")
        df = df.copy()
        if sample_size is None:
            if "f" in df.columns and complete:
                sample_size = int(df["f"].sum())
        if "f" not in df.columns:
            if sample_size is not None:
                if "pmw" in df.columns:
                    df["f"] = df["pmw"] * sample_size / 1_000_000
                elif "rel_f" in df.columns:
                    df["f"] = df["rel_f"] * sample_size
                df["f"] = df["f"].round().astype(int)
        if "pmw" not in df.columns:
            if "rel_f" in df.columns:
                df["pmw"] = df["rel_f"] * 1_000_000
            elif "f" in df.columns and sample_size:
                df["pmw"] = df["f"] / sample_size * 1_000_000
        if "rel_f" not in df.columns:
            if "f" in df.columns and sample_size is not None:
                df["rel_f"] = df["f"] / sample_size
        sort_col = "f" if "f" in df.columns else "rel_f"
        df = df.sort_values(sort_col, ascending=False).reset_index(drop=True)
        df.index += 1
        self._frequency_lists[name] = (
            df,
            {"sample_size": sample_size, "complete": complete, **(info or {})},
        )

    def get_frequency_list(
        self,
        name: str,
        frequency_columns: Sequence[str] | None = ("f", "pmw", "rel_f"),
        token_attribute_columns: Sequence[str] | None = None,
        ignore_case: bool = False,
    ) -> pd.DataFrame:
        df, _meta = self._frequency_lists[name]
        df_out = df.copy()
        sort_col = "f" if "f" in df.columns else "rel_f"
        if ignore_case:
            for col in df_out.columns:
                if df_out[col].dtype == object:
                    df_out[col] = df_out[col].str.lower()
        if token_attribute_columns and len(token_attribute_columns) > 0:
            agg_cols: list[str] = [
                c for c in ("f", "pmw", "rel_f") if c in df_out.columns
            ]
            df_out = (
                df_out.groupby(list(token_attribute_columns), as_index=False)[agg_cols]
                .sum()
                .sort_values(sort_col, ascending=False)
            )
            df_out.index = pd.RangeIndex(start=1, stop=len(df_out) + 1)
        if frequency_columns is not None:
            df_out = df_out[
                [
                    c
                    for c in df_out.columns
                    if c not in {"f", "pmw", "rel_f"} or c in frequency_columns
                ]
            ]
        return df_out

    def get_frequency_list_info(self, name: str) -> Dict[str, Any]:
        return self._frequency_lists[name][1]

    def register_scores(
        self, name: str, df: pd.DataFrame, info: dict[str, Any] | None = None
    ) -> None:
        if not isinstance(df, pd.DataFrame):
            raise TypeError("Scores must be a pandas DataFrame")
        self._scores[name] = (df.copy(), {**(info or {})})

    def get_scores(
        self, name: str, columns: Dict[str, Sequence] | None = None
    ) -> pd.DataFrame:
        df, _meta = self._scores[name]
        df_out = df.copy()
        if columns:
            if set(columns) != {"attribute_columns", "score_columns"}:
                raise ValueError(
                    "columns must contain exactly attribute_columns and score_columns"
                )
            if not all(
                isinstance(columns[k], Sequence) and columns[k] for k in columns
            ):
                raise ValueError(
                    "attribute_columns and score_columns must be non empty sequences"
                )
            df_out = df_out[
                list(columns["attribute_columns"]) + list(columns["score_columns"])
            ]
        return df_out

    def get_scores_info(self, name: str) -> Dict[str, Any]:
        return self._scores[name][1]

    def list(self, resource_type: str | None = None):
        if resource_type == "frequency_list":
            return list(self._frequency_lists)
        if resource_type == "scores":
            return list(self._scores)
        if resource_type is None:
            return {
                "frequency_list": list(self._frequency_lists),
                "scores": list(self._scores),
            }
        raise ValueError(f"Unknown resource_type {resource_type}")

    def remove_frequency_list(self, name: str) -> None:
        self._frequency_lists.pop(name, None)

    def remove_scores(self, name: str) -> None:
        self._scores.pop(name, None)
