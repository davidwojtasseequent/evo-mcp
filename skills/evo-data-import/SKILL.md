---
name: evo-data-import
description: "Import CSV data into Evo geoscience objects — pointsets, line-segments, and downhole-collections from local files"
---

# Evo Data Import Workflow

Import geoscience data from local CSV files into the Evo platform.

## Supported Object Types

| Type | File Pattern | Use Case |
|------|--------------|----------|
| **Pointset** | Single CSV with X/Y/Z | Sample locations, sensors |
| **LineSegments** | Vertices CSV + Segments CSV | Faults, contacts, lines |
| **DownholeCollection** | Collar + Survey + Intervals | Drillhole data |

## Recommended Workflow

### Step 1: Discover Files
```
list_local_data_files(file_pattern="*.csv")
```

### Step 2: Analyze Files (Optional)
```
preview_csv_file(file_path="file1.csv")
```
This shows column names and data types to help determine column mappings.

### Step 3: Create Object (use the appropriate tool for your data type)

#### For Pointset (single CSV with coordinates):
```
build_and_create_pointset(
    workspace_id="<uuid>",
    object_path="/data/my_pointset.json",
    object_name="My Pointset",
    description="Sample locations",
    csv_file="points.csv",
    x_column="X",
    y_column="Y",
    z_column="Z",
    dry_run=True  # Validate first
)
```

#### For LineSegments (vertices + segments CSVs):
```
build_and_create_line_segments(
    workspace_id="<uuid>",
    object_path="/data/my_lines.json",
    object_name="My Lines",
    description="Fault traces",
    vertices_file="vertices.csv",
    segments_file="segments.csv",
    x_column="X",
    y_column="Y",
    z_column="Z",
    start_index_column="start_idx",
    end_index_column="end_idx",
    dry_run=True  # Validate first
)
```

#### For DownholeCollection (collar + survey + intervals):
```
build_and_create_downhole_collection(
    workspace_id="<uuid>",
    object_path="/drillholes/my_drillholes.json",
    object_name="My Drillholes",
    description="Exploration drilling",
    collar_file="collar.csv",
    survey_file="survey.csv",
    collar_id_column="HOLE_ID",
    survey_id_column="HOLE_ID",
    x_column="X",
    y_column="Y",
    z_column="Z",
    depth_column="DEPTH",
    azimuth_column="AZIMUTH",
    dip_column="DIP",
    interval_files=[
        {
            "file": "assay.csv",
            "name": "assay",
            "id_column": "HOLE_ID",
            "from_column": "FROM",
            "to_column": "TO"
        }
    ],
    dry_run=True  # Validate first
)
```

### Step 4: Create (after validation)
Run the same command with `dry_run=False` to create the object.

## Best Practices

1. **Always use dry_run=True first** — validates without creating
2. **Check column names** — use `preview_csv_file` to see available columns
3. **Review warnings** — understand data quality before proceeding
