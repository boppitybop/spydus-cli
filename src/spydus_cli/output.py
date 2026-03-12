from typing import Any


def format_records_table(records: list[dict[str, Any]], columns: list[str]) -> str:
    if not records:
        return "No data found."

    headers = columns
    rows: list[list[str]] = []
    widths = [len(header) for header in headers]
    use_index_column = bool(columns) and columns[0] == "#"

    for index, record in enumerate(records, start=1):
        if use_index_column:
            # Preserve explicit row ids when present; otherwise fall back to 1-based numbering.
            values = [str(record.get("#", index))] + [
                str(record.get(column, "")) for column in columns[1:]
            ]
        else:
            values = [str(record.get(column, "")) for column in columns]
        rows.append(values)
        for column_index, value in enumerate(values):
            widths[column_index] = max(widths[column_index], min(len(value), 48))

    def clip(value: str, limit: int = 48) -> str:
        if len(value) <= limit:
            return value
        return value[: limit - 1] + "…"

    rows = [[clip(value) for value in row] for row in rows]

    def render(values: list[str]) -> str:
        return "| " + " | ".join(
            value.ljust(widths[index]) for index, value in enumerate(values)
        ) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    lines = [separator, render(headers), separator]
    lines.extend(render(row) for row in rows)
    lines.append(separator)
    return "\n".join(lines)