"""peek_text.py <id> [head_chars]  -> print the head of the html body."""
import json, re, sys, pathlib
book_id = sys.argv[1]
head_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 2500
p = pathlib.Path(__file__).parent.parent / "pages" / "extensions" / "texts" / f"{book_id}.js"
s = p.read_text(encoding="utf-8")
# Find the html string literal (greedy to end)
m = re.search(r'html:\s*"(.*)"\s*\}\s*;\s*$', s, re.DOTALL)
if not m:
    print("no match")
    sys.exit(1)
raw = m.group(1)
# json.loads expects JSON escapes: \/ is valid JSON escape for /
body = json.loads('"' + raw + '"')
print(body[:head_chars])
print(f"\n---\nlen(html)={len(body)}  <p>={body.count('<p>')}  chap={body.count('chap')}  <h3>={body.count('<h3>')}")
