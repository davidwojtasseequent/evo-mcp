"""Data loading utilities for downloading and classifying Evo interval tables."""

import time
import pandas as pd


from evo_mcp.utils.data_analysis_utils import (
    download_interval_data,
    download_downhole_intervals_data,
)


async def download_all_interval_tables(obj, object_type: str, collections_info: list[dict]) -> dict:
    """Download all interval tables and classify their columns.

    For each collection, downloads the interval data and classifies columns
    as numeric (suitable for statistics) or categorical.

    Args:
        obj: Downloaded Evo object.
        object_type: Object type string (e.g., 'downhole-collection', 'downhole-intervals').
        collections_info: List of collection info dicts from get_collection_info().

    Returns:
        Dict of { collection_name: { "df": DataFrame, "numeric_cols": [...], "categorical_cols": [...] } }
    """
    collection_data = {}

    for coll in collections_info:
        coll_name = coll['name']
        t0 = time.perf_counter()

        if object_type == 'downhole-intervals':
            df = await download_downhole_intervals_data(obj)
        else:
            df = await download_interval_data(obj, coll_name)

        elapsed = time.perf_counter() - t0

        # Classify columns: numeric vs categorical
        # Exclude structural columns (hole_id, from, to) from analysis
        structural_cols = {'hole_id', 'from', 'to'}
        attribute_cols = [c for c in df.columns if c not in structural_cols]

        numeric_cols = [c for c in attribute_cols if pd.api.types.is_numeric_dtype(df[c])]
        categorical_cols = [c for c in attribute_cols if c not in numeric_cols]

        collection_data[coll_name] = {
            "df": df,
            "numeric_cols": numeric_cols,
            "categorical_cols": categorical_cols,
            "elapsed": elapsed,
        }

    return collection_data
