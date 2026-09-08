-- EXAMPLE only. Buyer owns the warehouse. Tarka does not host it.
SELECT r.evaluation_token, r.pack_hash, l.label_kind
FROM receipts r
JOIN labels l USING (evaluation_token);
