"""Extract upstream's labels/traits; run after updating Sources/Catalog.swift."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "Sources/Catalog.swift").read_text(encoding="utf-8")
actions = {}


def call_at(start):
    depth, quoted, escaped = 0, False, False
    for end in range(start, len(source)):
        c = source[end]
        if escaped:
            escaped = False
        elif c == "\\" and quoted:
            escaped = True
        elif c == '"':
            quoted = not quoted
        elif not quoted:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if not depth:
                    return source[start:end + 1]
    raise ValueError("Unclosed Swift call")


for match in re.finditer(r'\b(format|WheelOption|o|strip)\((?:id: )?"((?:img|pdf|vid|aud|doc|gen)\.[^"]+)"', source):
    function, action = match.groups()
    call = call_at(source.index("(", match.start()))
    fields = dict(re.findall(r'(big|symbol|ammo|title|detail):\s*"([^"\n]*)"', call))
    strings = re.findall(r'"([^"\n]*)"', call)
    if function == "o":
        fields.update(zip(("big", "ammo", "title", "detail"), strings[2:6]))
    if function == "strip":
        fields.update(title="去隐私", ammo="去隐私", symbol="location.slash")
    actions.setdefault(action, {"id": action, **fields})

traits = {}
for kind in ("image", "pdf", "video", "audio", "doc"):
    body = re.search(r'static let ' + kind + r'Traits:.*?= \[(.*?)\n    \]', source, re.S).group(1)
    traits[kind] = {key: [float(x) for x in values.split(",")] for key, values in re.findall(r'"([^"]+)": \[([^\]]+)\]', body)}

target = ROOT / "windows/formatwheel/catalog_data.json"
target.write_text(json.dumps({"actions": actions, "traits": traits}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Synced {len(actions)} actions to {target}")
