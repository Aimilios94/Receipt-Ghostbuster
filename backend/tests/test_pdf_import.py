"""Bank-statement PDF parsing — the deterministic heuristic + code-side
normalization (the accounting-critical paths). The LLM structuring path isn't
unit-tested here (no network); it feeds the same `normalize_rows`."""
from app.config import Settings
from app.services import pdf_import


MOCK = Settings(llm_provider="mock")


def test_heuristic_signed_amounts_and_balance():
    text = (
        "Movimentos\n"
        "05/10/2026   COMPRA CONTINENTE LISBOA        -11,58     988,42\n"
        "06/10/2026   TRF RECEBIDA SALARIO           2.000,00   2.988,42\n"
    )
    rows = pdf_import.parse_lines_heuristic(text)
    assert len(rows) == 2
    assert rows[0]["txn_date"] == "2026-10-05"
    assert rows[0]["description"] == "COMPRA CONTINENTE LISBOA"
    assert rows[0]["amount"] == -11.58
    assert rows[0]["balance"] == 988.42
    assert rows[1]["amount"] == 2000.00


def test_heuristic_accounting_negatives():
    text = (
        "10/09/2026  LEVANTAMENTO MB            (40,00)\n"
        "11/09/2026  COMPRA LIDL                25,30-\n"
        "12/09/2026  JUROS                      0,12\n"
    )
    rows = pdf_import.parse_lines_heuristic(text)
    assert [r["amount"] for r in rows] == [-40.00, -25.30, 0.12]


def test_heuristic_ignores_non_transaction_lines():
    text = (
        "EXTRATO DE CONTA\n"
        "Saldo inicial 1.000,00\n"            # no leading date -> ignored
        "03/10/2026  PINGO DOCE        -48,24\n"
        "Pagina 1 de 2\n"                      # no amount -> ignored
    )
    rows = pdf_import.parse_lines_heuristic(text)
    assert len(rows) == 1
    assert rows[0]["amount"] == -48.24


def test_parse_statement_text_falls_back_to_heuristic_in_mock():
    text = "01/10/2026  SPOTIFY        -9,99\n"
    rows = pdf_import.parse_statement_text(text, MOCK)
    assert rows[0]["amount"] == -9.99


def test_empty_text_raises_scanned_error():
    import pytest

    with pytest.raises(pdf_import.PdfImportError):
        pdf_import.parse_statement_text("   \n  ", MOCK)


def test_normalize_rows_reparses_llm_output():
    raw = [
        {"date": "05/10/2026", "description": "CONTINENTE", "amount": "-11,58", "balance": "988,42"},
        {"date": "2026-10-06", "description": "SALARIO", "amount": 2000.0, "balance": None},
        {"date": "bad", "description": "junk", "amount": None},  # dropped (no amount)
    ]
    rows = pdf_import.normalize_rows(raw)
    assert len(rows) == 2
    assert rows[0]["txn_date"] == "2026-10-05"
    assert rows[0]["amount"] == -11.58
    assert rows[0]["balance"] == 988.42
    assert rows[1]["amount"] == 2000.00
