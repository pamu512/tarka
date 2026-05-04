import { PageTitle } from "../components/PageTitle";
import { RuleBuilderCanvas } from "../components/RuleBuilder";

/**
 * Visual rule builder — React Flow canvas compiles to `VisualAstPack` / Rust `when` JSON
 * (`compileToAST`, `POST /v1/rules/visual/compile`, dry-run `POST /v1/rules/visual/evaluate-dry-run`).
 */
export default function VisualRuleBuilder() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <PageTitle module="rules">
        Visual rule builder
        <span className="block text-xs font-normal text-gray-500 mt-1">
          Node-based editor: <strong>Feature</strong> → <strong>Operator</strong> → <strong>AND / OR</strong> →{" "}
          <strong>Rule output</strong>. Connections are validated so numeric operators cannot wire directly to string-only
          features without an operator in between. OR branches compile to multiple flat rules for the JSON/Rust path; use{" "}
          <code className="text-gray-400">POST /v1/rules/visual/compile/rego</code> for nested boolean logic in OPA.
        </span>
      </PageTitle>
      <RuleBuilderCanvas />
    </div>
  );
}
