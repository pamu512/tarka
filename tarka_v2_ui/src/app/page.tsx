"use client";

import { useCallback, useState } from "react";
import { DecisionDetail } from "@/components/decision-detail";
import { TransactionTicker } from "@/components/transaction-ticker";

export default function HomePage() {
  const [detailTxnId, setDetailTxnId] = useState<string | null>(null);
  const closeDetail = useCallback(() => setDetailTxnId(null), []);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col gap-4 p-4">
      {detailTxnId ? (
        <DecisionDetail
          key={detailTxnId}
          transactionId={detailTxnId}
          onClose={closeDetail}
        />
      ) : null}
      <TransactionTicker limit={20} pollIntervalMs={2000} onRowSelect={setDetailTxnId} />
    </div>
  );
}
