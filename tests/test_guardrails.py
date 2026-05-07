"""Tests for the 5-rule Allium guardrail system."""

from src.modules.data.dictionary import DataDictionary, DataDictionaryEntry
from src.modules.data.guardrails import QueryValidator


def _make_dict(*field_names: str) -> DataDictionary:
    return DataDictionary(
        unit_of_observation="transaction",
        fields=[DataDictionaryEntry(name=f, description="", data_type="string", source_table="t") for f in field_names],
    )


# --- Rule 1: No SELECT * ---


def test_select_star_rejected():
    result = QueryValidator.validate_no_select_star("SELECT * FROM transfers")
    assert not result.valid
    assert "SELECT *" in result.rejection_reason


def test_table_star_rejected():
    result = QueryValidator.validate_no_select_star("SELECT t.* FROM transfers t")
    assert not result.valid


def test_explicit_fields_accepted():
    result = QueryValidator.validate_no_select_star("SELECT block_timestamp, from_address, value FROM transfers")
    assert result.valid


# --- Rule 2: Fields in dictionary ---


def test_valid_fields_pass():
    d = _make_dict("block_timestamp", "from_address", "value")
    result = QueryValidator.validate_fields_in_dictionary(["block_timestamp", "from_address"], d)
    assert result.valid


def test_unknown_field_rejected():
    d = _make_dict("block_timestamp", "from_address")
    result = QueryValidator.validate_fields_in_dictionary(["secret_field"], d)
    assert not result.valid
    assert "secret_field" in result.rejection_reason


# --- Rule 3: Time-bound WHERE clause ---


def test_date_bound_passes():
    sql = "SELECT x FROM t WHERE block_timestamp >= '2024-01-01' AND block_timestamp < '2024-02-01'"
    result = QueryValidator.validate_time_bound(sql)
    assert result.valid


def test_no_where_rejected():
    result = QueryValidator.validate_time_bound("SELECT x FROM transfers")
    assert not result.valid


def test_non_time_where_rejected():
    result = QueryValidator.validate_time_bound("SELECT x FROM t WHERE value > 0")
    assert not result.valid


# --- Rule 4: Aggregation level ---


def test_daily_aggregation_passes():
    d = _make_dict("value")
    result = QueryValidator.validate_aggregation_level("daily", "N/A", d)
    assert result.valid


def test_transaction_level_warns_without_justification():
    d = _make_dict("value")
    result = QueryValidator.validate_aggregation_level("transaction", "", d)
    assert result.valid  # warns but doesn't block
    assert len(result.warnings) > 0
