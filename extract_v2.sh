#!/bin/bash

# Tarka V2 Surgical Extraction Script
# This will extract ONLY the highest-value, audit-first modules into a new 'tarka_v2_core' directory.
# Everything else gets boxed up into 'legacy_attic' to instantly clear your working context.

echo "[*] Initiating Tarka V2 Surgical Extraction..."

# Create the new clean environments
mkdir -p tarka_v2_core
mkdir -p legacy_attic

# The exact paths to salvage based on the V2 blueprint. 
# Converts the python module dots to filepaths.
declare -a SALVAGE_PATHS=(
    # 1. Ingestion & Audit
    "services/ingestor/src/ingestor/manifest_schema"
    "services/event-ingest/src/event_ingest/ingest_contract"
    "services/core/src/tarka_core/engine_adapter"
    "services/shared/tarka_shared/audit_trail"
    "services/legacy_v1_decision_api/src/decision_api/decision_log"
    
    # 2. Rule Engine & AST
    "services/core/src/tarka_core/visual_rule_ast"
    "services/core/src/tarka_core/ast_definition"
    "services/legacy_v1_decision_api/src/decision_api/json_rules"
    "services/legacy_v1_decision_api/src/decision_api/rule_compiler_api"
    
    # 3. AI Insights & ONNX
    "services/signal-api/src/signal_api/onnx_hot_reload"
    "services/ml_sidecar/onnx_engine"
    "services/ml-scoring/training/train_anomaly_model"
    "services/ml-scoring/src/ml_scoring/shap_explainer"
    "services/legacy_v1_decision_api/src/decision_api/inference_build"
    
    # 4. Omnipresent Copilot
    "services/agent/shadow_copilot"
    "services/investigation-agent/src/investigation_agent/copilot_hardening"
    "services/investigation-agent/src/investigation_agent/chat_bridge/workflow_bridge"
    "services/investigation-agent/src/investigation_agent/llm_health"
    "services/legacy_v1_decision_api/src/decision_api/shadow_evaluator"
)

for item in "${SALVAGE_PATHS[@]}"; do
    # Try copying as a directory first, then fallback to checking for a .py file
    if [ -d "$item" ]; then
        echo "[+] Salvaging directory: $item"
        mkdir -p "tarka_v2_core/$(dirname $item)"
        cp -r "$item" "tarka_v2_core/$item"
    elif [ -f "${item}.py" ]; then
        echo "[+] Salvaging file: ${item}.py"
        mkdir -p "tarka_v2_core/$(dirname $item)"
        cp "${item}.py" "tarka_v2_core/${item}.py"
    else
        echo "[!] WARNING: Could not locate $item or ${item}.py (Skipping)"
    fi
done

echo "[*] Archiving bloat..."
# Move the entire massive services folder out of the way
mv services legacy_attic/

echo "[*] Extraction complete."
echo "Your lean, audit-first V2 core is now ready in ./tarka_v2_core"
