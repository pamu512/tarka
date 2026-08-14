// JanusGraph demo: unique composite byTenantExternal + mixed vertexSearch on backend "search".
// graph-service submits the same schema on first Gremlin connect; this file is for empty clusters
// and operators (bin/gremlin.sh). Do not interpolate user input. Idempotent if indexes exist.
//
// :remote connect tinkerpop.server conf/remote.yaml
// :remote console
//   then paste, or: bin/gremlin.sh -e /etc/opt/janusgraph/ensure-indexes.groovy

import org.apache.tinkerpop.gremlin.structure.Vertex
import org.janusgraph.core.schema.Mapping
import org.janusgraph.core.schema.SchemaStatus

mgmt = graph.openManagement()
try {
  tid = mgmt.getPropertyKey('tenant_id')
  if (tid == null) { tid = mgmt.makePropertyKey('tenant_id').dataType(String.class).make() }
  eid = mgmt.getPropertyKey('external_id')
  if (eid == null) { eid = mgmt.makePropertyKey('external_id').dataType(String.class).make() }
  for (name in ['email', 'device_id', 'address', 'line1', 'phone', 'ip', 'user_id', 'card_id']) {
    pk = mgmt.getPropertyKey(name)
    if (pk == null) { mgmt.makePropertyKey(name).dataType(String.class).make() }
  }
  if (mgmt.getGraphIndex('byTenantExternal') == null) {
    mgmt.buildIndex('byTenantExternal', Vertex.class).addKey(tid).addKey(eid).unique().buildCompositeIndex()
  }
  if (mgmt.getGraphIndex('vertexSearch') == null) {
    b = mgmt.buildIndex('vertexSearch', Vertex.class)
    b.addKey(tid, Mapping.STRING.asParameter())
    b.addKey(eid, Mapping.TEXTSTRING.asParameter())
    for (name in ['email', 'device_id', 'address', 'line1', 'phone', 'ip', 'user_id', 'card_id']) {
      b.addKey(mgmt.getPropertyKey(name), Mapping.TEXTSTRING.asParameter())
    }
    b.buildMixedIndex('search')
  }
  mgmt.commit()
} catch (Exception e) {
  try { mgmt.rollback() } catch (Exception ignored) {}
  throw e
}
