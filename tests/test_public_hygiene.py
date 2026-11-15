"""Nothing private in a file this repository publishes.

The repository is meant to be public, so every file git would publish is scanned for what does not
belong in it: the owner's name outside LICENSE, references to planning notes that live elsewhere
(the plan, the progress log, their decision ids), and names from outside the project. Those names
are compared as SHA-256 hashes of each word, so this test does not publish them either. A comment
gives the product reason, or links a decision record in docs/decisions/, never a conversation.
"""

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# the first 16 hex characters of sha256(word) for each word that must not appear
PRIVATE_WORD_HASHES = {
    "09d00fc66614722e", "a8b180d2c8034c82", "45bb18f62b4c229c", "4279dea103719fc2",
    "674b17288aa29d8b", "cafb41334d62257c", "fe8c433a0e86185e", "ef92dd8f9a2fd9be",
}
# the planning files' names, the same way but case kept, so the plain English words stay allowed
PLANNING_WORD_HASHES = {"0ff15403106fefda", "e0d0adc74c8be52a"}
# The owner's name comes from LICENSE, the one file that must carry it, so this file does not spell it out either.
OWNER = re.search(r"^Copyright \(c\) \d{4} (.+)$", (ROOT / "LICENSE").read_text(encoding="utf-8"), re.M).group(1).strip()
FIRST = OWNER.split()[0]
PATTERNS = {
    "owner's first name": re.compile(rf"\b{re.escape(FIRST)}\b|\b{re.escape(FIRST)}'s\b"),
    "planning notes": re.compile(r"\bD[1-9]\b|(?i:\bmilestones? \d)"),
    # a database address (scheme://user@host) is not an email
    "an email address": re.compile(r"(?<!://)(?<![\w.+-])[\w.+-]+@(?!example\.(?:com|org|net)\b)[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b"),
}
BINARY = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf"}
# The author's byline at the top of the README, as the sibling demos carry it; the only place the name may appear
# besides LICENSE.
BYLINE_TEXT = f"By [{OWNER}](https://www.linkedin.com/in/{OWNER.replace(' ', '').lower()})."
BYLINE = re.compile(rf"^{re.escape(BYLINE_TEXT)}$")


def published_files() -> list[Path]:
    """What git would publish: tracked files plus untracked ones that are not ignored."""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines() if line and (ROOT / line).suffix.lower() not in BINARY]


def read_published(path: Path) -> str:
    """A file's text; one that is not UTF-8 is read as Latin-1 rather than skipped, so it is scanned too."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def findings(path: Path, text: str) -> list[str]:
    found = []
    rel = path.relative_to(ROOT).as_posix()
    for n, line in enumerate(text.splitlines(), 1):
        if rel == "README.md" and BYLINE.match(line):
            continue
        for what, pattern in PATTERNS.items():
            if what == "owner's first name" and rel == "LICENSE":
                continue
            if pattern.search(line):
                found.append(f"{rel}:{n}: {what}")
        for word in re.findall(r"[A-Za-z]+", line):
            if hashlib.sha256(word.lower().encode()).hexdigest()[:16] in PRIVATE_WORD_HASHES and rel != "LICENSE":
                found.append(f"{rel}:{n}: a name from outside the project")
            if hashlib.sha256(word.encode()).hexdigest()[:16] in PLANNING_WORD_HASHES:
                found.append(f"{rel}:{n}: planning notes")
    return found


def test_no_published_file_carries_private_names_or_planning_notes():
    files = published_files()
    assert len(files) > 100  # the scan is looking at the repository, not an empty list
    found = []
    for path in files:
        if path == Path(__file__).resolve():  # the scanner's own samples below are leaks on purpose
            continue
        try:
            text = read_published(path)
        except FileNotFoundError:  # listed by git but deleted since
            continue
        found += findings(path, text)
    assert found == []


def test_the_scan_catches_each_kind_of_leak():
    sample = ROOT / "src" / "example.py"
    assert findings(sample, f"# {FIRST}, 2026-11-14: ship it")
    assert findings(sample, "# in milestone 3 the fields come from Claude")
    assert findings(sample, '"""The command line. Milestone 1: the checks"""')
    assert not findings(sample, 'd="M1 2 L3 4 M10 20"')  # SVG path data is not a milestone
    assert findings(sample, "# decided in D4")
    assert findings(sample, "# write to someone@mail.invalid")  # a reserved domain: no real mailbox
    assert not findings(sample, "# write to ap@example.com")
    assert not findings(sample, 'url = "postgresql://app@db.internal:5432"')
    assert not findings(sample, "# a 2D canvas and the Mathematics of it")
    readme = ROOT / "README.md"  # the author's byline, as the sibling demos have it, and nothing else
    assert not findings(readme, BYLINE_TEXT)
    assert findings(readme, f"{FIRST} asked for this layout")
    assert findings(sample, BYLINE_TEXT)


def test_planning_file_names_are_caught_by_the_exact_word(monkeypatch):
    """The planning files' names are hashed like the outside names; shown with a stand-in word so this file does not
    publish them."""
    monkeypatch.setattr(sys.modules[__name__], "PLANNING_WORD_HASHES", {hashlib.sha256(b"ROADMAP").hexdigest()[:16]})
    sample = ROOT / "src" / "example.py"
    assert findings(sample, "# see ROADMAP.md section 4")
    assert findings(sample, "# ROADMAP M4's three named tests")
    assert not findings(sample, "# the roadmap for next year")  # the plain word, in lower case, is fine


def test_a_file_that_is_not_utf8_is_still_scanned(tmp_path):
    odd = tmp_path / "notes.txt"
    odd.write_bytes(f"{FIRST} said ship it \u00e9".encode("latin-1"))
    assert findings(ROOT / "src" / "example.py", read_published(odd))
