from __future__ import annotations

"""SAR/STR report generation.

Generates regulatory-compliant suspicious activity reports from case data.
Supports FinCEN SAR (US), UK SAR (NCA), and generic XML/JSON formats.

FinCEN XML follows the BSA E-Filing XML schema (FinCEN SAR v1.3).
NCA JSON follows the UK NCA Defence Against Money Laundering (DAML) format.
"""


import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


@dataclass
class SARReport:
    report_id: str
    format: str
    filing_date: str
    subject: dict[str, Any]
    institution: dict[str, Any]
    narrative: str
    transactions: list[dict[str, Any]]
    xml_content: str | None = None
    json_content: dict[str, Any] | None = None
    status: str = "draft"


# FinCEN activity type codes
_FINCEN_ACTIVITY_TYPES: dict[str, str] = {
    "structuring": "29",
    "money_laundering": "19",
    "terrorist_financing": "33",
    "identity_theft": "14",
    "wire_fraud": "37",
    "check_fraud": "7",
    "credit_card_fraud": "10",
    "account_takeover": "1",
    "bribery": "5",
    "embezzlement": "11",
    "other": "24",
}

# NCA reason codes (UK)
_NCA_REASON_CODES: dict[str, str] = {
    "money_laundering": "ML",
    "terrorist_financing": "TF",
    "fraud": "FR",
    "tax_evasion": "TE",
    "sanctions": "SN",
    "other": "OT",
}


class SARGenerator:
    """Generate suspicious activity reports from case and transaction data."""

    async def generate_sar(
        self,
        case: dict[str, Any],
        transactions: list[dict[str, Any]],
        entity_data: dict[str, Any],
        format: str = "fincen_xml",
        filing_institution: dict[str, Any] | None = None,
    ) -> SARReport:
        report_id = f"SAR-{uuid.uuid4().hex[:12].upper()}"
        filing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        institution = filing_institution or _default_institution()

        subject = _extract_subject(entity_data)
        narrative = self.generate_narrative(case, transactions)

        xml_content: str | None = None
        json_content: dict[str, Any] | None = None

        if format == "fincen_xml":
            xml_content = self._build_fincen_sar(
                report_id,
                filing_date,
                subject,
                institution,
                narrative,
                case,
                transactions,
            )
        elif format == "nca_json":
            json_content = self._build_nca_sar(
                report_id,
                filing_date,
                subject,
                institution,
                narrative,
                case,
                transactions,
            )
        elif format == "generic_json":
            json_content = self._build_generic(
                report_id,
                filing_date,
                subject,
                institution,
                narrative,
                case,
                transactions,
            )
        else:
            raise ValueError(f"Unsupported SAR format: {format}")

        return SARReport(
            report_id=report_id,
            format=format,
            filing_date=filing_date,
            subject=subject,
            institution=institution,
            narrative=narrative,
            transactions=transactions,
            xml_content=xml_content,
            json_content=json_content,
            status="draft",
        )

    # ------------------------------------------------------------------
    # FinCEN BSA/SAR XML (United States)
    # ------------------------------------------------------------------

    def _build_fincen_sar(
        self,
        report_id: str,
        filing_date: str,
        subject: dict[str, Any],
        institution: dict[str, Any],
        narrative: str,
        case: dict[str, Any],
        transactions: list[dict[str, Any]],
    ) -> str:
        root = ET.Element("EFilingBatchXML")
        root.set("xmlns", "https://www.fincen.gov/bsa")

        activity = ET.SubElement(root, "Activity")
        ET.SubElement(activity, "EFilingPriorDocumentNumber").text = report_id

        # --- Filing date / type info ---
        filing = ET.SubElement(activity, "ActivityAssociation")
        ET.SubElement(filing, "InitialDesignation").text = "Initial"
        ET.SubElement(filing, "FilingDateText").text = filing_date

        # --- Activity date range from transactions ---
        tx_dates = _transaction_date_range(transactions)
        date_range = ET.SubElement(activity, "ActivityDateRange")
        ET.SubElement(date_range, "StartDateText").text = tx_dates["start"]
        ET.SubElement(date_range, "EndDateText").text = tx_dates["end"]

        # --- Suspicious activity characterization ---
        labels = case.get("labels", [])
        for label in labels:
            activity_code = _FINCEN_ACTIVITY_TYPES.get(label)
            if activity_code:
                char = ET.SubElement(activity, "SuspiciousActivityClassification")
                ET.SubElement(char, "SuspiciousActivityTypeID").text = activity_code

        if not labels or not any(lbl in _FINCEN_ACTIVITY_TYPES for lbl in labels):
            char = ET.SubElement(activity, "SuspiciousActivityClassification")
            ET.SubElement(char, "SuspiciousActivityTypeID").text = "24"  # Other

        # --- Total amounts ---
        amounts = ET.SubElement(activity, "CumulativeAmount")
        total = sum(Decimal(str(tx.get("amount", 0))) for tx in transactions)
        ET.SubElement(amounts, "CumulativeAmountValue").text = str(total)
        ET.SubElement(amounts, "CumulativeCurrencyCodeText").text = _dominant_currency(transactions)

        # --- Subject (the person/entity under investigation) ---
        subject_el = ET.SubElement(activity, "Subject")
        party = ET.SubElement(subject_el, "SubjectParty")
        name_el = ET.SubElement(party, "PartyName")
        ET.SubElement(name_el, "RawPartyFullName").text = subject.get("full_name", "Unknown")

        if subject.get("date_of_birth"):
            ET.SubElement(party, "BirthDateText").text = subject["date_of_birth"]

        for id_doc in subject.get("id_documents", []):
            ident = ET.SubElement(party, "PartyIdentification")
            ET.SubElement(ident, "PartyIdentificationTypeCode").text = id_doc.get("type", "OT")
            ET.SubElement(ident, "PartyIdentificationNumberText").text = id_doc.get("number", "")

        address = subject.get("address", {})
        if address:
            addr_el = ET.SubElement(party, "Address")
            ET.SubElement(addr_el, "RawStreetAddress1Text").text = address.get("street", "")
            ET.SubElement(addr_el, "RawCityText").text = address.get("city", "")
            ET.SubElement(addr_el, "RawStateCodeText").text = address.get("state", "")
            ET.SubElement(addr_el, "RawZIPCode").text = address.get("zip", "")
            ET.SubElement(addr_el, "RawCountryCodeText").text = address.get("country", "US")

        for acct in subject.get("accounts", []):
            acct_el = ET.SubElement(party, "Account")
            ET.SubElement(acct_el, "AccountNumberText").text = acct.get("account_number", "")
            ET.SubElement(acct_el, "AccountTypeCode").text = acct.get("type", "OT")

        # --- Filing institution ---
        filer = ET.SubElement(activity, "FilingInstitution")
        filer_party = ET.SubElement(filer, "FilingParty")
        filer_name = ET.SubElement(filer_party, "PartyName")
        ET.SubElement(filer_name, "RawPartyFullName").text = institution.get("name", "")
        filer_id = ET.SubElement(filer_party, "PartyIdentification")
        ET.SubElement(filer_id, "PartyIdentificationTypeCode").text = "EIN"
        ET.SubElement(filer_id, "PartyIdentificationNumberText").text = institution.get("ein", "")

        contact = ET.SubElement(filer, "FilingContact")
        ET.SubElement(contact, "ContactNameText").text = institution.get("contact_name", "")
        ET.SubElement(contact, "ContactPhoneNumberText").text = institution.get("contact_phone", "")

        # --- Narrative ---
        narr_el = ET.SubElement(activity, "SuspiciousActivityNarrative")
        ET.SubElement(narr_el, "NarrativeText").text = narrative

        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="unicode", xml_declaration=True)

    # ------------------------------------------------------------------
    # NCA SAR JSON (United Kingdom)
    # ------------------------------------------------------------------

    def _build_nca_sar(
        self,
        report_id: str,
        filing_date: str,
        subject: dict[str, Any],
        institution: dict[str, Any],
        narrative: str,
        case: dict[str, Any],
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        labels = case.get("labels", [])
        reason_codes = [_NCA_REASON_CODES[lbl] for lbl in labels if lbl in _NCA_REASON_CODES] or ["OT"]

        tx_dates = _transaction_date_range(transactions)
        total = float(sum(Decimal(str(tx.get("amount", 0))) for tx in transactions))

        return {
            "header": {
                "report_id": report_id,
                "report_type": "SAR",
                "submission_date": filing_date,
                "reporter": {
                    "institution_name": institution.get("name", ""),
                    "registration_number": institution.get("registration_number", ""),
                    "regulated_sector": institution.get("sector", "banking"),
                    "contact": {
                        "name": institution.get("contact_name", ""),
                        "phone": institution.get("contact_phone", ""),
                        "email": institution.get("contact_email", ""),
                    },
                },
            },
            "subject": {
                "type": subject.get("entity_type", "individual"),
                "full_name": subject.get("full_name", "Unknown"),
                "date_of_birth": subject.get("date_of_birth"),
                "nationality": subject.get("nationality"),
                "address": subject.get("address", {}),
                "identifiers": subject.get("id_documents", []),
                "accounts": subject.get("accounts", []),
            },
            "suspicious_activity": {
                "reason_codes": reason_codes,
                "activity_period": {
                    "start_date": tx_dates["start"],
                    "end_date": tx_dates["end"],
                },
                "total_value": {
                    "amount": total,
                    "currency": _dominant_currency(transactions),
                },
                "transaction_count": len(transactions),
                "transactions": [
                    {
                        "date": tx.get("timestamp", tx.get("date", "")),
                        "amount": float(tx.get("amount", 0)),
                        "currency": tx.get("currency", "GBP"),
                        "direction": tx.get("direction", "unknown"),
                        "counterparty": tx.get("counterparty", ""),
                        "reference": tx.get("reference", ""),
                    }
                    for tx in transactions
                ],
            },
            "narrative": narrative,
            "consent_requested": _should_request_consent(case),
            "defence_sar": _should_request_consent(case),
        }

    # ------------------------------------------------------------------
    # Generic JSON SAR
    # ------------------------------------------------------------------

    def _build_generic(
        self,
        report_id: str,
        filing_date: str,
        subject: dict[str, Any],
        institution: dict[str, Any],
        narrative: str,
        case: dict[str, Any],
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        tx_dates = _transaction_date_range(transactions)
        total = float(sum(Decimal(str(tx.get("amount", 0))) for tx in transactions))

        return {
            "report_id": report_id,
            "format": "generic_json",
            "filing_date": filing_date,
            "status": "draft",
            "case_reference": {
                "case_id": case.get("id", ""),
                "case_title": case.get("title", ""),
                "priority": case.get("priority", "medium"),
                "labels": case.get("labels", []),
            },
            "filing_institution": institution,
            "subject": subject,
            "activity_summary": {
                "period_start": tx_dates["start"],
                "period_end": tx_dates["end"],
                "total_amount": total,
                "currency": _dominant_currency(transactions),
                "transaction_count": len(transactions),
            },
            "transactions": [
                {
                    "id": tx.get("id", ""),
                    "timestamp": tx.get("timestamp", tx.get("date", "")),
                    "amount": float(tx.get("amount", 0)),
                    "currency": tx.get("currency", "USD"),
                    "direction": tx.get("direction", "unknown"),
                    "counterparty": tx.get("counterparty", ""),
                    "channel": tx.get("channel", ""),
                    "risk_indicators": tx.get("risk_indicators", []),
                }
                for tx in transactions
            ],
            "narrative": narrative,
            "risk_indicators": _aggregate_risk_indicators(case, transactions),
        }

    # ------------------------------------------------------------------
    # Narrative generation
    # ------------------------------------------------------------------

    def generate_narrative(self, case: dict[str, Any], transactions: list[dict[str, Any]]) -> str:
        """Auto-generate a SAR narrative following the who/what/when/where/why
        structure that regulators expect."""

        subject_name = case.get("entity_id", "Unknown Subject")
        case_title = case.get("title", "Suspicious Activity")
        labels = case.get("labels", [])
        priority = case.get("priority", "medium")
        case_id = case.get("id", "N/A")

        tx_dates = _transaction_date_range(transactions)
        total = sum(Decimal(str(tx.get("amount", 0))) for tx in transactions)
        currencies = set(tx.get("currency", "USD") for tx in transactions)
        currency_str = "/".join(sorted(currencies)) if currencies else "USD"
        counterparties = set(tx.get("counterparty", "") for tx in transactions if tx.get("counterparty"))

        sections: list[str] = []

        # WHO
        sections.append(
            f"This report concerns suspicious activity involving the subject "
            f'identified as "{subject_name}" (internal case reference: {case_id}). '
            f"The activity was flagged as {priority}-priority."
        )

        # WHAT
        activity_desc = _describe_labels(labels)
        sections.append(
            f"The suspicious activity involves {activity_desc}. "
            f"A total of {len(transactions)} transaction(s) were identified "
            f"with a cumulative value of {currency_str} {total:,.2f}."
        )

        # WHEN
        sections.append(f"The suspicious transactions occurred between {tx_dates['start']} and {tx_dates['end']}.")

        # WHERE / counterparties
        if counterparties:
            cp_list = ", ".join(sorted(counterparties)[:10])
            sections.append(f"Transactions involved the following counterparties: {cp_list}.")

        # Transaction pattern analysis
        patterns = _detect_patterns(transactions)
        if patterns:
            sections.append("The following patterns were observed: " + " ".join(patterns))

        # Risk indicators from labels
        risk_notes = _narrative_risk_notes(labels)
        if risk_notes:
            sections.append(risk_notes)

        # WHY
        sections.append(
            f"Based on the transaction patterns, risk indicators, and case "
            f"investigation findings, the institution believes this activity "
            f"is suspicious and warrants regulatory reporting as described in "
            f'the case titled "{case_title}".'
        )

        return "\n\n".join(sections)


# ======================================================================
# Private helpers
# ======================================================================


def _default_institution() -> dict[str, Any]:
    return {
        "name": "Filing Institution",
        "ein": "00-0000000",
        "registration_number": "",
        "sector": "banking",
        "contact_name": "Compliance Officer",
        "contact_phone": "",
        "contact_email": "",
    }


def _extract_subject(entity_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_type": entity_data.get("type", "individual"),
        "full_name": entity_data.get("full_name", entity_data.get("name", "Unknown")),
        "date_of_birth": entity_data.get("date_of_birth"),
        "nationality": entity_data.get("nationality"),
        "address": entity_data.get("address", {}),
        "id_documents": entity_data.get("id_documents", []),
        "accounts": entity_data.get("accounts", []),
        "email": entity_data.get("email"),
        "phone": entity_data.get("phone"),
    }


def _transaction_date_range(transactions: list[dict[str, Any]]) -> dict[str, str]:
    today = date.today().isoformat()
    if not transactions:
        return {"start": today, "end": today}
    dates: list[str] = []
    for tx in transactions:
        d = tx.get("timestamp") or tx.get("date") or ""
        if d:
            dates.append(str(d)[:10])
    if not dates:
        return {"start": today, "end": today}
    dates.sort()
    return {"start": dates[0], "end": dates[-1]}


def _dominant_currency(transactions: list[dict[str, Any]]) -> str:
    if not transactions:
        return "USD"
    freq: dict[str, int] = {}
    for tx in transactions:
        cur = tx.get("currency", "USD")
        freq[cur] = freq.get(cur, 0) + 1
    return max(freq, key=freq.get)  # type: ignore[arg-type]


def _should_request_consent(case: dict[str, Any]) -> bool:
    """UK-specific: consent SARs are required when the institution needs
    permission from the NCA to proceed with a transaction."""
    labels = case.get("labels", [])
    return "consent_required" in labels or case.get("status") == "pending_consent"


def _describe_labels(labels: list[str]) -> str:
    if not labels:
        return "unspecified suspicious activity"
    readable = [lbl.replace("_", " ") for lbl in labels]
    if len(readable) == 1:
        return readable[0]
    return ", ".join(readable[:-1]) + " and " + readable[-1]


def _detect_patterns(transactions: list[dict[str, Any]]) -> list[str]:
    """Identify common suspicious transaction patterns."""
    patterns: list[str] = []

    if not transactions:
        return patterns

    amounts = [Decimal(str(tx.get("amount", 0))) for tx in transactions]

    # Structuring: multiple transactions just under a reporting threshold
    threshold = Decimal("10000")
    near_threshold = [a for a in amounts if Decimal("8000") <= a < threshold]
    if len(near_threshold) >= 3:
        patterns.append(
            f"{len(near_threshold)} transactions were structured just below "
            f"the {threshold:,.0f} reporting threshold, suggesting deliberate "
            f"structuring to avoid currency transaction reports."
        )

    # Rapid succession: many transactions in a short period
    if len(transactions) >= 5:
        dates = sorted(
            (tx.get("timestamp") or tx.get("date", "") for tx in transactions),
            key=str,
        )
        dates = [d for d in dates if d]
        if len(dates) >= 2:
            try:
                first = datetime.fromisoformat(str(dates[0])[:19])
                last = datetime.fromisoformat(str(dates[-1])[:19])
                span_days = max((last - first).days, 1)
                tx_per_day = len(transactions) / span_days
                if tx_per_day > 5:
                    patterns.append(f"High transaction velocity of {tx_per_day:.1f} transactions per day over {span_days} days.")
            except (ValueError, TypeError):
                pass

    # Round amounts
    round_count = sum(1 for a in amounts if a > 0 and a % 1000 == 0)
    if round_count >= 3:
        patterns.append(f"{round_count} transactions used round amounts (multiples of 1,000), which may indicate layering activity.")

    # Unusual direction split
    directions = [tx.get("direction") for tx in transactions]
    inbound = sum(1 for d in directions if d in ("credit", "inbound", "in"))
    outbound = sum(1 for d in directions if d in ("debit", "outbound", "out"))
    if inbound > 0 and outbound > 0 and len(transactions) >= 4:
        patterns.append(f"Funds were received ({inbound} inbound) and quickly moved ({outbound} outbound), consistent with pass-through activity.")

    return patterns


def _narrative_risk_notes(labels: list[str]) -> str:
    notes: list[str] = []
    label_set = set(labels)

    if "structuring" in label_set:
        notes.append("Transactions appear to be structured to avoid regulatory reporting thresholds.")
    if "money_laundering" in label_set:
        notes.append("Activity is consistent with money laundering typologies, including layering through multiple accounts.")
    if "terrorist_financing" in label_set:
        notes.append("Activity patterns raise concerns about potential terrorist financing, including transfers to high-risk jurisdictions.")
    if "identity_theft" in label_set:
        notes.append("Identity verification discrepancies suggest possible use of stolen or synthetic identities.")
    if "account_takeover" in label_set:
        notes.append("Behavioral anomalies and device signal changes indicate a possible account takeover event.")

    if not notes:
        return ""
    return "Risk assessment notes: " + " ".join(notes)


def _aggregate_risk_indicators(case: dict[str, Any], transactions: list[dict[str, Any]]) -> list[str]:
    indicators: list[str] = []

    labels = case.get("labels", [])
    for label in labels:
        indicators.append(f"case_label:{label}")

    if case.get("priority") in ("critical", "high"):
        indicators.append("high_priority_case")

    for tx in transactions:
        for ri in tx.get("risk_indicators", []):
            if ri not in indicators:
                indicators.append(ri)

    return indicators
