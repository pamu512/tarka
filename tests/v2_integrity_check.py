import sys
import os

CORE_BASE = os.path.abspath("tarka_v2_core")

# This will find any directory named 'tarka_shared' or 'ingestor' and add its PARENT to sys.path
for root, dirs, files in os.walk(CORE_BASE):
    if 'tarka_shared' in dirs or 'ingestor' in dirs:
        if root not in sys.path:
            sys.path.append(root)

print("[*] Testing Tarka V2 Integrity (Recursive Search)...")

try:
    # 1. Test Audit-First Foundation
    from tarka_shared.audit_trail import AuditLog
    print("✅ SUCCESS: AuditLog found.")
    
    # 2. Test Ingestion Contract
    from ingestor.manifest_schema import TransactionSchema
    print("✅ SUCCESS: Ingestion Schema found.")
    
    print("\n--- INTEGRITY PASSED ---")
    print("Foundation is locked. Ready to wire Shadow AI.")

except ImportError as e:
    print(f"\n❌ FAILURE: {e}")
    print("\nDEBUG: Current sys.path entries added:")
    for path in sys.path:
        if "tarka_v2_core" in path:
            print(f" - {path}")
    sys.exit(1)
