#!/usr/bin/env python3
"""The BatchIQ demo on a cloud machine: setup, up, stop, start, down, status, ssh. See infra/README.md.

    infra/bin/cloud.py setup      once per account
    infra/bin/cloud.py up         the demo on one cloud machine, then: ssh batchiq and open http://localhost:8080
    infra/bin/cloud.py down       delete it all
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

from batchiq_cloud.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
