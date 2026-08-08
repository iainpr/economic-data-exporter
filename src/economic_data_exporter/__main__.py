"""Application entry point."""

from economic_data_exporter.gui.main_window import run_gui
from economic_data_exporter.utils.logging import configure_logging


def main() -> None:
    configure_logging()
    raise SystemExit(run_gui())


if __name__ == "__main__":
    main()
