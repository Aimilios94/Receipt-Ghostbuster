"""Bank CSV parsing. Requires pydantic (pip install -r requirements.txt)."""
import pytest

from app.models import ColumnMapping
from app.services import csv_import


def test_signed_amount_default_mapping():
    csv = "date,description,amount,balance\n2026-09-10,STARBUCKS,-4.50,995.50\n"
    rows = csv_import.parse_bank_csv(csv, ColumnMapping())
    assert len(rows) == 1
    assert rows[0]["txn_date"] == "2026-09-10"
    assert rows[0]["amount"] == -4.50
    assert rows[0]["balance"] == 995.50


def test_debit_credit_columns():
    csv = "date,description,debit,credit\n2026-09-11,SALARY,,2000.00\n2026-09-12,RENT,600.00,\n"
    mapping = ColumnMapping(debit="debit", credit="credit", amount="unused")
    rows = csv_import.parse_bank_csv(csv, mapping)
    assert rows[0]["amount"] == 2000.00
    assert rows[1]["amount"] == -600.00


def test_european_number_and_date_format():
    csv = "Datum;Beschreibung;Betrag\n10.09.2026;LIDL;-1.234,56\n"
    # NOTE: default DictReader uses commas; this test documents that a ';' CSV
    # needs its own delimiter handling — kept simple here with a comma file:
    csv = "date,description,amount\n10/09/2026,LIDL,\"-1.234,56\"\n"
    rows = csv_import.parse_bank_csv(csv, ColumnMapping(date_format="%d/%m/%Y"))
    assert rows[0]["txn_date"] == "2026-09-10"
    assert rows[0]["amount"] == -1234.56


def test_autodetects_portuguese_headers_and_semicolon_delimiter():
    # A real-world export: ';' delimiter, Portuguese headers, no mapping supplied.
    csv = (
        "Data;Descrição;Montante;Saldo\n"
        "05/10/2026;COMPRA CONTINENTE;-11,58;988,42\n"
        "08/10/2026;TRF SALARIO;2.000,00;2.988,42\n"
    )
    rows = csv_import.parse_bank_csv(csv, ColumnMapping())
    assert len(rows) == 2
    assert rows[0]["txn_date"] == "2026-10-05"
    assert rows[0]["description"] == "COMPRA CONTINENTE"
    assert rows[0]["amount"] == -11.58
    assert rows[1]["amount"] == 2000.00


def test_missing_date_column_raises_clear_error():
    csv = "reference,amount\nSPOTIFY,-9.99\n"
    with pytest.raises(csv_import.CsvImportError) as exc:
        csv_import.parse_bank_csv(csv, ColumnMapping())
    assert "date column" in str(exc.value)


def test_unparseable_dates_raise_rather_than_storing_blanks():
    # The regression that showed up as "invalid input syntax for type date: ''".
    csv = "date,description,amount\nnot-a-date,SPOTIFY,-9.99\n"
    with pytest.raises(csv_import.CsvImportError):
        csv_import.parse_bank_csv(csv, ColumnMapping())


def test_revolut_export_completed_date_time_and_state_filter():
    # Revolut format: "Completed Date" with a time, quoted European decimals, and a
    # State column with PENDING/REVERTED rows that must be skipped.
    csv = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "Card Payment,Current,5/10/2026 12:33,6/10/2026 5:04,Continente,\"-11,58\",0,EUR,COMPLETED,\"74,27\"\n"
        "Topup,Current,2/10/2026 18:09,2/10/2026 18:09,Google Pay top-up,100,0,EUR,COMPLETED,\"101,83\"\n"
        "Card Payment,Current,17/10/2026 15:32,,Bolt,\"-3,92\",0,EUR,REVERTED,\n"
        "Card Payment,Current,17/10/2026 15:37,,Uber,\"-4,99\",0,EUR,PENDING,\n"
    )
    rows = csv_import.parse_bank_csv(csv, ColumnMapping())
    assert len(rows) == 2  # the REVERTED + PENDING rows are dropped
    assert rows[0]["txn_date"] == "2026-10-06"       # Completed Date, time stripped
    assert rows[0]["description"] == "Continente"
    assert rows[0]["amount"] == -11.58
    assert rows[1]["amount"] == 100.0


def test_rows_without_amount_are_skipped_not_dated_blank():
    csv = "date,description,amount\n2026-10-05,CONTINENTE,-11.58\n2026-10-06,OPENING BALANCE,\n"
    rows = csv_import.parse_bank_csv(csv, ColumnMapping())
    assert len(rows) == 1
    assert rows[0]["amount"] == -11.58
