# Security Policy

## Supported Versions

Tarka uses semantic versioning. Security fixes are applied to the latest stable release and, when feasible, the previous minor line.

| Version | Supported |
| ------- | --------- |
| 1.0.x   | :white_check_mark: |
| 0.9.x   | :white_check_mark: |
| < 0.9   | :x: |

## Reporting a Vulnerability

Please do **not** open public GitHub issues for security vulnerabilities.

- Report privately by emailing: **security@tarka.dev**
- Include:
  - affected component/service (for example `decision-api`, `case-api`, SDK name)
  - version/tag/commit hash
  - reproduction steps or proof of concept
  - impact assessment (data exposure, auth bypass, RCE, etc.)
  - any suggested mitigation

### Response Targets

- Initial acknowledgement: **within 24 hours**
- Triage decision (valid / needs more info / out of scope): **within 3 business days**
- Status updates: **at least every 7 days** until resolved

### Disclosure Process

1. We validate and score severity (CVSS-style internal triage).
2. We prepare and test a fix.
3. We coordinate disclosure timing with the reporter.
4. We publish a patch release and release notes.

Where possible, we credit reporters unless they request anonymity.

### Safe Harbor

We support good-faith security research. If you avoid privacy violations, data destruction, service disruption, and social engineering, we will not pursue legal action for responsible disclosure.
