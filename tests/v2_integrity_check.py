import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for candidate in (
    REPO / "packages" / "shared-core",
    REPO / "services" / "ingestor" / "src",
    REPO / "services" / "ingestor",
):
    p = str(candidate)
    if p not in sys.path:
        sys.path.insert(0, p)

print("[*] Testing Tarka V2 integrity (v1.3 layout)...")

try:
    from tarka_shared.audit_trail import AuditLog

    print("✅ SUCCESS: AuditLog found.")

    try:
        from ingestor.manifest_schema import TransactionSchema
    except ImportError as e:
        if getattr(e, "name", "") == "tarka" or "No module named 'tarka'" in str(e):
            print(
                "⚠️  SKIP: TransactionSchema requires tarka-py "
                "(cd crates/tarka-py && maturin develop)"
            )
            print("\n--- INTEGRITY PASSED (partial; install tarka-py for full check) ---")
            raise SystemExit(0) from e
        raise

    print("✅ SUCCESS: Ingestion Schema found.")
    print("\n--- INTEGRITY PASSED ---")
    print("Foundation is locked. Ready to wire Shadow AI.")

except ImportError as e:
    print(f"\n❌ FAILURE: {e}")
    print("\nDEBUG: Current sys.path entries added:")
    for path in sys.path[:12]:
        print(f" - {path}")
    sys.exit(1)
