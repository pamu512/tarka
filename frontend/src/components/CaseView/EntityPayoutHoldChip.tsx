import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router";
import { integrations, type PayoutDelayPayoutRow } from "../../api/client";
import { PayoutDelayHoldBadge } from "../integrations/PayoutDelayHoldBadge";

type Props = {
  tenantId: string;
  entityId: string;
};

/**
 * CaseDetail chip: shows durable payout holds for this entity (fail-soft if ingress down).
 */
export function EntityPayoutHoldChip({ tenantId, entityId }: Props): ReactElement | null {
  const [held, setHeld] = useState<PayoutDelayPayoutRow[]>([]);

  useEffect(() => {
    let cancelled = false;
    const tid = tenantId.trim();
    const eid = entityId.trim();
    if (!tid || !eid) {
      setHeld([]);
      return;
    }
    void integrations
      .payoutDelay({ tenant_id: tid, limit: 50 })
      .then((board) => {
        if (cancelled) return;
        const rows = (board.payouts ?? []).filter(
          (p) => p.entity_id === eid && p.status === "held",
        );
        setHeld(rows);
      })
      .catch(() => {
        if (!cancelled) setHeld([]);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, entityId]);

  if (held.length === 0) return null;

  const top = held[0];
  const more = held.length - 1;

  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-lg border border-violet-500/30 bg-violet-950/15 px-3 py-2"
      data-testid="entity-payout-hold-chip"
    >
      <PayoutDelayHoldBadge status={top.status} muleScore={top.mule_score} />
      <span className="text-[11px] text-gray-400 font-mono truncate max-w-[12rem]" title={top.payout_id}>
        {top.payout_id}
      </span>
      {more > 0 ? <span className="text-[10px] text-gray-500">+{more} more</span> : null}
      <Link
        to="/integrations/payout-delay"
        className="text-[11px] text-brand-400 hover:text-brand-300 ml-auto"
      >
        Payout delay board →
      </Link>
    </div>
  );
}
