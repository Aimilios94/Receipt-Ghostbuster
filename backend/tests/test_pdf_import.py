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


# --- Revolut statements read in code (synthetic text in the real layout) -------------

REVOLUT_EN = """EUR Statement
Revolut Bank UAB
Page 1 of 2
Balance summary
Product Opening balance Money out Money in Closing balance
Account (Current Account) €1.83 €559.90 €1,110.00 €551.93
Total €1.83 €559.90 €1,110.00 €551.93
Date Description Money out Money in Balance
2 Oct 2026 Google Pay top-up by *1111 €1,100.00 €1,101.83
From: *2222
3 Oct 2026 Shop One €15.98 €1,085.85
To: Shop One, Lisboa, PRT
Card: 111111******2222
4 Oct 2026 To Sam Sample €500.00 €585.85
Reference: Sent from Revolut
To: Sam Sample, PT50000000000000000000000
EUR Statement
Page 2 of 2
Date Description Money out Money in Balance
5 Oct 2026 Transfer to ALEX EXAMPLE €2.72 €583.13
Reference: To Alex E
To: ALEX EXAMPLE
6 Oct 2026 Transfer from ALEX EXAMPLE €10.00 €593.13
Reference: From Alex E
From: ALEX EXAMPLE
7 Oct 2026 Revolut Ltd €41.20 €551.93
Reference: To Someone
To: SOMEONE
Reverted from 1 October 2026 to 31 October 2026
Start date Description Money out Money in
17 Oct 2026 Ride €3.92
To: ride.example
Card: 111111******2222
"""

REVOLUT_EL = """EUR Κίνηση λογαριασμού
Revolut Bank UAB
Σελίδα 1 από 2
Σύνοψη ισολογισμού
Προϊόν Αρχικό υπόλοιπο Εκροές Εισροές Υπόλοιπο κλεισίματος
Λογαριασμός (τρεχούμενος λογαριασμός) 1,83€ 559,90€ 1.110,00€ 551,93€
Σύνολο 1,83€ 559,90€ 1.110,00€ 551,93€
Ημερομηνία Περιγραφή Εκροές Εισροές Υπόλοιπο
2 Οκτ 2026 Προσθήκη Google Pay από *1111 1.100,00€ 1.101,83€
Από: *2222
3 Οκτ 2026 Shop One 15,98€ 1.085,85€
Προς: Shop One, Lisboa, PRT
Κάρτα: 111111******2222
4 Οκτ 2026 To Sam Sample 500,00€ 585,85€
Αναφορά: Sent from Revolut
Προς: Sam Sample, PT50000000000000000000000
EUR Κίνηση λογαριασμού
Σελίδα 2 από 2
Ημερομηνία Περιγραφή Εκροές Εισροές Υπόλοιπο
5 Οκτ 2026 Μεταφορά προς ALEX EXAMPLE 2,72€ 583,13€
Αναφορά: To Alex E
Προς: ALEX EXAMPLE
6 Οκτ 2026 Μεταφορά από ALEX EXAMPLE 10,00€ 593,13€
Αναφορά: From Alex E
Από: ALEX EXAMPLE
7 Οκτ 2026 Revolut Ltd 41,20€ 551,93€
Αναφορά: To Someone
Προς: SOMEONE
Αντιστράφηκε από 1 Οκτωβρίου 2026 προς 31 Οκτωβρίου 2026
Ημερομηνία έναρξης Περιγραφή Εκροές Εισροές
17 Οκτ 2026 Ride 3,92€
Προς: ride.example
Κάρτα: 111111******2222
"""


def _core(rows):
    return [(r["txn_date"], r["description"], r["amount"], r["balance"], r["raw"].get("Type")) for r in rows]


def test_revolut_english_rows_signs_types_and_thousands():
    assert _core(pdf_import.parse_revolut_statement(REVOLUT_EN)) == [
        ("2026-10-02", "Google Pay top-up by *1111", 1100.0, 1101.83, "Topup"),
        ("2026-10-03", "Shop One", -15.98, 1085.85, "Card Payment"),
        ("2026-10-04", "To Sam Sample", -500.0, 585.85, "Transfer"),
        ("2026-10-05", "Transfer to ALEX EXAMPLE", -2.72, 583.13, "Transfer"),
        ("2026-10-06", "Transfer from ALEX EXAMPLE", 10.0, 593.13, "Transfer"),
        ("2026-10-07", "Revolut Ltd", -41.2, 551.93, "Transfer"),
    ]


def test_revolut_greek_reads_the_same_as_english():
    assert _core(pdf_import.parse_revolut_statement(REVOLUT_EL)) == _core(
        pdf_import.parse_revolut_statement(REVOLUT_EN)
    )


def test_revolut_skips_reverted_rows_and_keeps_ibans_out_of_raw():
    for text in (REVOLUT_EN, REVOLUT_EL):
        rows = pdf_import.parse_revolut_statement(text)
        assert not any("Ride" in r["description"] for r in rows)
        assert "PT50" not in str(rows)


def test_revolut_that_does_not_reconcile_is_rejected():
    assert pdf_import.parse_revolut_statement(REVOLUT_EN.replace("€559.90", "€559.91")) == []
    assert pdf_import.parse_revolut_statement(REVOLUT_EN.replace("€15.98", "€15.00")) == []
    assert pdf_import.parse_revolut_statement(REVOLUT_EN.replace("\nTotal ", "\nSummary ")) == []


def test_other_statements_are_not_read_as_revolut():
    assert pdf_import.parse_revolut_statement("Some Bank\n05/10/2026 SHOP -11,58 988,42\n") == []


def test_unknown_detail_labels_leave_the_type_unset():
    text = REVOLUT_EN.replace("Card: ", "Karte: ")
    rows = pdf_import.parse_revolut_statement(text)
    assert rows[1]["description"] == "Shop One" and "Type" not in rows[1]["raw"]


def test_revolut_needs_no_model(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("the model must not be called for a statement that reconciles")

    monkeypatch.setattr(pdf_import, "_structure_with_llm", fail)
    rows = pdf_import.parse_statement_text(REVOLUT_EL, Settings(llm_provider="openai", openai_api_key="k"))
    assert len(rows) == 6


def test_transfers_are_not_purchases_in_either_language():
    from app.services.reconciliation import is_reconcilable

    for text in (REVOLUT_EN, REVOLUT_EL):
        rows = pdf_import.parse_revolut_statement(text)
        assert [r["description"] for r in rows if is_reconcilable(r)] == ["Shop One"]
    assert not is_reconcilable({"amount": -2.0, "description": "Μεταφορά προς Someone"})


def test_breakdown_reads_counterparties_from_either_language():
    from app.services import breakdown

    for text in (REVOLUT_EN, REVOLUT_EL):
        tp = breakdown.third_party_breakdown(pdf_import.parse_revolut_statement(text))
        assert {r["name"] for r in tp["sent"]} == {"Sam Sample", "ALEX EXAMPLE", "SOMEONE"}
        assert tp["total_sent"] == 543.92 and tp["total_received"] == 10.0


def test_reupload_in_another_language_adds_nothing():
    from app.services import statements

    english = pdf_import.parse_revolut_statement(REVOLUT_EN)
    greek = pdf_import.parse_revolut_statement(REVOLUT_EL)
    greek[0]["description"] = "described differently"
    new, skipped = statements.filter_new_transactions(greek, english)
    assert new == [] and skipped == 6


class _FakeOpenAI:
    calls = []

    def __init__(self, **kwargs):
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        _FakeOpenAI.calls.append(kwargs)
        message = type("M", (), {"content": '{"transactions": []}'})
        return type("R", (), {"choices": [type("C", (), {"message": message})]})


def _llm_call(monkeypatch, model):
    import openai

    _FakeOpenAI.calls = []
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    settings = Settings(llm_provider="openai", openai_api_key="k", openai_model=model)
    pdf_import._structure_with_llm("Some Bank statement", settings)
    return _FakeOpenAI.calls[0]


def test_reasoning_model_gets_max_completion_tokens(monkeypatch):
    call = _llm_call(monkeypatch, "gpt-5-mini")
    assert "max_tokens" not in call and call["max_completion_tokens"] >= 8000


def test_older_model_keeps_max_tokens(monkeypatch):
    call = _llm_call(monkeypatch, "gpt-4o")
    assert "max_completion_tokens" not in call and call["max_tokens"] == 4096


def test_money_with_either_decimal_separator():
    from app.services.csv_import import _parse_money

    assert _parse_money("€1,010.00") == 1010.0
    assert _parse_money("1.010,00€") == 1010.0
    assert _parse_money("100,00€") == 100.0
    assert _parse_money("-1,234.56") == -1234.56


def test_revolut_transfers_keep_the_named_person_without_the_iban():
    for text in (REVOLUT_EN, REVOLUT_EL):
        rows = pdf_import.parse_revolut_statement(text)
        names = [r["raw"].get("Counterparty") for r in rows]
        assert names == [None, None, "Sam Sample", "ALEX EXAMPLE", "ALEX EXAMPLE", "SOMEONE"]
        assert "PT50" not in str(rows)
