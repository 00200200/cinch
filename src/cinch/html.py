"""Standalone searchable single-file HTML & documentation catalog generator.

Generates self-contained, zero-dependency HTML catalogs with embedded fuzzy search,
dark mode toggle, dialect compatibility pills, and one-click clipboard copying.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from cinch.adapters import get_adapter, render_cinch_skill
from cinch.catalog import HARNESS_ORDER, tags_for
from cinch.doc import Doc, parse_doc
from cinch.inventory import STARTER_DIR, Item


def discover_skills(
    project_root: Path | str = ".",
    extra_roots: tuple[Path, ...] = (),
    include_starter: bool = True,
) -> list[Doc]:
    """Discover all skill documents in project directories and optional starter set."""
    root = Path(project_root).resolve()
    skills_map: dict[str, Doc] = {}

    roots_to_scan = [
        root / rel
        for rel in (
            ".skills",
            "skills",
            ".claude/skills",
            ".agents/skills",
            ".cursor/skills",
            ".cinch/skills",
        )
        if (root / rel).is_dir()
    ]
    for extra in extra_roots:
        if extra.is_dir():
            roots_to_scan.append(extra)

    if include_starter and STARTER_DIR.is_dir():
        roots_to_scan.append(STARTER_DIR)

    for scan_dir in roots_to_scan:
        if (scan_dir / "SKILL.md").is_file():
            try:
                doc = parse_doc(
                    Item(kind="skill", name=scan_dir.name, source=scan_dir, tags=frozenset())
                )
                skills_map.setdefault(doc.name, doc)
            except Exception:
                pass
            continue

        for skill_md in sorted(scan_dir.rglob("SKILL.md")):
            skill_dir = skill_md.parent
            try:
                doc = parse_doc(
                    Item(kind="skill", name=skill_dir.name, source=skill_dir, tags=frozenset())
                )
                skills_map.setdefault(doc.name, doc)
            except Exception:
                pass

    return sorted(skills_map.values(), key=lambda d: d.name)


def _render_skill_card_data(doc: Doc) -> dict[str, Any]:
    """Extract serializable display and clipboard data for a single skill."""
    tags_set = set(tags_for(doc.name))
    if "tags" in doc.extra_meta and isinstance(doc.extra_meta["tags"], (list, tuple, set)):
        tags_set.update(str(t) for t in doc.extra_meta["tags"])
    tags = sorted(tags_set)

    # Render dialect-specific versions for one-click clipboard copying
    canonical = render_cinch_skill(doc)
    claude_text = ""
    cursor_text = ""
    try:
        claude_rendered = get_adapter("claude").render(doc)
        if claude_rendered:
            claude_text = claude_rendered[0].text
    except Exception:
        claude_text = canonical

    try:
        cursor_rendered = get_adapter("cursor").render(doc)
        if cursor_rendered:
            cursor_text = cursor_rendered[0].text
    except Exception:
        cursor_text = canonical

    return {
        "name": doc.name,
        "kind": doc.kind,
        "description": doc.description,
        "body": doc.body,
        "canonical": canonical,
        "claude": claude_text,
        "cursor": cursor_text,
        "tags": tags,
        "paths": list(doc.paths),
        "requires": list(doc.requires),
        "dialects": list(HARNESS_ORDER),
    }


def generate_html_catalog(
    skills: list[Doc] | dict[str, Doc],
    project_name: str = "Cinch Skills Catalog",
) -> str:
    """Generate a self-contained single-file HTML documentation catalog."""
    skill_list = list(skills.values()) if isinstance(skills, dict) else skills
    cards_data = [_render_skill_card_data(doc) for doc in skill_list]

    all_tags = sorted({t for item in cards_data for t in item["tags"]})
    tag_buttons = "".join(
        f'<button class="tag-btn" data-tag="{html.escape(t)}">{html.escape(t)}</button>'
        for t in all_tags
    )

    json_payload = json.dumps(cards_data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(project_name)}</title>
<style>
:root {{
  --bg: #f8fafc;
  --bg-card: #ffffff;
  --text: #0f172a;
  --text-muted: #64748b;
  --border: #e2e8f0;
  --primary: #3b82f6;
  --primary-hover: #2563eb;
  --badge-bg: #f1f5f9;
  --badge-text: #475569;
  --pill-bg: #e0e7ff;
  --pill-text: #3730a3;
  --code-bg: #0f172a;
  --code-text: #f8fafc;
  --shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
}}
[data-theme="dark"] {{
  --bg: #090d16;
  --bg-card: #131b2e;
  --text: #f1f5f9;
  --text-muted: #94a3b8;
  --border: #1e293b;
  --primary: #60a5fa;
  --primary-hover: #3b82f6;
  --badge-bg: #1e293b;
  --badge-text: #cbd5e1;
  --pill-bg: #1e1b4b;
  --pill-text: #c7d2fe;
  --code-bg: #020617;
  --code-text: #e2e8f0;
  --shadow: 0 4px 6px -1px rgb(0 0 0 / 0.5);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background-color: var(--bg);
  color: var(--text);
  line-height: 1.5;
  transition: background-color 0.2s, color 0.2s;
  padding: 0 1rem 3rem;
}}
header {{
  max-width: 1200px;
  margin: 2rem auto 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}}
.top-bar {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}}
.brand {{
  display: flex;
  align-items: center;
  gap: 0.75rem;
}}
.brand h1 {{
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}}
.theme-btn {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 0.5rem 1rem;
  border-radius: 9999px;
  cursor: pointer;
  font-weight: 500;
  font-size: 0.875rem;
}}
.search-controls {{
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}}
.search-box {{
  width: 100%;
  padding: 0.85rem 1.25rem;
  font-size: 1rem;
  border-radius: 0.75rem;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text);
  outline: none;
}}
.search-box:focus {{
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
}}
.tags-filter {{
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}}
.tag-btn {{
  background: var(--badge-bg);
  border: 1px solid var(--border);
  color: var(--badge-text);
  padding: 0.35rem 0.75rem;
  border-radius: 0.5rem;
  cursor: pointer;
  font-size: 0.85rem;
  text-transform: capitalize;
}}
.tag-btn.active {{
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}}
.stats-bar {{
  font-size: 0.875rem;
  color: var(--text-muted);
  margin-top: 0.25rem;
}}
main {{
  max-width: 1200px;
  margin: 0 auto;
}}
.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 1.5rem;
}}
.card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 1rem;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  box-shadow: var(--shadow);
}}
.card-header {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.5rem;
}}
.card-title {{
  font-size: 1.25rem;
  font-weight: 600;
}}
.badge-kind {{
  font-size: 0.75rem;
  padding: 0.2rem 0.6rem;
  border-radius: 9999px;
  background: var(--badge-bg);
  color: var(--badge-text);
  text-transform: uppercase;
  font-weight: 600;
}}
.card-desc {{
  color: var(--text-muted);
  font-size: 0.925rem;
  flex-grow: 1;
}}
.card-badges {{
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}}
.badge {{
  font-size: 0.75rem;
  padding: 0.2rem 0.5rem;
  border-radius: 0.375rem;
  background: var(--badge-bg);
  color: var(--badge-text);
}}
.dialects {{
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
  align-items: center;
}}
.dialect-pill {{
  font-size: 0.7rem;
  padding: 0.15rem 0.45rem;
  border-radius: 9999px;
  background: var(--pill-bg);
  color: var(--pill-text);
  font-weight: 500;
}}
.card-actions {{
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: 0.25rem;
}}
.btn {{
  padding: 0.45rem 0.85rem;
  font-size: 0.8rem;
  font-weight: 500;
  border-radius: 0.5rem;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  cursor: pointer;
  transition: all 0.15s;
}}
.btn:hover {{
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}}
details {{
  border-top: 1px solid var(--border);
  padding-top: 0.75rem;
  margin-top: 0.25rem;
}}
summary {{
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--primary);
  font-weight: 500;
  user-select: none;
}}
pre {{
  background: var(--code-bg);
  color: var(--code-text);
  padding: 0.75rem;
  border-radius: 0.5rem;
  font-size: 0.775rem;
  overflow-x: auto;
  margin-top: 0.5rem;
  white-space: pre-wrap;
  word-break: break-all;
}}
.empty-state {{
  text-align: center;
  padding: 4rem 1rem;
  color: var(--text-muted);
  font-size: 1.1rem;
  grid-column: 1 / -1;
}}
</style>
</head>
<body>
<header>
  <div class="top-bar">
    <div class="brand">
      <h1>⚡ {html.escape(project_name)}</h1>
    </div>
    <button id="theme-toggle" class="theme-btn" aria-label="Toggle theme">🌓 Theme</button>
  </div>
  <div class="search-controls">
    <input type="text" id="search" class="search-box"
      placeholder="Instant fuzzy search across titles, descriptions, and prompt bodies..."
      autocomplete="off">
    <div class="tags-filter" id="tags-filter">
      <button class="tag-btn active" data-tag="all">All</button>
      {tag_buttons}
    </div>
    <div class="stats-bar" id="stats-bar">
      Showing {len(cards_data)} of {len(cards_data)} skills
    </div>
  </div>
</header>
<main>
  <div class="grid" id="cards-grid"></div>
</main>

<script id="skills-data" type="application/json">
{json_payload}
</script>

<script>
(function() {{
  const skills = JSON.parse(document.getElementById('skills-data').textContent);
  const grid = document.getElementById('cards-grid');
  const searchInput = document.getElementById('search');
  const statsBar = document.getElementById('stats-bar');
  const tagsContainer = document.getElementById('tags-filter');
  const themeToggle = document.getElementById('theme-toggle');

  let activeTag = 'all';

  // Theme support
  const savedTheme = localStorage.getItem('cinch-theme');
  if (savedTheme) {{
    document.documentElement.setAttribute('data-theme', savedTheme);
  }} else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {{
    document.documentElement.setAttribute('data-theme', 'dark');
  }}

  themeToggle.addEventListener('click', () => {{
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('cinch-theme', next);
  }});

  function copyText(btn, text) {{
    navigator.clipboard.writeText(text).then(() => {{
      const original = btn.textContent;
      btn.textContent = '✓ Copied!';
      setTimeout(() => btn.textContent = original, 1400);
    }}).catch(() => {{
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      const original = btn.textContent;
      btn.textContent = '✓ Copied!';
      setTimeout(() => btn.textContent = original, 1400);
    }});
  }}

  function escapeHtml(str) {{
    return (str || '').replace(/[&<>"']/g, m => ({{
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }})[m]);
  }}

  function renderCards(filtered) {{
    grid.innerHTML = '';
    if (filtered.length === 0) {{
      grid.innerHTML =
        '<div class="empty-state">No matching skills found. Try another search query.</div>';
      statsBar.textContent = `Showing 0 of ${{skills.length}} skills`;
      return;
    }}

    statsBar.textContent = `Showing ${{filtered.length}} of ${{skills.length}} skills`;

    filtered.forEach(skill => {{
      const card = document.createElement('div');
      card.className = 'card';

      const tagBadges = (skill.tags || []).map(t =>
        `<span class="badge">#${{escapeHtml(t)}}</span>`
      ).join('');

      const dialectPills = (skill.dialects || []).slice(0, 6).map(d =>
        `<span class="dialect-pill">${{escapeHtml(d)}}</span>`
      ).join('');

      const descText = escapeHtml(skill.description || 'No description provided.');
      card.innerHTML = `
        <div class="card-header">
          <div class="card-title">${{escapeHtml(skill.name)}}</div>
          <span class="badge-kind">${{escapeHtml(skill.kind)}}</span>
        </div>
        <div class="card-desc">${{descText}}</div>
        ${{tagBadges ? `<div class="card-badges">${{tagBadges}}</div>` : ''}}
        <div class="dialects">
          <span style="font-size:0.75rem; color:var(--text-muted);">Dialects:</span>
          ${{dialectPills}}
        </div>
        <div class="card-actions">
          <button class="btn btn-copy-prompt">Copy Prompt</button>
          <button class="btn btn-copy-claude">Copy for Claude</button>
          <button class="btn btn-copy-cursor">Copy for Cursor</button>
        </div>
        <details>
          <summary>View Prompt Body</summary>
          <pre><code>${{escapeHtml(skill.body)}}</code></pre>
        </details>
      `;

      card.querySelector('.btn-copy-prompt').addEventListener('click', e => {{
        copyText(e.target, skill.body);
      }});
      card.querySelector('.btn-copy-claude').addEventListener('click', e => {{
        copyText(e.target, skill.claude || skill.canonical);
      }});
      card.querySelector('.btn-copy-cursor').addEventListener('click', e => {{
        copyText(e.target, skill.cursor || skill.canonical);
      }});

      grid.appendChild(card);
    }});
  }}

  function filterSkills() {{
    const q = (searchInput.value || '').trim().toLowerCase();
    const filtered = skills.filter(item => {{
      const matchesTag = activeTag === 'all' || (item.tags || []).includes(activeTag);
      if (!matchesTag) return false;
      if (!q) return true;

      const inName = (item.name || '').toLowerCase().includes(q);
      const inDesc = (item.description || '').toLowerCase().includes(q);
      const inBody = (item.body || '').toLowerCase().includes(q);
      const inTags = (item.tags || []).some(t => t.toLowerCase().includes(q));
      return inName || inDesc || inBody || inTags;
    }});
    renderCards(filtered);
  }}

  searchInput.addEventListener('input', filterSkills);

  tagsContainer.addEventListener('click', e => {{
    if (!e.target.classList.contains('tag-btn')) return;
    document.querySelectorAll('.tag-btn').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    activeTag = e.target.getAttribute('data-tag');
    filterSkills();
  }});

  // Initial render
  renderCards(skills);
}})();
</script>
</body>
</html>
"""


def export_html_catalog(
    project_root: Path | str = ".",
    output_path: Path | str | None = None,
    include_starter: bool = True,
    title: str = "Cinch Skills Catalog",
) -> str:
    """Discover skills, generate standalone HTML, and optionally write to output file."""
    skills = discover_skills(project_root=project_root, include_starter=include_starter)
    html_content = generate_html_catalog(skills, project_name=title)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html_content, encoding="utf-8")

    return html_content
