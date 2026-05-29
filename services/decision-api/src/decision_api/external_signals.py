"""Legacy synchronous external signal providers were removed in 1.3.0-beta.

Third-party risk enrichment is asynchronous: decision-api publishes ``fraud.enrichment.request``
on NATS; integration-ingress materializes OSINT into Redis for the evaluate path (see ``async_osint_redis``).
"""

from __future__ import annotations
