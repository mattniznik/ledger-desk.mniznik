"""Write web/src/site-data.json: every number the page shows about how well the demo works and how it was
built, read from the repository so none is typed in by hand.

Usage (from the repo root, with the test database up):
    uv run python scripts/export_site.py

What it reads:
- both test suites, by RUNNING them (pytest, and Vitest in web/), and their totals. It refuses to export
  while any test fails or a suite reports none, so the page never shows a count from a red suite;
- the eval results in evals/results/, one file per run;
- the recorded real runs the demo replays (replays/claude-opus-5-5-low-run2/), with their calls, cost and time;
- the decision records' index, docs/decisions/README.md;
- the approval limits in src/ledger_desk/rules.py.

The pure parts are tested in tests/test_export_site.py; main() runs only when this file is run directly.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAYS = ROOT / "replays" / "claude-opus-5-5-low-run2"
OUT = ROOT / "web" / "src" / "site-data.json"


# ---------------------------------------------------------------- pure parts

def count_pytest(output: str) -> dict:
    """The totals on pytest's summary line ("1 failed, 335 passed, 2 errors in 9.1s")."""
    line = next((l for l in reversed(output.splitlines()) if re.search(r"\d+ (passed|failed)", l) and " in " in l), None)
    if line is None:
        raise ValueError("no pytest summary line with a passed or failed count")
    n = lambda word: sum(int(m) for m in re.findall(rf"(\d+) {word}", line))  # noqa: E731
    passed, failed = n("passed"), n("failed") + n("errors?")
    return {"tests": passed + failed, "passed": passed, "failed": failed}


def count_vitest(output: str) -> dict:
    """The totals on Vitest's "Tests" line ("Tests  2 failed | 56 passed (58)")."""
    m = re.search(r"^\s*Tests\s+(.*)\((\d+)\)\s*$", output, re.M)
    if m is None:
        raise ValueError("no Vitest 'Tests' line")
    counts = dict((word, int(num)) for num, word in re.findall(r"(\d+) (passed|failed)", m.group(1)))
    files = re.search(r"^\s*Test Files\s+(.*)\((\d+)\)\s*$", output, re.M)
    # a test file that fails to load runs none of its tests: "Test Files 1 failed" with every test line passing
    files_failed = int(re.search(r"(\d+) failed", files.group(1)).group(1)) if files and "failed" in files.group(1) else 0
    return {"tests": int(m.group(2)), "passed": counts.get("passed", 0), "failed": counts.get("failed", 0) + files_failed,
            "files": int(files.group(2)) if files else 0}


def require_green(suites: dict) -> None:
    for name, c in suites.items():
        if c["failed"] or not c["tests"] or c.get("exit", 0) != 0:
            sys.exit(f"refusing to export: the {name} suite has {c['failed']} failing of {c['tests']}, exit code {c.get('exit', 0)}")


def eval_runs(folder: Path) -> list[dict]:
    runs = []
    for path in sorted(folder.glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        s = d["summary"]
        reading = s["reading"]
        runs.append({
            "file": path.name,
            "model": d["model"],
            "version": d.get("version"),
            "date": d.get("date"),
            "tier": d.get("tier") or ("hard" if "-hard-" in path.name else "standard"),
            "proves": "the graders and the rules, not a model" if d["model"] == "scripted" else "the model and the code together",
            "cases": s["cases"],
            "end_result": s["end_result"]["exact"],
            "known_limits": s["end_result"].get("known_limits", []),
            "fields": sum(r["fields"] for r in reading.values()),
            "fields_correct": sum(r["fields_correct"] for r in reading.values()),
            "pdf_fields": reading.get("pdf", {}).get("fields_correct", 0),
            "photo_fields": reading.get("photo", {}).get("fields_correct", 0),
            "account_top1": s["account"]["top1"],
            "account_graded": s["account"]["graded"],
            "safe": s["safety"]["passed"],
            "model_calls": s["cost"]["metrics"]["model_calls"],
            "usd": s["cost"]["usd"],
            "per_invoice_usd": s["cost"]["per_invoice_usd"],
            "per_invoice_seconds": s["time"]["per_invoice_seconds"],
        })
    return runs


def field(folder: Path) -> dict:
    """Each bill of the real model's standard eval run with its outcome, for the dot field: one dot per bill."""
    path = next(p for p in sorted(folder.glob("*.json")) if "-hard-" not in p.name and "scripted" not in p.name)
    d = json.loads(path.read_text(encoding="utf-8"))
    keep = ("id", "document", "status", "exact", "safe")
    return {"file": path.name, "cases": [{k: c[k] for k in keep} for c in d["cases"]]}


def _spread(values: list[float]) -> dict:
    return {"total": round(sum(values), 6), "mean": round(statistics.mean(values), 6), "median": round(statistics.median(values), 6),
            "min": round(min(values), 6), "max": round(max(values), 6)}


MODEL_NAMES = {"claude-opus-5-5": "Claude Opus 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-haiku-5-5": "Claude Haiku 5.5"}


def model_of(folder: Path) -> dict:
    """The model the recorded runs used, with the name people read."""
    first = next(json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json")) if p.name != "summary.json")
    return {"id": first["model"], "name": MODEL_NAMES.get(first["model"], first["model"])}


def _first_paragraph(text: str) -> str:
    return (text or "").strip().split("\n\n")[0].strip()


def recorded_runs(folder: Path) -> dict:
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]
    records = [r for r in records if "outcome" in r]  # summary.json is not a run
    return {
        "folder": folder.relative_to(ROOT).as_posix(),
        "model": records[0]["model"],
        "date": records[0]["date"],
        "n": len(records),
        "matched": sum(1 for r in records if r.get("match", {}).get("all")),
        "model_calls": sum(r["metrics"]["model_calls"] for r in records),
        "cost_usd": _spread([r["metrics"]["cost_usd"] for r in records]),
        "seconds": _spread([r["seconds"] for r in records]),
        "runs": [{
            "sample": r["id"], "calls": r["metrics"]["model_calls"], "cost_usd": r["metrics"]["cost_usd"], "seconds": r["seconds"],
            "vendor": r["outcome"]["extraction"]["vendor_name"], "number": r["outcome"]["extraction"]["number"],
            "total": r["outcome"]["extraction"]["total"], "status": r["outcome"]["status"], "account": r["outcome"].get("account"),
            "flags": [{"code": f["code"], "amount": f.get("amount"), "detail": f.get("detail", "")} for f in r["outcome"]["flags"]],
            "explanation": _first_paragraph(r["outcome"].get("explanation") or ""),
            "steps": [{"task": x["task"], "tools": [t.get("name") for t in x["reply"].get("tool_calls", [])]} for x in r.get("replies", [])],
            "source_checks": _source_counts(r["outcome"].get("source_checks") or {}),
            "next_step": _next_step(r["outcome"]),
            "usage": [_usage(u) for u in r.get("model_usage", [])],
        } for r in records],
    }


def _usage(u: dict) -> dict:
    """One model call's tokens, as the API reported them: for the trace waterfall's measured bars."""
    parts = {"input": u.get("input_tokens") or 0, "cache_write": u.get("cache_creation_input_tokens") or 0,
             "cache_read": u.get("cache_read_input_tokens") or 0, "output": u.get("output_tokens") or 0}
    return {"step": u.get("step"), **parts, "tokens": sum(parts.values())}


def _source_counts(checks: dict) -> dict:
    return {k: sum(1 for v in checks.values() if v == k) for k in ("ok", "missing", "not_checked")}


def _next_step(outcome: dict) -> dict | None:
    """The playbook's suggested step for a recorded run, as the page would show it (no credit memos queued)."""
    from ledger_desk.company import build_company
    from ledger_desk.playbook import next_step

    step = next_step(outcome.get("flags") or [], outcome.get("extraction") or {}, build_company())
    return {"code": step["code"], "decision": step["decision"], "action": step["action"]} if step else None


def replayed_lookups(folder: Path, db: str, samples: list[str] | None = None) -> dict[str, list[dict]]:
    """Each recorded run replayed through today's code on a scratch database, for the agent's lookups with their
    real results (the recordings hold the model's requests, not what the ERP answered)."""
    from ledger_desk.company import build_company
    from ledger_desk.db import connect, reset_database, seed_erp
    from ledger_desk.invoices import load_case
    from ledger_desk.runner import ReplayModel, run_case

    reset_database(db)
    company = build_company()
    with connect(db) as conn:
        seed_erp(conn, company)
        conn.commit()
    out = {}
    for path in sorted(folder.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if "outcome" not in record or (samples and record["id"] not in samples):
            continue
        replayed = run_case(load_case(record["id"]), ReplayModel(record["replies"]), db, ROOT / "out", company)
        if replayed.get("error"):  # an empty list here would read as "no lookups" on the page
            raise RuntimeError(f"recorded run {record['id']} failed on replay: {replayed['error']}")
        out[record["id"]] = replayed["outcome"].get("lookups", [])
    return out


def policies() -> dict:
    """The approval limits the page quotes, read from the rules the checks enforce."""
    from ledger_desk.agent import MAX_TOOL_CALLS
    from ledger_desk.rules import CONTROLLER_FROM, PRICE_TOLERANCE

    return {"controller_from": float(CONTROLLER_FROM), "price_tolerance_percent": float(PRICE_TOLERANCE * 100), "max_lookups": MAX_TOOL_CALLS}


def built_steps(data: dict, repo: str | None) -> list[dict]:
    """How it was built: the loop every change goes through. Every number in a fact comes from the data."""
    t, rec = data["tests"], data["recorded"]
    at = (lambda path: f"{repo}/{path}") if repo else (lambda path: None)
    usd = lambda v, d=4: f"${v:,.{d}f}"  # noqa: E731
    total_tests = t["python"]["tests"] + t["web"]["tests"]
    total_files = t["python"]["files"] + t["web"]["files"]
    c = rec["cost_usd"]
    return [
        {"title": "Plan from the provider's documentation",
         "text": "Each decision quotes the documentation it rests on, with the date it was read, and says what would change it.",
         "fact": "Decision records in docs/decisions, each with its sources and measurements", "url": at("tree/main/docs/decisions")},
        {"title": "Write the test, watch it fail",
         "text": "Each change starts with a test, and it has to fail on the old code for the reason expected before the code is written.",
         "fact": f"{total_tests} tests in {total_files} files, Python and the page, all passing", "url": at("tree/main/tests")},
        {"title": "Change the code",
         "text": "Small steps, each with its tests. What decides money is code that checks after the model reads, never the model alone.",
         "fact": f"{data['checks']} checks in code, each with a suggested next step", "url": at("blob/main/src/ledger_desk/rules.py")},
        {"title": "Measure on real runs",
         "text": "Real Claude runs are recorded with the tokens and time they reported, then replayed through today's code at no cost.",
         "fact": f"{rec['n']} real runs recorded, {rec['matched']} of {rec['n']} ending as their answer key says; "
                 f"{usd(c['total'], 2)} at API list prices in all, {usd(c['min'])} to {usd(c['max'])} each",
         "url": at("tree/main/replays")},
        {"title": "Independent review",
         "text": "A reviewer with fresh context reads each change that touches money, an outward action or more than one area.",
         "fact": "Review findings and their fixes recorded in decisions 0007 and 0010", "url": at("tree/main/docs/decisions")},
        {"title": "Check it in a browser",
         "text": "The page is built and opened in a real browser at a desktop and a phone size on every change, against the real API, and the live deploy on Azure is checked the same way.",
         "fact": "Browser tests at 1280 x 800 and 390 x 844", "url": at("tree/main/web/e2e")},
    ]


def checks_count() -> int:
    """How many kinds of problem the checks name: one playbook step each (playbook.py)."""
    from ledger_desk.playbook import STEPS

    return len(STEPS)


def decisions(index: Path) -> list[dict]:
    rows = re.findall(r"^\| \[(\d{4})\]\(([^)]+)\) \| ([^|]+?) \|", index.read_text(encoding="utf-8"), re.M)
    return [{"number": n, "title": title.strip(), "file": f"docs/decisions/{link}"} for n, link, title in rows]


# ---------------------------------------------------------------- the README's generated blocks

def layouts(presets: Path) -> list[dict]:
    """The Studio's layouts (web/src/studio/presets.ts OPTIONS), with which one is the default."""
    text = presets.read_text(encoding="utf-8")
    default = re.search(r'export const DEFAULT = \{ option: "(\d+)"', text).group(1)
    rows = re.findall(r'\{ id: "(\d+)", name: "([^"]+)",(?: simple: \d,)? short: "([^"]+)"', text)
    return [{"id": i, "name": n, "short": sh, "default": i == default} for i, n, sh in rows]


def studio(presets: Path) -> dict:
    """How many colour sets and typefaces the Studio offers, and the default's names."""
    text = presets.read_text(encoding="utf-8")
    pal = text.split("export const PALETTES", 1)[1].split("export const FONTS", 1)[0]
    fonts = text.split("export const FONTS", 1)[1].split("export const DEFAULT", 1)[0] if "export const DEFAULT" in text.split("export const FONTS", 1)[1] else text.split("export const FONTS", 1)[1]
    d = re.search(r'export const DEFAULT = \{ option: "(\d+)", palette: "(\w+)", font: "(\w+)" \}', text)
    name_of = lambda block, key: re.search(rf"\b{key}: \{{ name: \"([^\"]+)\"", block).group(1)  # noqa: E731
    return {"palettes": pal.count('name: "'), "fonts": fonts.count('name: "'),
            "palette": name_of(pal, d.group(2)), "font": name_of(fonts, d.group(3))}


def _model_name(model: str) -> str:
    if model == "scripted":
        return "Scripted reader (proves the graders, not a model)"
    m = re.search(r"claude-([a-z]+)-(\d+)-(\d+)", model)
    return f"Claude {m.group(1).title()} {m.group(2)}.{m.group(3)}" if m else model


def readme_blocks(data: dict, lays: list[dict], counts: dict | None = None) -> dict:
    rec, tests = data["recorded"], data["tests"]
    model = data["model"]["name"]
    rows = []
    for r in sorted(data["evals"], key=lambda r: (r["model"] == "scripted", r["tier"] != "standard")):
        cost = "none" if r["model"] == "scripted" else f"${r['per_invoice_usd']:.4f}"
        rows.append(f"| {_model_name(r['model'])} | {r['tier']} | {r['cases']} | {r['end_result']} of {r['cases']} | "
                    f"{r['fields_correct']} of {r['fields']} | {r['account_top1']} of {r['account_graded']} | {r['safe']} of {r['cases']} | "
                    f"{cost} | {r['per_invoice_seconds']:.1f} |")
    c, sec = rec["cost_usd"], rec["seconds"]
    results = "\n".join([
        "One run per configuration, so small differences are unproven. The bills are rendered for the demo and are cleaner",
        "than real scans, so real bills may do worse; that has not been tested.",
        "",
        "| Model | Tier | Bills | Ended as expected | Fields read | Accounts | Safe | Cost a bill | Seconds a bill |",
        "|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "\"Safe\" means nothing reached the books without an approval. The scripted reader is a perfect reader built from the",
        "answer key: it proves the graders and the checks, not a model.",
        "",
        f"**The recorded runs the demo replays** ({model}, effort low): {rec['matched']} of {rec['n']} bills end as their answer",
        f"key says; {rec['model_calls']} model calls; ${c['total']:.2f} at API list prices in all (mean ${c['mean']:.3f}, median",
        f"${c['median']:.3f} a bill, n={rec['n']}); {sec['total']:.1f} s in all (median {sec['median']:.1f} s a bill). They ran on a",
        "Claude Code subscription, so nothing was spent.",
    ])
    default = next(l for l in lays if l["default"])
    k = counts or {}
    intro = "\n".join([
        "**Live demo: [ledger-desk.mniznik.com](https://ledger-desk.mniznik.com)**, on Microsoft Azure: the app API and the mock ERP",
        "on Azure Container Apps, the database on Azure Database for PostgreSQL, the secrets in Azure Key Vault and the page on",
        "Azure Static Web Apps, all set up with Terraform ([Where it runs](#where-it-runs-microsoft-azure)).",
        "",
        f"The demo replays {rec['n']} recorded real runs of {model} through today's code, so it costs",
        f"nothing per visit; {rec['matched']} of {rec['n']} end as their answer key says. {tests['python']['passed']} Python tests and",
        f"{tests['web']['passed']} page tests pass, and browser tests check every layout at 1280 x 800 and 390 x 844.",
        "",
        f"**A customizable page.** {len(lays)} layouts" + (f", {k['palettes']} colour sets and {k['fonts']} typefaces" if k else "")
        + f", with the same bills and numbers in all of them; the default is layout {default['id']}, {default['name']}. See",
        "[Design](#design-the-layouts-on-the-web-and-on-a-phone).",
        "",
        f'<img alt="Layout {default["id"]}, {default["name"]}, at 1280 pixels: the bill desk with the walkthrough button, the cards '
        f'for bills ready, bills that need a look and money caught" src="docs/img/layouts/{default["id"]}-web.jpg" width="640">',
    ])
    pairs = []
    for l in lays:
        tag = " (the default)" if l["default"] else ""
        pairs += [
            "<tr>",
            f'<td><img alt="Layout {l["id"]}, {l["name"]}, on the web" src="docs/img/layouts/{l["id"]}-web.jpg" width="640"></td>',
            f'<td><img alt="Layout {l["id"]}, {l["name"]}, on a phone" src="docs/img/layouts/{l["id"]}-phone.jpg" width="300"></td>',
            "</tr>",
            f'<tr><td colspan="2"><b>{l["id"]} {l["name"]}</b>{tag} - {l["short"]}</td></tr>',
        ]
    design = "\n".join([
        f"The default is layout {default['id']}, {default['name']}" + (f", in {k['palette']} with {k['font']}" if k else "") + ".",
        "Each pair is the page at 1280 x 800 and at 390 x 844, with reduced motion so the animations show their last frame.",
        "",
        "<table>",
        "<tr><th>Web, 1280 x 800</th><th>Phone, 390 x 844</th></tr>",
        *pairs,
        "</table>",
    ])
    return {"intro": intro, "results": results, "design": design}


def fill_readme(text: str, blocks: dict) -> str:
    """Put each block between its <!-- generated:NAME --> and <!-- /generated:NAME --> markers; nothing else changes."""
    for name, body in blocks.items():
        start, end = f"<!-- generated:{name} -->", f"<!-- /generated:{name} -->"
        if start not in text or end not in text:
            raise ValueError(f"README has no {start} ... {end} markers")
        head, rest = text.split(start, 1)
        _, tail = rest.split(end, 1)
        text = f"{head}{start}\n{body}\n{end}{tail}"
    return text


# ---------------------------------------------------------------- the run

def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=sys.platform == "win32")
    return out.returncode, out.stdout + out.stderr


def _with_lookups(rec: dict) -> dict:
    lookups = replayed_lookups(REPLAYS, "ledger_desk_export")
    for r in rec["runs"]:
        r["lookups"] = lookups.get(r["sample"], [])
    return rec


def run_suites(_out: Path) -> dict:
    return {
        "python": run(["uv", "run", "pytest", "-p", "no:warnings"], ROOT),
        "web": run(["npx", "vitest", "run"], ROOT / "web"),
    }


def export(out: Path, suites_runner=run_suites, readme: Path | None = None) -> dict:
    """Write the new data, run both suites against it (the page's tests read this file), then keep it with the
    fresh counts, or put the previous file back and refuse if anything failed."""
    previous = out.read_text(encoding="utf-8") if out.exists() else None
    data = {
        "generated": date.today().isoformat(),
        "tests": json.loads(previous).get("tests") if previous else None,
        "evals": eval_runs(ROOT / "evals" / "results"),
        "recorded": _with_lookups(recorded_runs(REPLAYS)),
        "decisions": decisions(ROOT / "docs" / "decisions" / "README.md"),
        "policies": policies(),
        "model": model_of(REPLAYS),
        "checks": checks_count(),
        "field": field(ROOT / "evals" / "results"),
    }
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        output = suites_runner(out)  # {"python": (exit code, output), "web": (exit code, output)}
        suites = {"python": count_pytest(output["python"][1]), "web": count_vitest(output["web"][1])}
        suites["python"]["exit"], suites["web"]["exit"] = output["python"][0], output["web"][0]
        suites["python"]["files"] = len(list((ROOT / "tests").glob("test_*.py")))
        require_green(suites)
        for c in suites.values():
            c.pop("exit")
    except BaseException:  # a red suite, a missing executable, Ctrl+C: never leave untested data behind
        if previous is None:
            out.unlink()
        else:
            out.write_text(previous, encoding="utf-8")
        raise
    data["tests"] = suites
    data["built"] = {"repo": None, "steps": built_steps(data, None), "badge": None, "links": []}
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if readme is not None:  # the README's tables and the design section, from the same data
        presets = ROOT / "web" / "src" / "studio" / "presets.ts"
        blocks = readme_blocks(data, layouts(presets), studio(presets))
        readme.write_text(fill_readme(readme.read_text(encoding="utf-8"), blocks), encoding="utf-8")
    return data


def main() -> None:
    data = export(OUT, readme=ROOT / "README.md")
    t = data["tests"]
    print(f"wrote {OUT.relative_to(ROOT)}: python {t['python']['passed']} and web {t['web']['passed']} tests passed; "
          f"{len(data['evals'])} eval runs; {data['recorded']['n']} recorded runs; {len(data['decisions'])} decisions")


if __name__ == "__main__":
    main()
