# analytics-sink (source library)

Deploy surface: **data-plane** (`services/data-plane/src/data_plane/main.py`
mounts `analytics_sink` as a sub-app) and event-ingest CI path. This directory
is the ClickHouse sink/query source library; it has no standalone compose
service. One deploy surface, one job: data-plane.
