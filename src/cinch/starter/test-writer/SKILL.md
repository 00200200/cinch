---
name: test-writer
description: Generate comprehensive, edge-case resilient unit tests
paths:
  - "tests/**"
  - "**/*test*"
---
# Test Writer

Write focused, reproducible unit and integration tests:
1. Test boundary conditions, null/empty values, and unexpected error states.
2. Use descriptive test names following `test_<function>_<scenario>_<expected>`.
3. Prefer deterministic fixtures over network or time-dependent mocks.
4. Keep test assertions minimal and explicit.
