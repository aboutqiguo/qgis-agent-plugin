"""Zero-dependency GitHub Flavored Markdown (GFM) renderer for QGIS QTextBrowser.

Provides robust HTML rendering for tables, checklists, code blocks,
blockquotes, headers, bold/italic, and inline code without requiring
external third-party markdown packages.
"""

from __future__ import annotations

import html
import re
from typing import Dict, List, Optional


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return "|" in s and not s.startswith("```")


def _is_table_separator(line: str) -> bool:
    s = line.strip().strip("|")
    parts = [p.strip() for p in s.split("|")]
    return len(parts) >= 1 and all(bool(re.match(r"^:?-+:?$", p)) for p in parts if p)


def _format_inlines(text: str, colors: Optional[Dict[str, str]] = None) -> str:
    """Format inline markdown elements: bold, italic, code, links.

    Protects inline code spans and intra-word underscores (e.g., ask_human,
    shijian_mask.png, shijiao_2019101) so snake_case identifiers are never
    mangled into italics.
    """
    colors = colors or {}
    c_code_bg = colors.get("code_bg", "#f6f8fa")
    c_code_text = colors.get("code_text", "#24292f")
    c_border = colors.get("border", "#d0d7de")
    c_link = colors.get("link", "#0969da")

    code_spans: List[str] = []

    def _code_repl(m):
        code_txt = html.escape(m.group(1))
        rendered = (
            f'<code style="font-family: Consolas, monospace; font-size: 11px; '
            f'background-color: {c_code_bg}; color: {c_code_text}; '
            f'border: 1px solid {c_border}; border-radius: 3px; padding: 1px 4px;">{code_txt}</code>'
        )
        token = f"\x00INLINECODE{len(code_spans)}\x00"
        code_spans.append(rendered)
        return token

    text = re.sub(r"`([^`]+)`", _code_repl, text)

    # Bold: **bold** or GFM word-bounded __bold__
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(
        r"(?<![0-9A-Za-z_])__([^\s_](?:[^_]*[^\s_])?)__(?![0-9A-Za-z_])",
        r"<b>\1</b>",
        text,
    )

    # Italic: *italic* or GFM word-bounded _italic_ (never matches snake_case_identifiers)
    text = re.sub(r"(?<!\*)\*([^\s*](?:[^*]*[^\s*])?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(
        r"(?<![0-9A-Za-z_])_([^\s_](?:[^_]*[^\s_])?)_(?![0-9A-Za-z_])",
        r"<i>\1</i>",
        text,
    )

    # Links: [title](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        rf'<a href="\2" style="color: {c_link}; text-decoration: underline;">\1</a>',
        text,
    )

    for idx, rendered in enumerate(code_spans):
        text = text.replace(f"\x00INLINECODE{idx}\x00", rendered)

    return text


def _render_table(table_lines: List[str], colors: Optional[Dict[str, str]] = None) -> str:
    """Parse table lines and generate a clean, responsive HTML table."""
    if len(table_lines) < 2:
        return "<br>".join(table_lines)

    colors = colors or {}
    c_border = colors.get("border", "#d0d7de")
    c_header = colors.get("table_header", "#f6f8fa")
    c_text = colors.get("text", "#1f2328")
    c_alt = colors.get("table_alt", colors.get("pill_bg", "#fcfdfe"))

    header_cells = [c.strip() for c in table_lines[0].strip().strip("|").split("|")]
    data_rows = []
    for line in table_lines[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        data_rows.append(cells)

    html_parts = [
        f'<table style="border-collapse: collapse; width: 100%; margin: 8px 0; border: 1px solid {c_border}; font-size: 11.5px; border-radius: 6px; overflow: hidden;">',
        "<thead>",
        f'<tr style="background-color: {c_header}; border-bottom: 2px solid {c_border};">',
    ]

    for cell in header_cells:
        formatted = _format_inlines(cell, colors)
        html_parts.append(
            f'<th style="border: 1px solid {c_border}; padding: 6px 10px; font-weight: 600; text-align: left; color: {c_text}; white-space: nowrap;">{formatted}</th>'
        )
    html_parts.append("</tr></thead><tbody>")

    for idx, row in enumerate(data_rows):
        bg = c_alt if idx % 2 == 1 else "transparent"
        html_parts.append(f'<tr style="background-color: {bg}; border-bottom: 1px solid {c_border};">')
        for c_idx in range(len(header_cells)):
            cell_val = row[c_idx] if c_idx < len(row) else ""
            formatted = _format_inlines(cell_val, colors)
            html_parts.append(
                f'<td style="border: 1px solid {c_border}; padding: 5px 10px; vertical-align: top; color: {c_text};">{formatted}</td>'
            )
        html_parts.append("</tr>")

    html_parts.append("</tbody></table>")
    return "".join(html_parts)


def render_markdown_to_html(content: str, colors: Optional[Dict[str, str]] = None) -> str:
    """Convert markdown text to clean, styled HTML suitable for Qt QTextBrowser."""
    if not content:
        return ""

    colors = colors or {}
    c_text = colors.get("text", "#1f2328")
    c_border = colors.get("border", "#d0d7de")
    c_code_bg = colors.get("code_bg", "#f6f8fa")
    c_code_text = colors.get("code_text", "#24292f")
    c_quote_border = colors.get("quote_border", "#0969da")
    c_quote_text = colors.get("quote_text", "#57609a")

    # Pre-process checklists
    text = content.replace("\r\n", "\n")
    text = re.sub(
        r"^([ \t]*)[-*]\s+\[ \]\s+",
        r'\1<span style="font-size: 13px; color: #8c959f;">☐ </span>',
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^([ \t]*)[-*]\s+\[[xX]\]\s+",
        r'\1<span style="font-size: 13px; color: #2ea043; font-weight: bold;">☑ </span>',
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^([ \t]*)[-*]\s+\[/\]\s+",
        r'\1<span style="font-size: 13px; color: #0969da; font-weight: bold;">🔄 </span>',
        text,
        flags=re.MULTILINE,
    )

    lines = text.split("\n")
    out: List[str] = []
    i = 0
    n = len(lines)

    in_code_block = False
    in_pre_block = False
    code_block_lines: List[str] = []
    code_lang = ""

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Pass through pre-formatted HTML blocks (e.g., <div ...><b>🧠 思考过程:</b><br/><pre>...</pre></div>)
        if not in_code_block and ("<pre" in line or in_pre_block):
            out.append(line)
            if "<pre" in line and "</pre>" not in line:
                in_pre_block = True
            elif "</pre>" in line:
                in_pre_block = False
            i += 1
            continue

        # 1. Code blocks
        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = stripped.lstrip("`").strip()
                code_block_lines = []
                i += 1
                continue
            else:
                in_code_block = False
                escaped_code = html.escape("\n".join(code_block_lines))
                lang_tag = (
                    f"<div style='font-size: 10px; color: #8c959f; text-transform: uppercase; margin-bottom: 4px;'>{html.escape(code_lang)}</div>"
                    if code_lang
                    else ""
                )
                out.append(
                    f"<div style='margin: 8px 0; background-color: {c_code_bg}; border: 1px solid {c_border}; border-radius: 6px; padding: 8px 10px;'>"
                    f"{lang_tag}<pre style='margin: 0; font-family: Consolas, \"Courier New\", monospace; font-size: 11.5px; color: {c_code_text}; white-space: pre-wrap; word-break: break-all;'><code>{escaped_code}</code></pre></div>"
                )
                i += 1
                continue

        if in_code_block:
            code_block_lines.append(line)
            i += 1
            continue

        # 2. Markdown tables
        if _is_table_row(stripped) and i + 1 < n and _is_table_separator(lines[i + 1]):
            table_lines = [stripped, lines[i + 1].strip()]
            i += 2
            while i < n and _is_table_row(lines[i]):
                table_lines.append(lines[i].strip())
                i += 1
            out.append(_render_table(table_lines, colors))
            continue

        # 3. Headers
        header_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if header_match:
            level = len(header_match.group(1))
            h_text = _format_inlines(header_match.group(2), colors)
            font_size = {1: "16px", 2: "14.5px", 3: "13.5px", 4: "12.5px", 5: "12px", 6: "11.5px"}.get(level, "13px")
            out.append(f"<h{level} style='font-size: {font_size}; font-weight: 700; margin: 10px 0 6px 0; color: {c_text};'>{h_text}</h{level}>")
            i += 1
            continue

        # 4. Blockquotes
        if stripped.startswith(">"):
            quote_text = stripped.lstrip(">").strip()
            formatted_quote = _format_inlines(quote_text, colors)
            out.append(
                f"<blockquote style='margin: 6px 0; padding: 4px 10px; border-left: 3px solid {c_quote_border}; background-color: {c_code_bg}; color: {c_quote_text}; font-size: 12px; border-radius: 0 4px 4px 0;'>"
                f"{formatted_quote}</blockquote>"
            )
            i += 1
            continue

        # 5. Horizontal rule
        if re.match(r"^(\*{3,}|-{3,}|_{3,})$", stripped):
            out.append(f"<hr style='border: none; border-top: 1px solid {c_border}; margin: 10px 0;' />")
            i += 1
            continue

        # 6. Regular paragraph or list item
        if stripped:
            formatted_line = _format_inlines(line, colors)
            if stripped.startswith(("- ", "* ", "+ ")):
                content_item = _format_inlines(stripped[2:], colors)
                out.append(f"<div style='margin: 2px 0 2px 14px;'>• {content_item}</div>")
            elif re.match(r"^\d+\.\s+", stripped):
                m = re.match(r"^(\d+\.)\s+(.+)$", stripped)
                num = m.group(1)
                content_item = _format_inlines(m.group(2), colors)
                out.append(f"<div style='margin: 2px 0 2px 14px;'><b>{num}</b> {content_item}</div>")
            else:
                out.append(f"<div style='margin: 2px 0;'>{formatted_line}</div>")
        else:
            out.append("<div style='height: 6px;'></div>")

        i += 1

    return "\n".join(out)
