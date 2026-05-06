import { getIncomers, type Edge, type Node } from "@xyflow/react";

import { MAX_AST_DEPTH, MAX_AST_FIELD_LEN, MAX_AST_NODES, MAX_AST_VALUE_LEN, astDepth, astNodeCount, type JsonAstNode } from "../../types/jsonAst";
import { graphHasDirectedCycle } from "./graphCycle";
import { CompileToAstError, NODE_TYPES } from "./compileToAST";
import { compileFlowToJsonAst } from "./compileFlowToJsonAst";

export type CanvasValidationResult = { ok: true } | { ok: false; errors: string[] };

function push(errors: string[], msg: string): void {
  errors.push(msg);
}

/** Walk JSON AST and validate leaf field/value sizes (parity with Pydantic). */
export function validateJsonAstPayload(ast: JsonAstNode): CanvasValidationResult {
  const errors: string[] = [];

  const walk = (n: JsonAstNode): void => {
    if (n.type === "condition") {
      if (!n.field || n.field.length > MAX_AST_FIELD_LEN) {
        push(errors, `Condition field must be 1–${MAX_AST_FIELD_LEN} characters`);
      }
      if (n.value !== undefined && n.value !== null && String(n.value).length > MAX_AST_VALUE_LEN) {
        push(errors, `Condition value exceeds ${MAX_AST_VALUE_LEN} characters when stringified`);
      }
      return;
    }
    for (const c of n.children) walk(c);
  };

  walk(ast);

  const d = astDepth(ast);
  if (d > MAX_AST_DEPTH) {
    push(errors, `AST depth ${d} exceeds maximum ${MAX_AST_DEPTH}`);
  }
  const c = astNodeCount(ast);
  if (c > MAX_AST_NODES) {
    push(errors, `AST node count ${c} exceeds maximum ${MAX_AST_NODES}`);
  }

  return errors.length ? { ok: false, errors } : { ok: true };
}

/** Pre-save checks: topology, logic nodes fed, no graph cycles, compiles to AST. */
export function validateCanvasForAstSave(nodes: Node[], edges: Edge[]): CanvasValidationResult {
  const errors: string[] = [];

  if (graphHasDirectedCycle(nodes, edges)) {
    push(errors, "The graph contains a directed cycle; remove edges until the flow is acyclic.");
  }

  const roots = nodes.filter((n) => n.type === NODE_TYPES.ruleRoot);
  if (roots.length !== 1) {
    push(errors, "Exactly one Rule root node is required.");
    return { ok: false, errors };
  }
  const rr = roots[0];
  const rIn = getIncomers(rr, nodes, edges);
  if (rIn.length !== 1) {
    push(errors, "Rule root must have exactly one incoming connection.");
  }

  for (const n of nodes) {
    if (n.type === NODE_TYPES.logicAnd || n.type === NODE_TYPES.logicOr) {
      const inc = getIncomers(n, nodes, edges);
      if (inc.length === 0) {
        push(errors, `${n.type === NODE_TYPES.logicAnd ? "AND" : "OR"} node “${n.id}” has no inputs — connect at least one branch before saving.`);
      }
    }
  }

  if (errors.length) return { ok: false, errors };

  try {
    const ast = compileFlowToJsonAst(nodes, edges);
    const astLimits = validateJsonAstPayload(ast);
    if (!astLimits.ok) errors.push(...astLimits.errors);
  } catch (e) {
    push(errors, e instanceof CompileToAstError ? e.message : String(e));
  }

  return errors.length ? { ok: false, errors } : { ok: true };
}

export function tryCompileFlowToJsonAst(nodes: Node[], edges: Edge[]): { ok: true; ast: JsonAstNode } | { ok: false; errors: string[] } {
  try {
    const ast = compileFlowToJsonAst(nodes, edges);
    const v = validateJsonAstPayload(ast);
    if (!v.ok) return { ok: false, errors: v.errors };
    return { ok: true, ast };
  } catch (e) {
    return { ok: false, errors: [e instanceof CompileToAstError ? e.message : String(e)] };
  }
}
