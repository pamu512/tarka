# False-positive support kit

What support and dispute teams can say after an analyst clears a false positive —
without leaking PII or raw payloads.

## Safe fields (share)

| Field | Source |
|-------|--------|
| Case ID | CaseDetail |
| Tenant ID | CaseDetail |
| Entity ID | CaseDetail (internal id — confirm policy before external email) |
| Trace ID | Decision audit |
| Decision / score | Decision audit |
| Rule hits / tags (capped) | Decision audit |
| Disposition reason code | `disposition:*` label |
| Recommended action | Decision audit |

Use **Copy support-safe summary** on CaseDetail to build this packet.

## Never share

- Raw evaluate / SDK payload (emails, phone, full address, card PAN/token dumps)
- Full graph neighborhood exports
- SAR investigative notes / FinCEN package contents
- Internal maker-checker actor ids beyond “second review completed”

## Ops path

1. Queue → CaseDetail → review evidence  
2. Terminal disposition with reason `FALSE_POSITIVE` / `CUSTOMER_CLEARED`  
3. Optional playbook `close_false_positive`  
4. Copy support-safe summary → edit wording → send  

See [golden-analyst-loop.md](./golden-analyst-loop.md).

## Sample customer wording

> We reviewed this decision using our risk controls. If this was a false positive,
> we can clear the hold after a second review. Please reference Case ID `…` and
> Trace ID `…` so we can locate the audited decision.

## Dispute rebuttal packet

Prefer the evidence ZIP / act pack for merchant networks. For customer support,
stick to the support-safe summary — same audit row, fewer fields.
