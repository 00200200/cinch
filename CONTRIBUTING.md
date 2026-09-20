# Contributing to Cinch

Thanks for helping build universal agent and skill configuration across every AI harness!

Cinch operates under three core principles:
1. **Local-first & Zero Telemetry:** No servers, no network calls during init, no phone-home analytics.
2. **Vendor Accuracy:** Every target path and dialect emitted is backed by vendor documentation and verified with automated tests. No guessing.
3. **Safety First:** Existing hand-crafted rule files are never silently overwritten.

---

## 🛠️ Development Setup

Cinch uses [Astral `uv`](https://github.com/astral-sh/uv) for fast, reproducible dependency management.

```bash
# 1. Clone the repository
git clone https://github.com/00200200/cinch.git
cd cinch

# 2. Run tests
uv run pytest

# 3. Lint and format checks
uv run ruff check src tests
uv run ruff format --check src tests
```

---

## 🧩 Adding a New Dialect Adapter

To add support for a new AI harness:

1. **Check Vendor Documentation:** Obtain the official vendor specification for instruction/skill/rule files and their exact paths and frontmatter schemas.
2. **Add Adapter in [`src/cinch/adapters.py`](src/cinch/adapters.py):**
   Implement the `Adapter` protocol:
   ```python
   class MyHarnessAdapter:
       target = "myharness"

       def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
           # Convert canonical Doc to native RenderedFile(s)
           ...
   ```
3. **Register Adapter:** Add to `ADAPTERS` dictionary in `adapters.py`.
4. **Update Catalog in [`src/cinch/catalog.py`](src/cinch/catalog.py):** Add definition to `HARNESSES` and `HARNESS_ORDER`.
5. **Add Tests:** Add test cases in [`tests/test_translation.py`](tests/test_translation.py) checking rendered outputs against expected native dialect formats.

---

## 🧪 Running Tests & Conformance

```bash
# Run all test suites
uv run pytest -v

# Run translation engine tests only
uv run pytest tests/test_translation.py -v
```

Before submitting a pull request, ensure all tests pass and formatting conforms to project standards:
```bash
uv run ruff check --fix src tests
uv run ruff format src tests
uv run pytest
```
