"""SR-10: pre-filing validation depth."""

from case_api.sar_filing_transport import validate_pre_filing


def test_validate_pre_filing_ok_json_format():
    errs = validate_pre_filing(
        {
            "filer_tin": "12-3456789",
            "financial_institution_name": "Demo Bank",
            "report_id": "r1",
            "format": "json",
            "narrative": "Suspicious activity narrative.",
        }
    )
    assert errs == []


def test_validate_pre_filing_requires_report_id():
    errs = validate_pre_filing(
        {
            "filer_tin": "12-3456789",
            "financial_institution_name": "Demo Bank",
            "format": "json",
        }
    )
    assert "missing_field:report_id" in errs


def test_validate_pre_filing_fincen_xml_requires_batch():
    errs = validate_pre_filing(
        {
            "filer_tin": "12-3456789",
            "financial_institution_name": "Demo Bank",
            "report_id": "r1",
            "format": "fincen_xml",
            "xml_content": "<root/>",
        }
    )
    assert "invalid_xml:missing_efiling_batch" in errs


def test_validate_pre_filing_fincen_xml_ok():
    errs = validate_pre_filing(
        {
            "filer_tin": "12-3456789",
            "financial_institution_name": "Demo Bank",
            "report_id": "r1",
            "format": "fincen_xml",
            "xml_content": "<EFilingBatchXML><Activity/></EFilingBatchXML>",
            "narrative": "ok",
        }
    )
    assert errs == []
