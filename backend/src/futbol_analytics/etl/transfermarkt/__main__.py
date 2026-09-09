"""Permite `python -m futbol_analytics.etl.transfermarkt`."""

import sys

from futbol_analytics.etl.transfermarkt.run import main

if __name__ == "__main__":
    sys.exit(main())
