"""Benchmarking utilities for MongoDB query performance profiling."""

import time
from statistics import mean, stdev


def profile_query(collection, query: dict, iterations: int = 100) -> dict:
    """Run a query multiple times and measure execution time."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        list(collection.find(query))  # Force cursor evaluation
        end = time.perf_counter()
        times.append((end - start) * 1000)  # Convert to ms
    
    return {
        "mean_ms": round(mean(times), 4),
        "stdev_ms": round(stdev(times), 4) if len(times) > 1 else 0,
        "min_ms": round(min(times), 4),
        "max_ms": round(max(times), 4),
        "iterations": iterations,
    }


def get_explain_stats(collection, query: dict) -> dict:
    """Get query execution stats from explain()."""
    explain = collection.find(query).explain()
    exec_stats = explain.get("executionStats", {})
    return {
        "docs_examined": exec_stats.get("totalDocsExamined", "N/A"),
        "keys_examined": exec_stats.get("totalKeysExamined", "N/A"),
        "execution_time_ms": exec_stats.get("executionTimeMillis", "N/A"),
        "index_used": explain.get("queryPlanner", {}).get("winningPlan", {}).get("inputStage", {}).get("indexName", "COLLSCAN"),
    }


def run_index_benchmark(collection, workspace_id: str, object_id: str):
    """Benchmark queries with and without indexes."""
    
    # Define the two indexes to test
    indexes = [
        {
            "name": "workspace_object_idx",
            "keys": [("workspace_id", 1), ("object_id", 1)],
            "query": {"workspace_id": workspace_id, "object_id": object_id},
        },
        {
            "name": "object_name_idx",
            "keys": [("object_name", 1)],
            "query": {"object_name": {"$regex": ".*", "$options": "i"}},  # Simulated search
        },
    ]
    
    results = []
    
    for idx_config in indexes:
        print(f"\n{'='*60}")
        print(f"Testing index: {idx_config['name']}")
        print(f"Query: {idx_config['query']}")
        print(f"{'='*60}")
        
        # --- Test WITHOUT index ---
        # Drop the index if it exists
        try:
            collection.drop_index(idx_config["name"])
        except Exception:
            pass  # Index didn't exist
        
        print("\nWITHOUT INDEX:")
        no_idx_profile = profile_query(collection, idx_config["query"])
        no_idx_explain = get_explain_stats(collection, idx_config["query"])
        print(f"   Mean: {no_idx_profile['mean_ms']:.4f} ms (±{no_idx_profile['stdev_ms']:.4f})")
        print(f"   Docs examined: {no_idx_explain['docs_examined']}")
        print(f"   Index used: {no_idx_explain['index_used']}")
        
        # --- Test WITH index ---
        collection.create_index(idx_config["keys"], name=idx_config["name"])
        
        print("\nWITH INDEX:")
        with_idx_profile = profile_query(collection, idx_config["query"])
        with_idx_explain = get_explain_stats(collection, idx_config["query"])
        print(f"   Mean: {with_idx_profile['mean_ms']:.4f} ms (±{with_idx_profile['stdev_ms']:.4f})")
        print(f"   Docs examined: {with_idx_explain['docs_examined']}")
        print(f"   Keys examined: {with_idx_explain['keys_examined']}")
        print(f"   Index used: {with_idx_explain['index_used']}")
        
        # Calculate improvement
        if no_idx_profile['mean_ms'] > 0:
            improvement = ((no_idx_profile['mean_ms'] - with_idx_profile['mean_ms']) / no_idx_profile['mean_ms']) * 100
            print(f"\n   ⚡ Improvement: {improvement:.1f}%")
        
        results.append({
            "index_name": idx_config["name"],
            "without_index": no_idx_profile,
            "with_index": with_idx_profile,
            "docs_examined_without": no_idx_explain['docs_examined'],
            "docs_examined_with": with_idx_explain['docs_examined'],
        })
    
    return results


def profile_high_grade_queries(collection, grade: str = "Au", iterations: int = 50):
    """
    Profile high-grade query performance with and without indexes.
    
    Tests:
    1. find_high_grade_objects with $elemMatch
    2. get_top_objects_by_grade aggregation pipeline
    """
    
    # Define the indexes we're testing
    grade_indexes = [
        ("grade_lwm", [("stats_summary.grade", 1), ("stats_summary.lwm", -1)]),
        ("grade_max", [("stats_summary.grade", 1), ("stats_summary.max", -1)]),
        ("grade_accumulation", [("stats_summary.grade", 1), ("stats_summary.accumulation", -1)]),
        ("workspace_grade_lwm", [("workspace_id", 1), ("stats_summary.grade", 1), ("stats_summary.lwm", -1)]),
    ]
    
    # Define test queries
    test_cases = [
        {
            "name": f"find_high_grade_objects({grade}, min_lwm=0.5)",
            "query": {"stats_summary": {"$elemMatch": {"grade": grade, "lwm": {"$gte": 0.5}}}},
            "type": "find",
        },
        {
            "name": f"find_high_grade_objects({grade}, min_max=5.0)",
            "query": {"stats_summary": {"$elemMatch": {"grade": grade, "max": {"$gte": 5.0}}}},
            "type": "find",
        },
        {
            "name": f"get_top_objects_by_grade({grade}, lwm, top_n=10)",
            "pipeline": [
                {"$unwind": "$stats_summary"},
                {"$match": {"stats_summary.grade": grade}},
                {"$sort": {"stats_summary.lwm": -1}},
                {"$limit": 10},
            ],
            "type": "aggregate",
        },
    ]
    
    results = []
    
    # --- Test WITHOUT indexes ---
    print("=" * 70)
    print("DROPPING GRADE INDEXES FOR BASELINE...")
    print("=" * 70)
    
    for idx_name, _ in grade_indexes:
        try:
            collection.drop_index(idx_name)
        except Exception:
            pass
    
    print("\n📊 WITHOUT INDEXES:\n")
    no_idx_results = {}
    
    for test in test_cases:
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            if test["type"] == "find":
                list(collection.find(test["query"]).limit(20))
            else:
                list(collection.aggregate(test["pipeline"]))
            end = time.perf_counter()
            times.append((end - start) * 1000)
        
        stats = {
            "mean_ms": round(mean(times), 4),
            "stdev_ms": round(stdev(times), 4) if len(times) > 1 else 0,
            "min_ms": round(min(times), 4),
            "max_ms": round(max(times), 4),
        }
        no_idx_results[test["name"]] = stats
        
        # Get explain for find queries
        if test["type"] == "find":
            explain = collection.find(test["query"]).explain()
            exec_stats = explain.get("executionStats", {})
            docs_examined = exec_stats.get("totalDocsExamined", "N/A")
            index_used = explain.get("queryPlanner", {}).get("winningPlan", {}).get("inputStage", {}).get("indexName", "COLLSCAN")
        else:
            docs_examined = "N/A (aggregate)"
            index_used = "N/A (aggregate)"
        
        print(f"   {test['name']}")
        print(f"      Mean: {stats['mean_ms']:.4f} ms (±{stats['stdev_ms']:.4f})")
        print(f"      Docs examined: {docs_examined}, Index: {index_used}\n")
    
    # --- Test WITH indexes ---
    print("\n" + "=" * 70)
    print("CREATING GRADE INDEXES...")
    print("=" * 70)
    
    for idx_name, idx_keys in grade_indexes:
        collection.create_index(idx_keys, name=idx_name)
    print(f"Created: {[name for name, _ in grade_indexes]}")
    
    print("\n📊 WITH INDEXES:\n")
    with_idx_results = {}
    
    for test in test_cases:
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            if test["type"] == "find":
                list(collection.find(test["query"]).limit(20))
            else:
                list(collection.aggregate(test["pipeline"]))
            end = time.perf_counter()
            times.append((end - start) * 1000)
        
        stats = {
            "mean_ms": round(mean(times), 4),
            "stdev_ms": round(stdev(times), 4) if len(times) > 1 else 0,
            "min_ms": round(min(times), 4),
            "max_ms": round(max(times), 4),
        }
        with_idx_results[test["name"]] = stats
        
        # Get explain for find queries
        if test["type"] == "find":
            explain = collection.find(test["query"]).explain()
            exec_stats = explain.get("executionStats", {})
            docs_examined = exec_stats.get("totalDocsExamined", "N/A")
            keys_examined = exec_stats.get("totalKeysExamined", "N/A")
            index_used = explain.get("queryPlanner", {}).get("winningPlan", {}).get("inputStage", {}).get("indexName", "COLLSCAN")
        else:
            docs_examined = "N/A"
            keys_examined = "N/A"
            index_used = "N/A (aggregate)"
        
        print(f"   {test['name']}")
        print(f"      Mean: {stats['mean_ms']:.4f} ms (±{stats['stdev_ms']:.4f})")
        print(f"      Docs examined: {docs_examined}, Keys: {keys_examined}, Index: {index_used}\n")
    
    # --- Summary ---
    print("\n" + "=" * 70)
    print("PERFORMANCE COMPARISON SUMMARY")
    print("=" * 70)
    print(f"{'Query':<50} {'No Index':>12} {'With Index':>12} {'Improvement':>12}")
    print("-" * 86)
    
    for test_name in no_idx_results:
        no_idx = no_idx_results[test_name]["mean_ms"]
        with_idx = with_idx_results[test_name]["mean_ms"]
        if no_idx > 0:
            improvement = ((no_idx - with_idx) / no_idx) * 100
            improvement_str = f"{improvement:+.1f}%"
        else:
            improvement_str = "N/A"
        
        # Truncate long names
        display_name = test_name[:48] + ".." if len(test_name) > 50 else test_name
        print(f"{display_name:<50} {no_idx:>10.4f}ms {with_idx:>10.4f}ms {improvement_str:>12}")
        
        results.append({
            "query": test_name,
            "no_index_ms": no_idx,
            "with_index_ms": with_idx,
            "improvement_pct": improvement if no_idx > 0 else None,
        })
    
    return results
