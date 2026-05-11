# JanusGraph + Cassandra (local demo)

This stack satisfies **Prompt 81**: Cassandra-backed JanusGraph (`storage.backend=cql`), **2 GiB JVM heaps** for Cassandra and JanusGraph, and a **500 MiB JanusGraph DB cache** (`cache.db-cache=true`, `cache.db-cache-size` in bytes) for fast repeated traversals.

## Files

| File | Purpose |
|------|---------|
| `janusgraph.properties` | CQL storage hostname, keyspace/DC, replication, DB cache, Lucene mixed index for local demo |
| `docker-compose.yml` | `cassandra:4.1` + `janusgraph/janusgraph:1.0.0`, heap env, property mount |
| `scripts/verify-combined-memory-under-5g.sh` | Gate: fail if combined in-use memory of both containers exceeds **5 GiB** |

## Start

```bash
docker compose -f deploy/janusgraph-cassandra-demo/docker-compose.yml up -d
```

Gremlin WebSocket: `ws://127.0.0.1:8182/gremlin`

## Gate check (memory)

With the stack running:

```bash
chmod +x deploy/janusgraph-cassandra-demo/scripts/verify-combined-memory-under-5g.sh
./deploy/janusgraph-cassandra-demo/scripts/verify-combined-memory-under-5g.sh
```

Manual inspection:

```bash
docker stats --no-stream jcd-cassandra jcd-janusgraph
```

Expect each service near **~2 GiB heap** plus modest off-heap; combined **below 5 GiB** on a healthy idle graph.

## Stop / reset

```bash
docker compose -f deploy/janusgraph-cassandra-demo/docker-compose.yml down -v
```
