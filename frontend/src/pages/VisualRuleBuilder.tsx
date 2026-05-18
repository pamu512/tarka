import { Link } from "react-router-dom";

import { PageTitle } from "../components/PageTitle";
import { RuleBuilderCanvas } from "../components/RuleBuilder";

/**
 * Visual rule builder — drag-and-drop React Flow canvas whose save path emits a
 * `JsonAstNode` tree aligned with `decision_api.ast_models` (AND/OR + typed condition leaves).
 */
export default function VisualRuleBuilder() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <PageTitle module="rules">
        Visual rule builder
        <Link
          to="/rules/version-control"
          className="block text-xs font-normal text-brand-400 hover:text-brand-300 mt-1 w-fit"
        >
          Versioned rule control — rollback AST snapshots →
        </Link>
        <span className="block text-xs font-normal text-gray-500 mt-1">
          Drag from handles to wire <strong>Feature</strong> → <strong>Operator</strong> → <strong>AND / OR</strong> →{" "}
          <strong>Rule root</strong>. Cycles and empty logic nodes block <strong>Save AST pack</strong> (
          <code className="text-gray-400">POST /v1/rules</code> with <code className="text-gray-400">when_ast</code>). The
          live JSON panel mirrors the Python Pydantic schema. Use <strong>Validate on server</strong> for the legacy flat{" "}
          <code className="text-gray-400">when</code> compile path (<code className="text-gray-400">/v1/rules/visual/compile</code>) and{" "}
          <strong>Test rule…</strong> for dry-run.
        </span>
      </PageTitle>
      <RuleBuilderCanvas />
    </div>
  );
}
