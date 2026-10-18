"""Give each demo listing its own words (`source_text`), from the notes in the earlier map file.

"Does it have X?" wishes (gas included, pets allowed) are answered only from a listing's own text,
with an exact quote. The demo listings were saved as parsed fields, so this copies the original
notes back in. Walk-time guesses are left out on purpose: real times come from Google.

Run once:  .venv/bin/python scripts/add_demo_text.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "reference" / "UCLA-Apartment-Map.html"
DEMO = ROOT / "data" / "demo_listings.json"

# Reference field -> label in the text.
LABELS = [("tot", "Rent"), ("bdba", "Size"), ("laun", "Laundry"), ("park", "Parking"),
          ("avail", "Available"), ("pro", "Pros"), ("con", "Cons")]
# Names that differ between the two files.
ALIASES = {"1615 Greenfield Ave": "1615 Greenfield Ave (Unit 9)", "1375 Midvale Ave": "1375 Midvale Apartments"}


def reference_notes() -> dict[str, dict]:
    html = REFERENCE.read_text()
    block = html[html.index("const apts = ["):]
    block = block[:block.index("\n];")]
    notes = {}
    for chunk in re.split(r"\n\s*\{\s*n:", block)[1:]:
        fields = dict(re.findall(r'(\w+):"((?:[^"\\]|\\.)*)"', "n:" + chunk))
        notes[fields["n"]] = fields
    return notes


def main() -> None:
    notes = reference_notes()
    demo = json.loads(DEMO.read_text())
    for listing in demo:
        street = listing["address"].split(",")[0]
        name = ALIASES.get(street, street)
        n = notes.get(name)
        if n is None:
            print("no notes for", listing["address"])
            continue
        listing["source_text"] = "\n".join(f"{label}: {n[key]}" for key, label in LABELS if n.get(key))
    # One listing per line, like the file already is, so the git diff stays readable.
    DEMO.write_text("[\n" + ",\n".join("  " + json.dumps(d, ensure_ascii=False) for d in demo) + "\n]\n")
    print(f"added text to {sum('source_text' in d for d in demo)} of {len(demo)} listings")


if __name__ == "__main__":
    main()
