from economic_data_exporter.utils.redaction import redact_text, redact_url


def test_fred_key_redaction() -> None:
    key = "abcdefghijklmnopqrstuvwxyz123456"
    assert key not in redact_text(f"api_key={key}")
    url = f"https://api.stlouisfed.org/fred/series?api_key={key}&series_id=GDP"
    redacted = redact_url(url)
    assert key not in redacted
    assert "series_id=GDP" in redacted
