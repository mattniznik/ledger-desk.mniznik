"""Reading an invoice with a model (fake here), then checking what it read.

The model returns structured fields, each key field with the text it was read from. Code checks
that text is really in the PDF's text layer and really contains the value, so a misread or an
invented number cannot pass quietly. A refusal or an unreadable reply goes to manual entry: the
person types the fields, nothing is guessed."""

from pathlib import Path

import pytest

from fakes import ScriptedModel, perfect_reading, read_reply
from ledger_desk.documents import render_case
from ledger_desk.invoices import load_case
from ledger_desk.model import ModelReply
from ledger_desk.reading import read_invoice


@pytest.fixture(scope="module")
def docs(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("docs")
    for case_id in ("02", "03"):
        render_case(load_case(case_id), out)
    return out


def doc(docs, case_id):
    case = load_case(case_id)
    return case, next(docs.glob(f"{case.slug}.*"))


def test_a_perfect_reading_passes_every_source_check(docs):
    case, path = doc(docs, "03")
    result = read_invoice(path, ScriptedModel(read_reply(perfect_reading(case))))
    assert result.status == "read"
    assert result.invoice.total == case.invoice.total and result.invoice.number == "PKG-20817"
    assert set(result.source_checks.values()) == {"ok"}


def test_a_value_that_is_not_in_the_document_fails_its_source_check(docs):
    case, path = doc(docs, "03")
    invented = perfect_reading(case, number="PKG-99999")
    invented["sources"]["number"] = "PKG-99999"
    result = read_invoice(path, ScriptedModel(read_reply(invented)))
    assert result.source_checks["number"] == "missing"


def test_a_source_that_does_not_contain_the_value_fails(docs):
    case, path = doc(docs, "03")
    misread = perfect_reading(case, total="2010.00")  # the PDF says $2,100.00
    result = read_invoice(path, ScriptedModel(read_reply(misread)))
    assert result.source_checks["total"] == "missing"


def test_a_photo_has_no_text_layer_so_its_sources_are_marked_not_checked(docs):
    case, path = doc(docs, "02")
    result = read_invoice(path, ScriptedModel(read_reply(perfect_reading(case))))
    assert result.status == "read"
    assert set(result.source_checks.values()) == {"not_checked"}


def test_a_refusal_goes_to_manual_entry(docs):
    _, path = doc(docs, "03")
    result = read_invoice(path, ScriptedModel(ModelReply(stop_reason="refusal", model="claude-opus-5-5")))
    assert (result.status, result.reason) == ("manual_entry", "the model declined to read this document")
    assert result.invoice is None


def test_an_unreadable_reply_goes_to_manual_entry(docs):
    _, path = doc(docs, "03")
    result = read_invoice(path, ScriptedModel(ModelReply(stop_reason="end_turn", text="Sure! The invoice total is $2,100.")))
    assert result.status == "manual_entry"
    assert "not valid" in result.reason


def test_the_request_sends_the_document_and_the_schema(docs):
    case, path = doc(docs, "03")
    model = ScriptedModel(read_reply(perfect_reading(case)))
    read_invoice(path, model)
    request = model.requests[0]
    assert request["task"] == "read"
    assert request["document"]["media_type"] == "application/pdf" and request["document"]["data"]
    assert "sources" in request["schema"]["properties"]
