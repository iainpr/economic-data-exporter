from economic_data_exporter.utils.validation import split_series_ids


def test_split_series_ids_accepts_multiple_delimiters_and_deduplicates() -> None:
    assert split_series_ids("FSR2018JUNEC10AS2, bcpien\nFXUSDCAD; FXUSDCAD") == [
        "FSR2018JUNEC10AS2",
        "bcpien",
        "FXUSDCAD",
    ]
