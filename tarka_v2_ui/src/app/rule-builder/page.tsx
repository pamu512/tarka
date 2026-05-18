import { RuleBuilder } from "@/components/rule-builder/RuleBuilder";
import { BROAD_RULE_SHADOW_TEST_BLOCKS } from "@/lib/compile-rule-ast";

export default function RuleBuilderPage() {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6">
      <RuleBuilder initialBlocks={BROAD_RULE_SHADOW_TEST_BLOCKS} />
    </div>
  );
}
