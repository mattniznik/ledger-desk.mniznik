"""The CLI: run the checks on one sample invoice, or on the whole inbox, with no model."""

from ledger_desk.cli import main


def test_check_one_invoice_prints_its_flags(capsys):
    assert main(["check", "03"]) == 0
    out = capsys.readouterr().out
    assert "PKG-20817" in out
    assert "exception" in out
    assert "PRICE_VARIANCE" in out and "$200.00" in out
    assert "approver: clerk" in out


def test_inbox_runs_all_thirteen_and_compares_with_the_ground_truth(capsys):
    assert main(["inbox"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") >= 13
    assert "13 of 13 match their ground truth" in out


def test_an_unknown_invoice_id_is_a_clear_error(capsys):
    assert main(["check", "99"]) == 2
    assert "no sample invoice 99" in capsys.readouterr().err


def test_erp_serve_dry_run_builds_the_app_and_lists_its_routes(erp_db, capsys):
    assert main(["erp-serve", "--db", erp_db, "--dry-run"]) == 0
    out = capsys.readouterr().out
    for route in ("POST /journal-entries", "GET /purchase-orders/{po}", "GET /bills", "/docs"):
        assert route in out


def test_render_writes_every_document(tmp_path, capsys):
    assert main(["render", "--out", str(tmp_path)]) == 0
    files = sorted(p.name for p in tmp_path.iterdir())
    assert len(files) == 13
    assert "02-green-coffee-photo-partial.jpg" in files
