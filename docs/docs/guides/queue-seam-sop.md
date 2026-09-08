# Queue seam SOP

Connect the buyer’s existing CX / issue tool. Leftovers stay residual. Promote / label loop is unchanged.

1. Leave `QUEUE_WEBHOOK_URL` empty until the buyer webhook exists (off).
2. Set URL + optional secret. Evaluate/mint must keep succeeding if the webhook is down.
3. CX close → signed `POST /v1/webhooks/disposition` with `evaluation_token` + `disposition_code` or `label_kind`.
4. Labels bind to receipts. They do not Promote. Model never Promotes.

See [queue-seam-v1](../../contracts/queue-seam-v1.md) and [analyst-control-loop](analyst-control-loop.md).
