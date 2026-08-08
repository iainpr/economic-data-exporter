"""Source adapter registry."""

from __future__ import annotations

from economic_data_exporter.network import HttpClient
from economic_data_exporter.sources.bank_of_canada import BankOfCanadaSource
from economic_data_exporter.sources.base import DataSource
from economic_data_exporter.sources.fred import FredSource
from economic_data_exporter.sources.misc import (
    BISSource,
    FAOSTATSource,
    ILOStatSource,
    IMFSource,
    OECDSource,
    StatisticsCanadaSource,
)
from economic_data_exporter.sources.owid import OwidSource
from economic_data_exporter.sources.penn_world_table import PennWorldTableSource
from economic_data_exporter.sources.world_bank import WorldBankSource


def build_sources(client: HttpClient) -> dict[str, DataSource]:
    adapters: list[DataSource] = [
        BankOfCanadaSource(client),
        FredSource(client),
        WorldBankSource(client),
        OwidSource(client),
        PennWorldTableSource(client),
        StatisticsCanadaSource(client),
        OECDSource(client),
        IMFSource(client),
        BISSource(client),
        ILOStatSource(client),
        FAOSTATSource(client),
    ]
    return {adapter.name: adapter for adapter in adapters}
