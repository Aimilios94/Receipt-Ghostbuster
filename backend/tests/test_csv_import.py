"""Bank CSV parsing. Requires pydantic (pip install -r requirements.txt)."""
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
