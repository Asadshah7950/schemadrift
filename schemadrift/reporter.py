"""Reporting and export utilities for schemadrift diff results."""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from schemadrift.models import DiffResult


def render_json_report(diff_result: DiffResult) -> str:
    """Serialize the diff result to a formatted JSON string."""
    data = {
        "has_drift": diff_result.has_drift,
        "has_destructive_changes": diff_result.has_destructive_changes,
        "destructive_changes_count": diff_result.destructive_changes_count,
        "tables_added": [t.name for t in diff_result.tables_added],
        "tables_dropped": list(diff_result.tables_dropped),
        "columns_added": [
            {"table": t, "column": c.name, "type": c.data_type}
            for t, c in diff_result.columns_added
        ],
        "columns_dropped": [
            {"table": t, "column": c} for t, c in diff_result.columns_dropped
        ],
        "columns_altered": [
            {
                "table": t,
                "column": s.name,
                "from_type": s.data_type,
                "to_type": g.data_type,
            }
            for t, s, g in diff_result.columns_altered
        ],
        "indexes_added": [i.name for i in diff_result.indexes_added],
        "indexes_dropped": [i.name for i in diff_result.indexes_dropped],
        "fks_added": [fk.name for fk in diff_result.fks_added],
        "fks_dropped": [fk.name for fk in diff_result.fks_dropped],
        "enums_added": [
            {"name": name, "labels": labels}
            for name, labels in diff_result.enums_added
        ],
        "enums_altered": [
            {"name": name, "added_labels": added}
            for name, _, added in diff_result.enums_altered
        ],
    }
    return json.dumps(data, indent=2)


def render_summary_report(diff_result: DiffResult) -> str:
    """Return a human-readable plain-text summary of the diff."""
    lines = ["Schema Diff Summary", "=" * 40]
    lines.append(f"Tables added:    {len(diff_result.tables_added)}")
    lines.append(f"Tables dropped:  {len(diff_result.tables_dropped)}")
    lines.append(f"Columns added:   {len(diff_result.columns_added)}")
    lines.append(f"Columns dropped: {len(diff_result.columns_dropped)}")
    lines.append(f"Columns altered: {len(diff_result.columns_altered)}")
    lines.append(f"Indexes added:   {len(diff_result.indexes_added)}")
    lines.append(f"Indexes dropped: {len(diff_result.indexes_dropped)}")
    lines.append(f"FKs added:       {len(diff_result.fks_added)}")
    lines.append(f"FKs dropped:     {len(diff_result.fks_dropped)}")
    if diff_result.enums_added or diff_result.enums_altered:
        lines.append(f"Enums added:     {len(diff_result.enums_added)}")
        lines.append(f"Enums altered:   {len(diff_result.enums_altered)}")
    if diff_result.has_destructive_changes:
        lines.append(f"Destructive:     {diff_result.destructive_changes_count} drops")
    return "\n".join(lines)


def _md_row(label: str, badge: str, items: list[str]) -> str:
    details = ", ".join(items)
    return f"| **{label}** | {badge} | `{len(items)}` | {details} |"


def render_markdown_report(diff_result: DiffResult) -> str:
    """Serialize the diff result to a GitHub-flavored Markdown report."""
    if not diff_result.has_drift:
        return (
            "### 🟢 Schema Diff: No Changes Detected\n\nDatabase schemas are in sync."
        )

    lines = [
        "### 🔍 PostgreSQL Schema Drift Report\n",
        "| Component | Status | Count | Details |",
        "| :--- | :--- | :---: | :--- |",
    ]
    if diff_result.tables_added:
        items = [f"`{t.name}`" for t in diff_result.tables_added]
        lines.append(_md_row("Tables Added", "🟢 Added", items))
    if diff_result.tables_dropped:
        items = [f"`{t}`" for t in diff_result.tables_dropped]
        lines.append(_md_row("Tables Dropped", "🔴 Dropped", items))
    if diff_result.columns_added:
        items = [f"`{t}.{c.name}`" for t, c in diff_result.columns_added]
        lines.append(_md_row("Columns Added", "🟢 Added", items))
    if diff_result.columns_dropped:
        items = [f"`{t}.{c}`" for t, c in diff_result.columns_dropped]
        lines.append(_md_row("Columns Dropped", "🔴 Dropped", items))
    if diff_result.columns_altered:
        items = [f"`{t}.{s.name}`" for t, s, _ in diff_result.columns_altered]
        lines.append(_md_row("Columns Altered", "🟡 Altered", items))
    if diff_result.indexes_added:
        items = [f"`{i.name}`" for i in diff_result.indexes_added]
        lines.append(_md_row("Indexes Added", "🟢 Added", items))
    if diff_result.indexes_dropped:
        items = [f"`{i.name}`" for i in diff_result.indexes_dropped]
        lines.append(_md_row("Indexes Dropped", "🔴 Dropped", items))
    if diff_result.fks_added:
        items = [f"`{fk.name}`" for fk in diff_result.fks_added]
        lines.append(_md_row("Foreign Keys Added", "🟢 Added", items))
    if diff_result.fks_dropped:
        items = [f"`{fk.name}`" for fk in diff_result.fks_dropped]
        lines.append(_md_row("Foreign Keys Dropped", "🔴 Dropped", items))
    if diff_result.enums_added:
        items = [f"`{name}`" for name, _ in diff_result.enums_added]
        lines.append(_md_row("Enums Added", "🟢 Added", items))
    if diff_result.enums_altered:
        items = [f"`{name}`" for name, _, _ in diff_result.enums_altered]
        lines.append(_md_row("Enums Altered", "🟡 Altered", items))

    return "\n".join(lines)


def render_html_report(
    diff_result: DiffResult,
    sql: str | None = None,
    title: str = "PostgreSQL Schema Drift Report",
) -> str:
    """Generate a self-contained, responsive dark-mode HTML drift audit report."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    status_badge = (
        '<span class="badge badge-warning">DRIFT DETECTED</span>'
        if diff_result.has_drift
        else '<span class="badge badge-success">IN SYNC</span>'
    )

    t_add = len(diff_result.tables_added)
    t_drop = len(diff_result.tables_dropped)
    c_add = len(diff_result.columns_added)
    c_drop = len(diff_result.columns_dropped)
    c_alt = len(diff_result.columns_altered)
    i_add = len(diff_result.indexes_added)
    i_drop = len(diff_result.indexes_dropped)
    fk_add = len(diff_result.fks_added)
    fk_drop = len(diff_result.fks_dropped)

    cards_html = f"""
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-label">Tables</div>
        <div class="metric-value">{t_add + t_drop}</div>
        <div class="metric-sub">
          <span class="txt-add">+{t_add}</span> / <span class="txt-drop">-{t_drop}</span>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Columns</div>
        <div class="metric-value">{c_add + c_drop + c_alt}</div>
        <div class="metric-sub">
          <span class="txt-add">+{c_add}</span> /
          <span class="txt-drop">-{c_drop}</span> /
          <span class="txt-alt">~{c_alt}</span>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Indexes</div>
        <div class="metric-value">{i_add + i_drop}</div>
        <div class="metric-sub">
          <span class="txt-add">+{i_add}</span> / <span class="txt-drop">-{i_drop}</span>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Foreign Keys</div>
        <div class="metric-value">{fk_add + fk_drop}</div>
        <div class="metric-sub">
          <span class="txt-add">+{fk_add}</span> / <span class="txt-drop">-{fk_drop}</span>
        </div>
      </div>
    </div>
    """

    sections: list[str] = []

    if diff_result.tables_added:
        items = "".join(
            f"<li><code>{html.escape(t.name)}</code></li>"
            for t in diff_result.tables_added
        )
        sections.append(
            '<div class="diff-block">'
            f'<h3><span class="pill pill-add">Added</span> Tables ({t_add})</h3>'
            f'<ul>{items}</ul></div>'
        )

    if diff_result.tables_dropped:
        items = "".join(
            f"<li><code>{html.escape(t)}</code></li>"
            for t in diff_result.tables_dropped
        )
        sections.append(
            '<div class="diff-block">'
            f'<h3><span class="pill pill-drop">Dropped</span> Tables ({t_drop})</h3>'
            f'<ul>{items}</ul></div>'
        )

    if diff_result.columns_added:
        items = "".join(
            f"<li><code>{html.escape(t)}.{html.escape(c.name)}</code> &mdash; "
            f'<span class="type-tag">{html.escape(c.data_type)}</span></li>'
            for t, c in diff_result.columns_added
        )
        sections.append(
            '<div class="diff-block">'
            f'<h3><span class="pill pill-add">Added</span> Columns ({c_add})</h3>'
            f'<ul>{items}</ul></div>'
        )

    if diff_result.columns_dropped:
        items = "".join(
            f"<li><code>{html.escape(t)}.{html.escape(c)}</code></li>"
            for t, c in diff_result.columns_dropped
        )
        sections.append(
            '<div class="diff-block">'
            f'<h3><span class="pill pill-drop">Dropped</span> Columns ({c_drop})</h3>'
            f'<ul>{items}</ul></div>'
        )

    if diff_result.columns_altered:
        items = "".join(
            f"<li><code>{html.escape(t)}.{html.escape(s.name)}</code> &mdash; "
            f"{html.escape(s.data_type)} &rarr; "
            f"<strong>{html.escape(g.data_type)}</strong></li>"
            for t, s, g in diff_result.columns_altered
        )
        sections.append(
            '<div class="diff-block">'
            f'<h3><span class="pill pill-alt">Altered</span> Columns ({c_alt})</h3>'
            f'<ul>{items}</ul></div>'
        )

    if diff_result.indexes_added:
        items = "".join(
            f"<li><code>{html.escape(i.name)}</code> on "
            f"table <code>{html.escape(i.table)}</code></li>"
            for i in diff_result.indexes_added
        )
        sections.append(
            '<div class="diff-block">'
            f'<h3><span class="pill pill-add">Added</span> Indexes ({i_add})</h3>'
            f'<ul>{items}</ul></div>'
        )

    if diff_result.indexes_dropped:
        items = "".join(
            f"<li><code>{html.escape(i.name)}</code> on "
            f"table <code>{html.escape(i.table)}</code></li>"
            for i in diff_result.indexes_dropped
        )
        sections.append(
            '<div class="diff-block">'
            f'<h3><span class="pill pill-drop">Dropped</span> Indexes ({i_drop})</h3>'
            f'<ul>{items}</ul></div>'
        )

    if diff_result.fks_added:
        items = "".join(
            f"<li><code>{html.escape(fk.name)}</code> "
            f"({html.escape(fk.table)} &rarr; {html.escape(fk.ref_table)})</li>"
            for fk in diff_result.fks_added
        )
        sections.append(
            '<div class="diff-block">'
            f'<h3><span class="pill pill-add">Added</span> Foreign Keys ({fk_add})</h3>'
            f'<ul>{items}</ul></div>'
        )

    if diff_result.fks_dropped:
        items = "".join(
            f"<li><code>{html.escape(fk.name)}</code></li>"
            for fk in diff_result.fks_dropped
        )
        sections.append(
            '<div class="diff-block">'
            f'<h3><span class="pill pill-drop">Dropped</span> Foreign Keys ({fk_drop})</h3>'
            f'<ul>{items}</ul></div>'
        )

    details_content = (
        "".join(sections)
        if sections
        else '<p class="in-sync-msg">Schemas are in parity. No drift detected.</p>'
    )

    sql_block = ""
    if sql:
        escaped_sql = html.escape(sql)
        sql_block = f"""
        <div class="sql-section">
          <div class="sql-header">
            <h3>Generated Migration SQL</h3>
            <button class="btn-copy" onclick="copySql()">Copy SQL</button>
          </div>
          <pre><code id="sqlCode">{escaped_sql}</code></pre>
        </div>
        """

    footer_link = (
        '<a href="https://github.com/Asadshah7950/schemadrift"'
        ' target="_blank" rel="noopener">schemadrift</a>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #0d1117;
      --card-bg: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --text-muted: #8b949e;
      --heading: #f0f6fc;
      --green: #238636;
      --green-text: #3fb950;
      --red: #da3633;
      --red-text: #f85149;
      --amber: #d29922;
      --blue: #58a6ff;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      padding: 32px 16px;
      line-height: 1.5;
    }}
    .container {{ max-width: 960px; margin: 0 auto; }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
      margin-bottom: 24px;
      flex-wrap: wrap;
      gap: 12px;
    }}
    h1 {{ font-size: 1.5rem; color: var(--heading); }}
    .timestamp {{ font-size: 0.85rem; color: var(--text-muted); }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.5px;
    }}
    .badge-warning {{
      background: rgba(210, 153, 34, 0.15);
      color: var(--amber);
      border: 1px solid var(--amber);
    }}
    .badge-success {{
      background: rgba(63, 185, 80, 0.15);
      color: var(--green-text);
      border: 1px solid var(--green-text);
    }}
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }}
    .metric-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      text-align: center;
    }}
    .metric-label {{
      font-size: 0.85rem;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 600;
    }}
    .metric-value {{ font-size: 2rem; font-weight: 700; color: var(--heading); margin: 4px 0; }}
    .metric-sub {{ font-size: 0.85rem; font-weight: 600; }}
    .txt-add {{ color: var(--green-text); }}
    .txt-drop {{ color: var(--red-text); }}
    .txt-alt {{ color: var(--amber); }}
    .diff-block {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 16px;
    }}
    .diff-block h3 {{
      font-size: 1rem;
      color: var(--heading);
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .diff-block ul {{ list-style: none; }}
    .diff-block li {{
      padding: 6px 0;
      border-bottom: 1px solid rgba(48, 54, 61, 0.4);
      font-size: 0.9rem;
    }}
    .diff-block li:last-child {{ border-bottom: none; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: rgba(110, 118, 129, 0.2);
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.85em;
    }}
    .type-tag {{ color: var(--blue); font-size: 0.85rem; }}
    .pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .pill-add {{ background: rgba(63, 185, 80, 0.2); color: var(--green-text); }}
    .pill-drop {{ background: rgba(248, 81, 73, 0.2); color: var(--red-text); }}
    .pill-alt {{ background: rgba(210, 153, 34, 0.2); color: var(--amber); }}
    .in-sync-msg {{
      text-align: center;
      padding: 32px;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--green-text);
      font-weight: 600;
    }}
    .sql-section {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-top: 24px;
      overflow: hidden;
    }}
    .sql-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
    }}
    .sql-header h3 {{ font-size: 0.95rem; color: var(--heading); }}
    .btn-copy {{
      background: #21262d;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 0.8rem;
      cursor: pointer;
      font-weight: 600;
      transition: background 0.2s;
    }}
    .btn-copy:hover {{ background: #30363d; }}
    pre {{
      padding: 16px;
      overflow-x: auto;
      font-size: 0.85rem;
      line-height: 1.45;
      color: #e6edf3;
    }}
    footer {{
      margin-top: 36px;
      text-align: center;
      font-size: 0.8rem;
      color: var(--text-muted);
      border-top: 1px solid var(--border);
      padding-top: 16px;
    }}
    footer a {{ color: var(--blue); text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>schemadrift &bull; Audit Report</h1>
        <div class="timestamp">Generated on {now_utc}</div>
      </div>
      <div>
        {status_badge}
      </div>
    </header>

    {cards_html}

    <div class="diff-details">
      {details_content}
    </div>

    {sql_block}

    <footer>
      Generated with {footer_link} &mdash; PostgreSQL Schema Drift Detection
    </footer>
  </div>

  <script>
    function copySql() {{
      const text = document.getElementById('sqlCode').innerText;
      navigator.clipboard.writeText(text).then(() => {{
        const btn = document.querySelector('.btn-copy');
        const orig = btn.innerText;
        btn.innerText = 'Copied!';
        btn.style.color = '#3fb950';
        setTimeout(() => {{
          btn.innerText = orig;
          btn.style.color = '';
        }}, 2000);
      }});
    }}
  </script>
</body>
</html>
"""


def write_github_step_summary(markdown_content: str) -> bool:
    """Append a markdown report to the GitHub Step Summary file if in GitHub Actions."""
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return False
    try:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n{markdown_content}\n")
        return True
    except Exception:
        return False
