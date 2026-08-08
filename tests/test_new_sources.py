import pandas as pd

from economic_data_exporter.sources.sdmx import SDMXSource
from economic_data_exporter.sources.misc import (
    FAOSTATSource,
    IMFSource,
    ILOStatSource,
    StatisticsCanadaSource,
)

class FakeClient:
    def __init__(self, responses): self.responses=responses
    def get(self, url, **kwargs): return self.responses[url]
    def post_json(self, url, **kwargs): return self.responses[url]

class Resp:
    def __init__(self, text, headers=None): self.content=text.encode(); self.headers=headers or {"Content-Type":"application/json"}; self.status_code=200; self.retrieved_at=pd.Timestamp.utcnow().to_pydatetime(); self.from_cache=False
    @property
    def text(self): return self.content.decode()
    def json(self): import json; return json.loads(self.text)

def test_statcan_vector_metadata_and_fetch():
    info='[{"status":"SUCCESS","object":{"vectorId":123,"SeriesTitleEn":"Test series","frequencyCode":9}}]'
    data='{"status":"SUCCESS","object":[{"vectorId":123,"vectorDataPoint":[{"refPer":"2020-01-01","value":10},{"refPer":"2021-01-01","value":11}]}]}'
    base="https://www150.statcan.gc.ca/t1/wds/rest"
    c=FakeClient({f"{base}/getSeriesInfoFromVector":Resp(info),f"{base}/getDataFromVectorByReferencePeriodRange":Resp(data)})
    src=StatisticsCanadaSource(c)
    assert src.search("V123")[0].name == "Test series"
    result=src.fetch(type("R",(),{"series_id":"V123","start_date":pd.Timestamp("2020-01-01").date(),"end_date":pd.Timestamp("2021-12-31").date(),"geography":"","frequency":"","options":{}})(), cancel=lambda:None)
    assert len(result.data)==2

def test_imf_search():
    base="https://www.imf.org/external/datamapper/api/v2"
    c=FakeClient({f"{base}/indicators":Resp('{"indicators":{"NGDP_RPCH":{"label":"Real GDP growth"}}}')})
    assert IMFSource(c).search("GDP")[0].series_id == "NGDP_RPCH"

def test_ilostat_csv_normalization():
    base="https://rplumber.ilo.org/data/indicator/"
    csv='ref_area,ref_area.label,indicator,indicator.label,time,obs_value\nCAN,Canada,UNE,Unemployment,2020,8.1\nCAN,Canada,UNE,Unemployment,2021,7.5\n'
    c=FakeClient({base:Resp(csv,{"Content-Type":"text/csv"})})
    src=ILOStatSource(c)
    result=src.fetch(type("R",(),{"series_id":"UNE","start_date":pd.Timestamp("2020-01-01").date(),"end_date":pd.Timestamp("2021-12-31").date(),"geography":"CAN","frequency":"","options":{}})(), cancel=lambda:None)
    assert result.data["value"].tolist()==[8.1,7.5]

def test_sdmx_requires_flow_and_key():
    class X(SDMXSource):
        name="X"; base_url="https://example.org/rest"; hosts=("example.org",); source_url="https://example.org"; attribution="X"; license_text="X"
    c=FakeClient({})
    try: X(c).fetch(type("R",(),{"series_id":"FLOW","start_date":pd.Timestamp("2020-01-01").date(),"end_date":pd.Timestamp("2021-01-01").date(),"geography":"","frequency":"","options":{}})(), cancel=lambda:None)
    except ValueError as exc: assert "DATAFLOW|KEY" in str(exc)
    else: raise AssertionError("Expected validation error")

def test_faostat_is_explicitly_limited_without_verified_auth_flow():
    src=FAOSTATSource(FakeClient({}))
    try: src.fetch(type("R",(),{"series_id":"QCL","start_date":pd.Timestamp("2020-01-01").date(),"end_date":pd.Timestamp("2021-01-01").date(),"geography":"","frequency":"","options":{}})(), cancel=lambda:None)
    except Exception as exc: assert "intentionally not enabled" in str(exc)
    else: raise AssertionError("Expected explicit FAOSTAT limitation")
