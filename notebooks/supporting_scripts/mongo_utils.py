"""MongoDB utilities for Evo statistics storage and querying."""

import bson
from datetime import datetime, timezone
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure


# MongoDB document size limit
MONGO_DOC_LIMIT = 16 * 1024 * 1024  # 16 MB
SAFE_DOC_LIMIT = 14 * 1024 * 1024   # 14 MB — leave headroom


def connect_to_mongodb(uri: str, db_name: str, collection_name: str):
    """Connect to MongoDB and return the collection handle."""
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        # Verify connection
        client.admin.command('ping')
        db = client[db_name]
        collection = db[collection_name]
        
        print(f"✓ Connected to MongoDB: {db_name}.{collection_name}")
        return client, db, collection
    except ConnectionFailure as e:
        print(f"✗ Failed to connect to MongoDB: {e}")
        raise


def estimate_doc_size(doc: dict) -> int:
    """Estimate BSON document size in bytes."""
    return len(bson.BSON.encode(doc))


def build_gap_summary(gap_analysis: dict) -> dict:
    """Clean gap analysis for MongoDB (remove DataFrames)."""
    return {
        "total_gap_count": gap_analysis.get("total_gap_count", 0),
        "total_gap_length": gap_analysis.get("total_gap_length", 0),
        "holes_with_gaps": gap_analysis.get("holes_with_gaps", 0),
        "holes_without_gaps": gap_analysis.get("holes_without_gaps", 0),
    }


def _build_grade_stats_array(attribute_stats: dict, include_by_hole: bool = True) -> list[dict]:
    """Convert attribute_stats dict into a flat array for MongoDB storage.

    Each element contains ``attribute``, ``overall``, and optionally
    ``by_hole`` / ``hole_count``.  Using an array (rather than a dict
    keyed by attribute name) allows efficient ``$elemMatch`` queries.
    """
    result = []
    for attr_name, attr_data in attribute_stats.items():
        entry: dict = {
            "attribute": attr_name,
            "overall": attr_data.get("overall", {}),
            "hole_count": attr_data.get("hole_count", 0),
        }
        if include_by_hole:
            entry["by_hole"] = attr_data.get("by_hole", [])
        result.append(entry)
    return result


def _build_categorical_stats_array(
    categorical_stats: dict | None,
    include_by_hole: bool = True,
) -> list[dict]:
    """Convert categorical_stats dict into a flat array for MongoDB.

    Groups per-attribute fields under an ``overall`` key (mirroring the
    numeric convention) so every statistics entry has the same shape:
    ``{attribute, overall, by_hole}``.
    """
    if not categorical_stats:
        return []
    result = []
    for attr_name, stats in categorical_stats.items():
        entry: dict = {
            "attribute": attr_name,
            "overall": {
                "unique_count": stats.get("unique_count", 0),
                "total_count": stats.get("total_count", 0),
                "null_count": stats.get("null_count", 0),
                "truncated": stats.get("truncated", False),
                "value_counts": stats.get("value_counts", []),
            },
        }
        if include_by_hole:
            entry["by_hole"] = stats.get("by_hole", [])
        result.append(entry)
    return result


def prepare_collection_documents(
    workspace_id: str,
    object_id: str,
    object_name: str,
    object_type: str,
    collection_name: str,
    attribute_stats: dict,
    gap_analysis: dict,
    categorical_stats: dict | None = None,
) -> list[dict]:
    """Prepare MongoDB documents for one interval table.
    
    Returns a list of documents. Usually 1 document, but if the full document
    would exceed the safe size limit, it splits into:
    - 1 summary doc (overall stats only, small and fast to query)
    - N detail docs (per-hole stats, chunked by attribute batches)
    """
    now = datetime.now(timezone.utc)
    
    base_metadata = {
        "workspace_id": workspace_id,
        "object_id": object_id,
        "object_name": object_name,
        "object_type": object_type,
        "collection_name": collection_name,
        "timestamp": now,
        "metadata": {
            "version": "latest",
            "generated_by": "mcp_stats_to_mongo.ipynb",
        },
    }
    
    # Determine data type and build unified statistics array
    if attribute_stats:
        data_type = "numeric"
        statistics = _build_grade_stats_array(attribute_stats, include_by_hole=True)
    else:
        data_type = "categorical"
        statistics = _build_categorical_stats_array(categorical_stats, include_by_hole=True)

    # Try building a single complete document first
    full_doc = {
        **base_metadata,
        "doc_type": "complete",               # complete | summary | detail
        "data_type": data_type,
        "statistics": statistics,
        "gap_analysis": build_gap_summary(gap_analysis),
    }
    
    doc_size = estimate_doc_size(full_doc)
    full_doc["metadata"]["doc_size_bytes"] = doc_size
    
    if doc_size < SAFE_DOC_LIMIT:
        return [full_doc]
    
    # --- Document is too large: split into summary + detail chunks ---
    print(f"    {collection_name}: {doc_size / 1024 / 1024:.1f} MB exceeds limit, splitting...")
    
    # Summary document: overall stats only (no per-hole data)
    if attribute_stats:
        summary_statistics = _build_grade_stats_array(attribute_stats, include_by_hole=False)
    else:
        summary_statistics = _build_categorical_stats_array(categorical_stats, include_by_hole=False)

    summary_doc = {
        **base_metadata,
        "doc_type": "summary",
        "data_type": data_type,
        "statistics": summary_statistics,
        "gap_analysis": build_gap_summary(gap_analysis),
    }
    summary_doc["metadata"]["doc_size_bytes"] = estimate_doc_size(summary_doc)
    
    documents = [summary_doc]
    
    # Detail documents: chunk per-hole stats by attribute batches
    attr_names = list(attribute_stats.keys())
    chunk_start = 0
    chunk_idx = 0
    
    while chunk_start < len(attr_names):
        # Grow the chunk until it approaches the size limit
        chunk_end = chunk_start + 1
        
        while chunk_end <= len(attr_names):
            chunk_attrs = {
                name: {"by_hole": attribute_stats[name]["by_hole"], "hole_count": attribute_stats[name]["hole_count"]}
                for name in attr_names[chunk_start:chunk_end]
            }
            detail_doc = {
                **base_metadata,
                "doc_type": "detail",
                "chunk_index": chunk_idx,
                "attributes_in_chunk": attr_names[chunk_start:chunk_end],
                "hole_statistics": chunk_attrs,
            }
            if estimate_doc_size(detail_doc) > SAFE_DOC_LIMIT:
                chunk_end -= 1
                break
            chunk_end += 1
        
        # Ensure we make progress (at least 1 attribute per chunk)
        chunk_end = max(chunk_end, chunk_start + 1)
        
        chunk_attrs = {
            name: {"by_hole": attribute_stats[name]["by_hole"], "hole_count": attribute_stats[name]["hole_count"]}
            for name in attr_names[chunk_start:chunk_end]
        }
        detail_doc = {
            **base_metadata,
            "doc_type": "detail",
            "chunk_index": chunk_idx,
            "attributes_in_chunk": attr_names[chunk_start:chunk_end],
            "hole_statistics": chunk_attrs,
        }
        detail_doc["metadata"]["doc_size_bytes"] = estimate_doc_size(detail_doc)
        documents.append(detail_doc)
        
        chunk_start = chunk_end
        chunk_idx += 1
    
    print(f"  Split into 1 summary + {chunk_idx} detail document(s)")
    return documents


def create_grade_stats_indexes(collection):
    """Create indexes optimized for grade value queries."""
    indexes_created = []
    
    # Primary index: query by attribute name and length-weighted mean
    # Supports: "find all objects where Au LWM > 1.0"
    collection.create_index(
        [("statistics.attribute", 1), ("statistics.overall.length_weighted_mean", -1)],
        name="grade_lwm"
    )
    indexes_created.append("grade_lwm")
    
    # Secondary index: query by accumulation (grade-meters)
    # Supports: "find objects with highest Au accumulation"
    collection.create_index(
        [("statistics.attribute", 1), ("statistics.overall.accumulation_grade_meters", -1)],
        name="grade_accumulation"
    )
    indexes_created.append("grade_accumulation")
    
    # Index on max grade value
    # Supports: "find objects with peak Au values > 10"
    collection.create_index(
        [("statistics.attribute", 1), ("statistics.overall.max", -1)],
        name="grade_max"
    )
    indexes_created.append("grade_max")
    
    # Compound index for workspace-scoped grade queries
    # Supports: "find high-grade Au objects in this workspace"
    collection.create_index(
        [("workspace_id", 1), ("statistics.attribute", 1), ("statistics.overall.length_weighted_mean", -1)],
        name="workspace_grade_lwm"
    )
    indexes_created.append("workspace_grade_lwm")
    
    print(f"✓ Created {len(indexes_created)} grade query indexes: {indexes_created}")
    return indexes_created


def find_high_grade_objects(
    collection,
    grade: str,
    min_lwm: float = None,
    min_max: float = None,
    min_accumulation: float = None,
    workspace_id: str = None,
    limit: int = 20,
) -> list[dict]:
    """
    Find objects with high grade values.
    
    Args:
        grade: Grade column name (e.g., "Au", "Cu")
        min_lwm: Minimum length-weighted mean
        min_max: Minimum peak/max value
        min_accumulation: Minimum accumulation (grade-meters)
        workspace_id: Optional workspace filter
        limit: Max results to return
    """
    # Build the $elemMatch query for the statistics array
    elem_match = {"attribute": grade}
    
    if min_lwm is not None:
        elem_match["overall.length_weighted_mean"] = {"$gte": min_lwm}
    if min_max is not None:
        elem_match["overall.max"] = {"$gte": min_max}
    if min_accumulation is not None:
        elem_match["overall.accumulation_grade_meters"] = {"$gte": min_accumulation}
    
    query = {"data_type": "numeric", "statistics": {"$elemMatch": elem_match}}
    
    if workspace_id:
        query["workspace_id"] = workspace_id
    
    results = list(collection.find(
        query,
        {"object_id": 1, "object_name": 1, "statistics": 1, "timestamp": 1}
    ).sort([("statistics.overall.length_weighted_mean", -1)]).limit(limit))
    
    return results


def get_top_objects_by_grade(collection, grade: str, metric: str = "lwm", top_n: int = 10) -> list[dict]:
    """
    Get top N objects ranked by a grade metric.
    
    Args:
        grade: Grade column name
        metric: One of "lwm", "max", "accumulation"
        top_n: Number of results
    """
    # Mapping from short metric names to full field paths
    _METRIC_FIELDS = {
        "lwm": "length_weighted_mean",
        "max": "max",
        "accumulation": "accumulation_grade_meters",
    }
    overall_field = _METRIC_FIELDS.get(metric, metric)

    pipeline = [
        {"$match": {"data_type": "numeric"}},
        {"$unwind": "$statistics"},
        {"$match": {"statistics.attribute": grade}},
        {"$sort": {f"statistics.overall.{overall_field}": -1}},
        {"$limit": top_n},
        {"$project": {
            "object_id": 1,
            "object_name": 1,
            "workspace_id": 1,
            "grade": "$statistics.attribute",
            metric: f"$statistics.overall.{overall_field}",
            "timestamp": 1,
        }}
    ]
    return list(collection.aggregate(pipeline))
