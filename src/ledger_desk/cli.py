"""The ledger-desk command line: the checks on each sample invoice's ground-truth fields with no model, so the
rules can be seen working on their own, and the commands that serve, run and grade the demo.

    uv run ledger-desk check 03          one invoice: status, flags, approver, account
    uv run ledger-desk inbox             all 13, each compared with its expected result
    uv run ledger-desk render [--out D]  the PDFs and the phone photo, from the YAML
    uv run ledger-desk db-reset          recreate the local database and seed the ERP
    uv run ledger-desk erp-serve         the mock ERP on 127.0.0.1:8100, docs at /docs
    uv run ledger-desk api-serve         the app API on 127.0.0.1:8200 (the web app proxies /api to it)
    uv run ledger-desk run --model scripted|subscription [--ids 01,09] [--record replays/<dir>]
                                         the workflow on the samples, to the approval pause,
                                         compared with the ground truth; --record writes replays
    uv run ledger-desk eval --model scripted|subscription [--version dev] [--ids v01,v24]
                                         the 50-case eval set, graded in code; a results file
                                         per version and model in evals/results/
    uv run ledger-desk qbo-connect       connect the Intuit app to the QuickBooks sandbox once
                                         (OAuth consent in the browser, callback on localhost:8765);
                                         keys and tokens stay in .env.local, never printed
    uv run ledger-desk qbo-check         read the connected sandbox company's name
    uv run ledger-desk api-serve --mirror-quickbooks
                                         also mirror each approved bill to the QuickBooks sandbox
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .company import COMPANY_NAME, build_company
from .invoices import Case, load_all, load_case
from .rules import Result, check


def _usd(value) -> str:
    return f"${value:,.2f}" if value >= 0 else f"-${-value:,.2f}"


def _flag_text(result: Result) -> str:
    if not result.flags:
        return "no flags"
    parts = []
    for f in result.flags:
        extra = f" {_usd(f.amount)}" if f.amount is not None else f" {f.quantity:,} over" if f.quantity is not None else ""
        parts.append(f"{f.code}{extra}")
    return ", ".join(parts)


def _matches(case: Case, result: Result) -> bool:
    from decimal import Decimal

    def d(v):
        return None if v is None else Decimal(str(v))

    want = {(f["code"], d(f.get("amount")), d(f.get("quantity"))) for f in case.expected.get("flags", [])}
    got = {(f.code, f.amount, f.quantity) for f in result.flags}
    return (
        result.status == case.expected["status"]
        and got == want
        and result.approver == case.expected["approver"]
        and result.account == case.expected.get("account")
    )


def cmd_check(args) -> int:
    try:
        case = load_case(args.id)
    except FileNotFoundError:
        print(f"no sample invoice {args.id}; the ids are 01 to 13", file=sys.stderr)
        return 2
    inv, result = case.invoice, check(case.invoice, build_company())
    print(f"{case.slug}: {inv.vendor_name} {inv.number}, {_usd(inv.total)}")
    print(f"  {result.status}: {_flag_text(result)}")
    for f in result.flags:
        print(f"    {f.code}: {f.detail}")
    extra = ", controller only, phone check required" if result.controller_only else ""
    print(f"  approver: {result.approver}{extra}; account: {result.account or 'none'}")
    return 0


def cmd_inbox(args) -> int:
    company = build_company()
    cases = load_all()
    good = 0
    print(f"{COMPANY_NAME}: {len(cases)} invoices in the inbox")
    for case in cases:
        result = check(case.invoice, company)
        ok = _matches(case, result)
        good += ok
        mark = "ok  " if ok else "DIFF"
        print(f"  {mark} {case.id} {case.invoice.vendor_name:<28} {_usd(case.invoice.total):>12}  {result.status:<9} {result.approver:<10} {_flag_text(result)}")
    print(f"{good} of {len(cases)} match their ground truth")
    return 0 if good == len(cases) else 1


def cmd_render(args) -> int:
    from .documents import render_case

    out = Path(args.out)
    paths = [render_case(case, out) for case in load_all()]
    print(f"{len(paths)} documents in {out}")
    return 0


def cmd_db_reset(args) -> int:
    from .db import connect, reset_database, seed_erp

    reset_database(args.name)
    with connect(args.name) as conn:
        seed_erp(conn, build_company())
        conn.commit()
    print(f"database {args.name} recreated and seeded")
    return 0


LOCAL_API_KEY = "local-dev-key"  # local only: the server binds to 127.0.0.1; not a secret


def cmd_erp_serve(args) -> int:
    from .approval import new_key_pair
    from .erp.app import create_app

    from .settings import erp_settings

    # Deployed: its key and the approval public half from the environment. Locally: the dev key
    # and a throwaway pair (reads work; posting needs the API's matching private half).
    api_key, public_key = erp_settings()
    app = create_app(args.db, api_key=api_key, approval_public_key=public_key)
    if args.dry_run:
        for route in app.routes:
            for method in sorted(getattr(route, "methods", None) or []):
                if method != "HEAD":
                    print(f"{method} {route.path}")
        return 0
    import uvicorn

    key_note = f"X-API-Key: {LOCAL_API_KEY}, local only" if api_key == LOCAL_API_KEY else "key from LEDGER_DESK_ERP_KEY"  # never print a real key
    print(f"mock ERP on http://{args.host}:{args.port}/docs  ({key_note})")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def cmd_api_serve(args) -> int:
    from .api import create_api
    from .company import build_company
    from .db import apply_migrations, connect, seed_erp_if_empty

    from .settings import api_settings

    settings = api_settings()  # refuses a half-set deployment before anything starts
    mirror = None
    if args.mirror_quickbooks:  # checked before the database is touched
        from . import quickbooks as qbo

        try:
            qb = qbo.connect_from_env(qbo.EnvFile(qbo.ENV_PATH))
        except qbo.QuickBooksError as e:
            print(e, file=sys.stderr)
            return 1

        def mirror(request: dict) -> dict:
            return qbo.mirror_bill(qb, request)

    with connect(args.db) as conn:
        applied = apply_migrations(conn)
        # a deployed database is never reset, so a new one gets the demo company here, once
        seeded = seed_erp_if_empty(conn, build_company())
    if applied:
        print(f"migrated {args.db}: {', '.join(applied)}")
    if seeded:
        print(f"seeded the demo company in {args.db}")
    api = create_api(args.db, keys=settings.keys, erp_url=settings.erp_url, erp_key=settings.erp_key, web_origin=settings.web_origin, mirror=mirror)
    if mirror:
        print("approved bills are mirrored to the QuickBooks sandbox")
    if args.dry_run:
        for route in api.routes:
            for method in sorted(getattr(route, "methods", None) or []):
                if method != "HEAD":
                    print(f"{method} {route.path}")
        return 0
    import uvicorn

    print(f"app API on http://{args.host}:{args.port}/docs")
    uvicorn.run(api, host=args.host, port=args.port)
    return 0


def cmd_qbo_connect(args) -> int:
    """One OAuth consent: the authorize URL goes to the browser (or a file, never the screen, since
    it carries the client id), Intuit redirects to localhost, the code becomes tokens in .env.local."""
    import secrets
    import webbrowser

    import httpx

    from . import quickbooks as qbo

    env = qbo.EnvFile(qbo.ENV_PATH)
    try:
        client_id = env.require(qbo.CLIENT_ID)
        env.require(qbo.CLIENT_SECRET)
    except qbo.QuickBooksError as e:
        print(e, file=sys.stderr)
        return 1
    redirect = f"http://localhost:{args.port}/callback"
    state = secrets.token_urlsafe(24)
    url = qbo.authorize_url(client_id, redirect, state)
    if args.url_file:
        Path(args.url_file).write_text(url, encoding="utf-8")
        print(f"Intuit's consent URL is in {args.url_file} (not printed: it carries the client id)")
    else:
        webbrowser.open(url)
        print("opened Intuit's consent page in the browser")
    print(f"waiting for Intuit on {redirect} for up to {args.timeout:.0f} s", flush=True)
    try:
        params = qbo.wait_for_callback(args.port, timeout=args.timeout, state=state)
        with httpx.Client(timeout=20) as http:
            tokens = qbo.Tokens(http, env)
            realm = qbo.finish_connect(params, state, tokens, redirect, env)
            name = qbo.QuickBooks(http, tokens, realm).company_name()
    except qbo.QuickBooksError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"connected to {name}; tokens saved in {env.path.name}")
    return 0


def cmd_qbo_check(args) -> int:
    from . import quickbooks as qbo

    try:
        qb = qbo.connect_from_env(qbo.EnvFile(qbo.ENV_PATH))
        name = qb.company_name()
    except qbo.QuickBooksError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"QuickBooks sandbox company: {name}")
    return 0


def cmd_eval(args) -> int:
    from .evals import run_eval
    from .invoices import load_eval_set, load_hard_set

    cases = {"standard": load_eval_set, "hard": load_hard_set, "all": lambda: load_eval_set() + load_hard_set()}[args.set]()
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c.id in wanted]
    r = run_eval(cases, args.model, args.db, Path(args.docs), version=args.version, tier=args.set, model_id=args.model_id, effort=args.effort)
    s = r["summary"]
    er, rd = s["end_result"], s["reading"]
    print(f"{r['model']}, {s['cases']} cases, {r['tier']} tier, version {r['version']}")
    print(f"  end result exact: {er['exact']} of {s['cases']}; failed: {', '.join(er['failed']) or 'none'} (known limits: {', '.join(er['known_limits']) or 'none'})")
    for kind in ("pdf", "photo"):
        print(f"  reading, {kind}: {rd[kind]['fields_correct']} of {rd[kind]['fields']} fields over {rd[kind]['cases']} cases")
    print(f"  account top-1: {s['account']['top1']} of {s['account']['graded']}; safety: {s['safety']['passed']} of {s['safety']['graded']}")
    for code, f in s["flags"].items():
        p = "n/a" if f["precision"] is None else f"{f['precision']:.2f}"
        rc = "n/a" if f["recall"] is None else f"{f['recall']:.2f}"
        print(f"    {code:<18} precision {p}  recall {rc}  (tp {f['tp']}, fp {f['fp']}, fn {f['fn']})")
    cost = "no price" if s["cost"]["usd"] is None else f"${s['cost']['usd']:.4f}"
    print(f"  cost {cost}; {s['time']['seconds']} s ({s['time']['per_invoice_seconds']} s per invoice); errors: {', '.join(s['errors']) or 'none'}")
    return 0


def cmd_run(args) -> int:
    from . import runner

    cases = [load_case(i) for i in args.ids.split(",")] if args.ids else load_all()
    model = runner.make_model(args.model, model_id=args.model_id, effort=args.effort)
    record_dir = Path(args.record) if args.record else None
    records = []
    print(f"{COMPANY_NAME}: {len(cases)} invoices through the workflow, model: {args.model}")
    for case in cases:
        r = runner.run_case(case, model, args.db, args.docs)
        records.append(r)
        if record_dir:
            runner.write_record(r, record_dir)
        o = r["outcome"]
        mark = "ok  " if r["match"]["all"] else "ERR " if "error" in r else "DIFF"
        flags = ", ".join(f["code"] for f in o.get("flags") or []) or "no flags"
        detail = r.get("error") or f"{o.get('status', '?'):<12} {o.get('approver') or '-':<10} {o.get('account') or '-':<5} {flags}"
        print(f"  {mark} {case.id} {case.invoice.vendor_name:<28} {r['seconds']:>6.1f}s  {detail}", flush=True)
    summary = runner.summary_of(records)
    if record_dir:
        (record_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    m = summary["metrics"]
    cost = "no price" if m["cost_usd"] is None else f"${m['cost_usd']:.4f} at API list prices"
    errors = f", {summary['errors']} errors" if summary["errors"] else ""
    print(f"{summary['matched']} of {summary['total']} match their ground truth{errors}; {m['model_calls']} model calls, tokens in {m['input_tokens']:,} + cache write {m['cache_write_tokens']:,} + cache read {m['cache_read_tokens']:,}, out {m['output_tokens']:,}, {cost}, {summary['seconds']:.1f}s")
    return 0 if summary["matched"] == summary["total"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledger-desk", description="Accounts-payable demo: checks, the mock ERP, the app API, recorded runs and the eval.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check", help="check one sample invoice")
    p.add_argument("id", help="01 to 13")
    p.set_defaults(fn=cmd_check)
    sub.add_parser("inbox", help="check all sample invoices").set_defaults(fn=cmd_inbox)
    p = sub.add_parser("render", help="render the PDFs and the photo")
    p.add_argument("--out", default="out")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("db-reset", help="recreate and seed the local database")
    p.add_argument("--name", default="ledger_desk")
    p.set_defaults(fn=cmd_db_reset)
    p = sub.add_parser("erp-serve", help="run the mock ERP locally, with its API docs at /docs")
    p.add_argument("--db", default="ledger_desk")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside a container")
    p.add_argument("--dry-run", action="store_true", help="build the app and list its routes, without serving")
    p.set_defaults(fn=cmd_erp_serve)
    p = sub.add_parser("eval", help="grade a model on the 50-case eval set and write a results file")
    p.add_argument("--model", choices=["scripted", "subscription", "api"], default="scripted")
    p.add_argument("--model-id", default="claude-opus-5-5")
    p.add_argument("--effort", default="low")
    p.add_argument("--version", default="dev")
    p.add_argument("--set", choices=["standard", "hard", "all"], default="standard", help="the 50-case set, the hard tier (10), or both")
    p.add_argument("--ids", default="")
    p.add_argument("--db", default="ledger_desk")
    p.add_argument("--docs", default="out/evals")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("api-serve", help="run the app API locally (sessions, runs, approvals, audit)")
    p.add_argument("--db", default="ledger_desk")
    p.add_argument("--port", type=int, default=8200)
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside a container")
    p.add_argument("--dry-run", action="store_true", help="migrate, build the app and list its routes, without serving")
    p.add_argument("--mirror-quickbooks", action="store_true", help="also mirror each approved bill to the QuickBooks sandbox (needs qbo-connect first)")
    p.set_defaults(fn=cmd_api_serve)
    p = sub.add_parser("qbo-connect", help="connect the Intuit app to the QuickBooks sandbox (OAuth consent, once)")
    p.add_argument("--port", type=int, default=8765, help="must match the redirect URI on the Intuit app")
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--url-file", default="", help="write the consent URL here instead of opening a browser")
    p.set_defaults(fn=cmd_qbo_connect)
    sub.add_parser("qbo-check", help="read the connected QuickBooks sandbox company's name").set_defaults(fn=cmd_qbo_check)
    p = sub.add_parser("run", help="run the workflow on the samples to the approval pause, and record it")
    p.add_argument("--model", choices=["scripted", "subscription", "api"], default="scripted", help="scripted: no model; subscription: claude -p on the Claude login")
    p.add_argument("--model-id", default="claude-opus-5-5")
    p.add_argument("--effort", default="low")
    p.add_argument("--ids", default="", help="comma-separated, e.g. 01,09; default all 13")
    p.add_argument("--db", default="ledger_desk")
    p.add_argument("--docs", default="out", help="where the documents are rendered")
    p.add_argument("--record", default="", help="write one JSON record per invoice and a summary here")
    p.set_defaults(fn=cmd_run)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
