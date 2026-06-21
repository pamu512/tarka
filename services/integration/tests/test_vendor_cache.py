import json

from tarka_vendor_finops.cache import VendorSignalCache


def test_unwrap_positive_and_negative() -> None:
    pos = {"__meta__": {"negative": False}, "payload": {"a": 1}}
    n, p = VendorSignalCache.unwrap_entry(pos)
    assert not n and p == {"a": 1}

    neg = json.loads(
        json.dumps(
            {
                "__meta__": {
                    "negative": True,
                    "status_code": 404,
                    "error_class": "HTTPNotFound",
                    "message": "x",
                },
                "payload": None,
            }
        )
    )
    n2, p2 = VendorSignalCache.unwrap_entry(neg)
    assert n2 and p2 is None
