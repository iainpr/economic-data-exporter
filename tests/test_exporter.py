from pathlib import Path

from openpyxl import load_workbook

from economic_data_exporter.models import FailureRecord
from economic_data_exporter.services.exporter import export_workbook, safe_sheet_name


def test_excel_creation_readme_data_failures(tmp_path: Path, sample_result) -> None:
    output = tmp_path / "result.xlsx"
    failure = FailureRecord("FRED", "BAD", "", "ParsingError", "Malformed")
    path = export_workbook(output, [sample_result], [failure])
    workbook = load_workbook(path, read_only=True, data_only=False)
    assert {"README", "Data", "Failures"}.issubset(workbook.sheetnames)
    assert workbook["Data"].max_row == 4
    assert workbook["README"].max_row > 5
    workbook.close()


def test_safe_sheet_names() -> None:
    used: set[str] = set()
    first = safe_sheet_name("a/b:c*?[]" * 5, used)
    second = safe_sheet_name("a/b:c*?[]" * 5, used)
    assert len(first) <= 31
    assert first != second
