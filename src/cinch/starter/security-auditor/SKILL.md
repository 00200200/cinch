---
name: security-auditor
description: Audit source code for vulnerabilities and dangerous API patterns
paths:
  - "**/*.py"
  - "**/*.js"
  - "**/*.ts"
  - "**/*.go"
---
# Security Auditor

Audit proposed code changes against the OWASP Top 10 guidelines:
1. **Injection:** Ensure all database queries use parameterized SQL; avoid shell execution.
2. **Access Control:** Verify tenant-scoped model lookups.
3. **Secrets:** Flag hardcoded API keys, bearer tokens, and credentials.
4. **Dependencies:** Validate that external package imports are recognized and pinned.
