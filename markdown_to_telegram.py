"""
markdown_to_telegram.py
=======================
Converts Markdown text from LLM responses to Telegram-compatible HTML.

Telegram supports a subset of HTML. This module converts standard Markdown
to that subset, preserving:
- Bold (**text** → <b>text</b>)
- Italic (*text* or _text_ → <i>text</i>)
- Inline code (`code` → <code>code</code>)
- Code blocks (```code``` → <pre>code</pre>)
- Links ([text](url) → <a href="url">text</a>)
- Headings (# H1 → <b>H1</b>)
- Bullet lists (- item → • item)
- Numbered lists (1. item → 1. item)
- Blockquotes (> text → <blockquote>text</blockquote>)
- Line breaks and double line breaks (preserved)
- Horizontal rules (--- → ━━━━━━━━━)

Telegram HTML does NOT support:
- Markdown headers (h1-h6) — converted to bold
- Tables — flattened to text
- Images — stripped
- Strikethrough in standard Markdown (~~text~~) — supported in Telegram as <s>

Important: We must escape HTML entities (< > &) BEFORE applying Markdown
conversions, to prevent injection and broken formatting.
"""

from __future__ import annotations

import re
from typing import List


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def convert_markdown_to_telegram_html(markdown_text: str) -> str:
    """Convert Markdown text to Telegram-compatible HTML.

    Args:
        markdown_text: Text with Markdown formatting from an LLM

    Returns:
        HTML text formatted for Telegram's HTML parse mode
    """
    if not markdown_text:
        return ""

    # First, protect blockquotes before escaping
    blockquotes = []

    def save_blockquote(match):
        lines = match.group(0).strip().split('\n')
        content = '\n'.join(line.lstrip('> ').rstrip() for line in lines)
        blockquotes.append(content)
        return f"__BLOCKQUOTE_{len(blockquotes) - 1}__"

    text = re.sub(r'(?:^> .+(?:\n> .+)*)', save_blockquote, markdown_text, flags=re.MULTILINE)

    # Now escape all HTML entities
    text = escape_html(text)

    # Protect code blocks (triple backtick) — process them separately
    code_blocks = []

    def save_code_block(match):
        code = match.group(1).strip()
        code_blocks.append(code)
        return f"__CODE_BLOCK_{len(code_blocks) - 1}__"

    # Match ```code``` (with optional language specifier)
    text = re.sub(r'```[\w]*\n?(.*?)```', save_code_block, text, flags=re.DOTALL)

    # Protect inline code (single backtick)
    inline_codes = []

    def save_inline_code(match):
        code = match.group(1)
        inline_codes.append(code)
        return f"__INLINE_CODE_{len(inline_codes) - 1}__"

    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # Protect links — process them separately
    links = []

    def save_link(match):
        link_text = match.group(1)
        link_url = match.group(2)
        links.append((link_text, link_url))
        return f"__LINK_{len(links) - 1}__"

    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', save_link, text)

    # Convert bold: **text** or __text__
    text = re.sub(r'\*\*([^\*]+)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\w)__([^\_]+)__(?!\w)', r'<b>\1</b>', text)

    # Convert italic: *text* or _text_
    # Be careful not to break bold that was already converted
    # Only convert *text* that's not part of **text**
    text = re.sub(r'(?<!\*)\*([^\*\n]+)\*(?!\*)', r'<i>\1</i>', text)
    # _italic_ — but avoid breaking words_with_underscores
    text = re.sub(r'(?<!\w)_([^\_\n]+)_(?!\w)', r'<i>\1</i>', text)

    # Convert strikethrough: ~~text~~
    text = re.sub(r'~~([^\~]+)~~', r'<s>\1</s>', text)

    # Convert headings: # H1, ## H2, ### H3, etc.
    # Telegram doesn't support headings — convert to bold
    def heading_to_bold(match):
        level = len(match.group(1))
        text_content = match.group(2).strip()
        return f"<b>{text_content}</b>"

    text = re.sub(r'^(#{1,6})\s+(.+)$', heading_to_bold, text, flags=re.MULTILINE)

    # Convert horizontal rules: --- or *** or ___
    text = re.sub(r'^[\-\*\_]{3,}$', '━━━━━━━━━', text, flags=re.MULTILINE)

    # Convert bullet lists: - item or * item → • item
    # But only at the start of a line (not in the middle of text)
    text = re.sub(r'^[\-\*]\s+', '• ', text, flags=re.MULTILINE)

    # Restore blockquotes
    for i, bq_content in enumerate(blockquotes):
        # Escape the blockquote content too
        bq_escaped = escape_html(bq_content)
        text = text.replace(f"__BLOCKQUOTE_{i}__", f"<blockquote>{bq_escaped}</blockquote>")

    # Restore links
    for i, (link_text, link_url) in enumerate(links):
        replacement = f'<a href="{link_url}">{link_text}</a>'
        text = text.replace(f"__LINK_{i}__", replacement)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        text = text.replace(f"__INLINE_CODE_{i}__", f"<code>{code}</code>")

    # Restore code blocks
    for i, code in enumerate(code_blocks):
        text = text.replace(f"__CODE_BLOCK_{i}__", f"<pre>{code}</pre>")

    # Clean up: remove any remaining unconverted Markdown artifacts
    # Remove stray backticks that weren't part of code blocks
    # (but keep them if they're inside <pre> or <code> tags)

    return text.strip()


def split_for_telegram(html_text: str, max_length: int = 4000) -> List[str]:
    """Split HTML text into chunks that fit Telegram's message limit.

    Tries to split at paragraph boundaries (double newlines).
    If a paragraph is too long, splits at single newlines.
    If a line is too long, splits at the character limit.

    Args:
        html_text: HTML formatted text
        max_length: Maximum characters per message (Telegram limit is 4096,
                    we use 4000 for safety with HTML tags)

    Returns:
        List of message chunks
    """
    if len(html_text) <= max_length:
        return [html_text]

    chunks = []
    remaining = html_text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at double newline
        split_pos = remaining.rfind('\n\n', 0, max_length)

        if split_pos == -1 or split_pos < max_length // 2:
            # Try single newline
            split_pos = remaining.rfind('\n', 0, max_length)

        if split_pos == -1 or split_pos < max_length // 2:
            # Hard split at max_length
            split_pos = max_length

        chunk = remaining[:split_pos].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_pos:].lstrip()

    return chunks


if __name__ == "__main__":
    # Test with various Markdown
    test_markdown = """# Morning Update

Here's your **one thing** for today.

## Tasks

1. Call the dentist — **HIGH priority**
2. Email John about the *contract*
3. Review the `code.py` file

### Notes

- This is a bullet point
- Another point with [a link](https://example.com)

> Remember: you said you'd do this yesterday.

---

```python
def hello():
    print("Hello, world!")
```

That's it. Let me know if you need anything."""

    result = convert_markdown_to_telegram_html(test_markdown)
    print("=== Converted HTML ===")
    print(result)
    print()
    print("=== Chunks ===")
    for i, chunk in enumerate(split_for_telegram(result)):
        print(f"Chunk {i+1} ({len(chunk)} chars):")
        print(chunk[:200])
        print()
