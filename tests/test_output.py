from spydus_cli.output import format_records_table


def test_format_records_table_uses_record_value_for_first_non_index_column():
    table = format_records_table(
        [
            {
                "title": "Example Book",
                "result": "Renewed",
                "reason": "",
            }
        ],
        ["title", "result", "reason"],
    )

    assert "| Example Book | Renewed |" in table
    assert "| 1            | Renewed |" not in table


def test_format_records_table_autonumbers_when_hash_column_requested():
    table = format_records_table(
        [
            {"title": "Book A", "status": "Queued"},
            {"title": "Book B", "status": "Ready"},
        ],
        ["#", "title", "status"],
    )

    assert "| 1 | Book A | Queued |" in table
    assert "| 2 | Book B | Ready  |" in table
