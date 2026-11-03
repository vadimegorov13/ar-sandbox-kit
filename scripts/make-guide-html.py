#!/usr/bin/python3
"""Turn docs/USER_GUIDE.md into a standalone, printable HTML page.

Handles the Markdown the guide uses: headings, paragraphs, ordered and
unordered lists, tables, block quotes, images and inline bold/code/links.
Usage: make-guide-html.py USER_GUIDE.md OUTPUT.html
"""
import html
import re
import sys

STYLE = """
:root { --ink:#17202a; --muted:#55616f; --accent:#087f73; --line:#d8e2e7; --wash:#eef5f7; --note:#fff6dd; }
* { box-sizing:border-box; }
body { margin:0; color:var(--ink); background:#f3f6f7; font:16px/1.55 system-ui,"Segoe UI",sans-serif; }
main { max-width:980px; margin:auto; background:#fff; padding:32px 48px 64px; box-shadow:0 6px 30px #0001; }
h1 { font-size:2.3rem; margin:0 0 .2em; color:#074b61; }
h2 { margin-top:2.2em; padding-bottom:.25em; border-bottom:2px solid var(--line); color:#074b61; }
h3 { margin-top:1.6em; color:var(--accent); }
a { color:#146b9c; }
code { background:var(--wash); padding:.1em .35em; border-radius:4px; font-size:.92em; }
table { border-collapse:collapse; width:100%; margin:1em 0; font-size:.95rem; }
th, td { border:1px solid var(--line); padding:7px 10px; text-align:left; vertical-align:top; }
th { background:var(--wash); }
blockquote { margin:1.2em 0; padding:12px 16px; background:var(--note); border-left:5px solid #d98b00; border-radius:6px; }
blockquote p { margin:0; }
figure { margin:1.4em 0; text-align:center; }
figure img { max-width:min(100%, 760px); border:1px solid var(--line); border-radius:6px; }
figcaption { color:var(--muted); font-size:.9rem; margin-top:.4em; }
@media print {
  body { background:#fff; font-size:11pt; }
  main { box-shadow:none; padding:0; max-width:none; }
  h2 { break-before:page; }
  h2:first-of-type { break-before:auto; }
  table, figure, blockquote { break-inside:avoid; }
  a { color:inherit; text-decoration:none; }
}
"""


def slug(text):
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"\s+", "-", text.strip())


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def convert(markdown):
    lines = markdown.splitlines()
    out, title, i = [], "AR Sandbox User Guide", 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif m := re.match(r"(#{1,4})\s+(.*)", line):
            level, text = len(m.group(1)), m.group(2)
            if level == 1:
                title = text
            out.append(f'<h{level} id="{slug(text)}">{inline(text)}</h{level}>')
            i += 1
        elif m := re.match(r"!\[([^\]]*)\]\(([^)]+)\)\s*$", line):
            alt, src = m.groups()
            out.append(f'<figure><img src="{html.escape(src)}" alt="{html.escape(alt)}">'
                       f"<figcaption>{inline(alt)}</figcaption></figure>")
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            head, body = rows[0], rows[1:]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head)
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
                                 for row in body)
                       + "</tbody></table>")
        elif line.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip("> ").rstrip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(quote))}</p></blockquote>")
        elif re.match(r"(\d+\.|-)\s", line):
            ordered = bool(re.match(r"\d+\.", line))
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines) and re.match(r"(\d+\.|-)\s", lines[i]):
                items.append(re.sub(r"^(\d+\.|-)\s+", "", lines[i]))
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(item)}</li>" for item in items)
                       + f"</{tag}>")
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(
                    r"(#{1,4}\s|\||>|!\[|\d+\.\s|-\s)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
    body = "\n".join(out)
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{html.escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n"
            f"<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: make-guide-html.py USER_GUIDE.md OUTPUT.html")
    with open(sys.argv[1], encoding="utf-8") as f:
        page = convert(f.read())
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(page)
