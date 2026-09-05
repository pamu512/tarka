import { getIncomers, type Edge, type Node } from "@xyflow/react";

import { CATALOG_HOPS } from "../../domain/authorCatalog";
import { emitHopPack, type HopSentence } from "../../utils/sentencePack";
import { NODE_TYPES } from "./compileToAST";

export type HopEtypeWhenAst = { type: "graph_v1"; atom: "has_etype"; etype: string };

export function compileHopEtypeFromCanvas(
  nodes: Node[],
  edges: Edge[],
):
  | { ok: true; etype: string; when_ast: HopEtypeWhenAst; tags: string[] }
  | { ok: false } {
  const roots = nodes.filter((n) => n.type === NODE_TYPES.ruleRoot);
  if (roots.length !== 1) return { ok: false };
  const incomers = getIncomers(roots[0], nodes, edges);
  if (incomers.length !== 1) return { ok: false };
  const hop = incomers[0];
  if (hop.type !== NODE_TYPES.hopEtype) return { ok: false };
  const etype = (hop.data as { etype?: unknown }).etype;
  if (typeof etype !== "string" || !(CATALOG_HOPS as readonly string[]).includes(etype)) {
    return { ok: false };
  }
  const pack = emitHopPack({ etype: etype as HopSentence["etype"] });
  const rule = (pack.rules as Array<{ when_ast?: HopEtypeWhenAst; tags?: string[] }>)[0];
  if (!rule?.when_ast || !rule.tags) return { ok: false };
  return { ok: true, etype, when_ast: rule.when_ast, tags: rule.tags };
}
