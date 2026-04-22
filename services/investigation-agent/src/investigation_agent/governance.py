from __future__ import annotations
from typing import Literal

"""Regional AI governance overlays for the Investigation Copilot (prompt + metadata).

These blocks align *product behavior* with common expectations in major jurisdictions.
They are not legal advice; each deployment must be validated by counsel against the
customer's use case, sector, and contracts.
"""
GovernanceProfile = Literal["us", "eu_uk", "global"]

_PROFILE_ALIASES: dict[str, GovernanceProfile] = {
    "us": "us",
    "usa": "us",
    "united_states": "us",
    "eu_uk": "eu_uk",
    "eu-uk": "eu_uk",
    "eu": "eu_uk",
    "uk": "eu_uk",
    "eea": "eu_uk",
    "gdpr": "eu_uk",
    "global": "global",
    "intl": "global",
    "international": "global",
}


def normalize_governance_profile(raw: str | None) -> GovernanceProfile:
    if not raw or not str(raw).strip():
        return "global"
    key = str(raw).strip().lower().replace(" ", "_")
    return _PROFILE_ALIASES.get(key, "global")


def regional_system_prompt_append(profile: GovernanceProfile) -> str:
    """Append to the copilot system prompt (after base security + workflow rules)."""
    if profile == "us":
        return (
            "\n\nREGIONAL GOVERNANCE (United States — operational alignment):\n"
            "- Frame outputs for teams subject to U.S. supervisory expectations in financial services "
            "(e.g. model risk management, fair lending, UDAAP-style fairness narratives) and emerging "
            "state AI / consumer-disclosure laws where applicable.\n"
            "- Emphasize **human decision-making** for adverse actions affecting consumers; the copilot "
            "supports analysis and documentation, not final credit or fraud disposition by automation alone.\n"
            "- When discussing populations or attributes, avoid discriminatory proxies; recommend **fairness "
            "testing, documentation, and escalation** to compliance — not ad-hoc profiling shortcuts.\n"
            "- Map to **NIST AI RMF**-style practice where helpful: govern, map, measure, manage — with "
            "evidence from tools and audit trails.\n"
            "- Never claim SOC 2, HIPAA, or regulatory approval unless the deployment has actually achieved it.\n"
        )
    if profile == "eu_uk":
        return (
            "\n\nREGIONAL GOVERNANCE (EU / UK — operational alignment):\n"
            "- Assume **UK GDPR / EU GDPR** and **EU AI Act** style obligations may apply depending on role "
            "(provider vs deployer) and risk class. The copilot is a **support tool**; humans remain "
            "accountable for decisions with legal or similarly significant effects.\n"
            "- Stress **data minimization**: only use fields and tool results needed for the investigation; "
            "do not suggest collecting sensitive attributes unless strictly necessary and lawful.\n"
            "- Where automated processing could affect individuals, remind analysts of **transparency, "
            "human oversight, and challenge rights** — operational guidance only; legal interpretation belongs "
            "to the customer's DPO / counsel.\n"
            "- For **high-risk AI** scenarios (as defined in applicable law), emphasize **logging, "
            "documentation, accuracy, robustness, and human-in-the-loop** for material outcomes.\n"
            "- **International transfers**: do not assume transfers to non-adequate countries are lawful; "
            "flag that subprocessors and LLM hosting need appropriate safeguards (SCCs, DPA, etc.).\n"
            "- ICO / EDPB guidance on AI and automated decision-making should inform process design — cite "
            "internal policy, not statutes, in user-facing answers unless asked for general education.\n"
        )
    return (
        "\n\nREGIONAL GOVERNANCE (Global — operational alignment):\n"
        "- Apply **defensive defaults**: human accountability, tool-grounded statements, minimal necessary "
        "data, and clear separation between **advisory** copilot output and **authoritative** systems of record.\n"
        "- Encourage alignment with **ISO/IEC 42001**-style AI management themes (governance, risk, "
        "lifecycle, documentation) where organizations pursue certification.\n"
        "- Remind users that **local law, sector regulation, and contracts** may impose stricter rules than "
        "this baseline; escalate to legal/compliance when uncertain.\n"
        "- Do not imply the platform is certified or compliant with a specific regime unless the deployer "
        "has verified that claim.\n"
    )


def governance_profile_label(profile: GovernanceProfile) -> str:
    if profile == "us":
        return "United States"
    if profile == "eu_uk":
        return "EU / UK"
    return "Global"


def governance_profile_references(profile: GovernanceProfile) -> list[str]:
    """Short reference list for `/v1/governance` and docs (not exhaustive)."""
    if profile == "us":
        return [
            "NIST AI Risk Management Framework (AI RMF)",
            "NIST GenAI Profile (where applicable)",
            "U.S. financial institution model risk management (SR 11-7 style) for relevant deployments",
            "State AI / consumer laws (jurisdiction-specific)",
        ]
    if profile == "eu_uk":
        return [
            "Regulation (EU) 2024/1689 (EU AI Act) — risk class & obligations depend on use case",
            "EU GDPR / UK GDPR — lawful basis, transparency, Art. 22 automated decision-making",
            "ICO guidance on AI and data protection (UK)",
            "EDPB guidelines relevant to automated processing (EU)",
        ]
    return [
        "ISO/IEC 42001 (AI management systems — optional certification path)",
        "OECD AI Principles",
        "Contractual and local statutory requirements (varies by country)",
    ]
