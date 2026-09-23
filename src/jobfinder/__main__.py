#!/usr/bin/env python3
"""Practice Job Finder launcher."""
import sys
from jobfinder.application.compensation import enrich_missing_compensation
from jobfinder.application.service import rescore_all
from jobfinder.infrastructure.storage import init_storage
from jobfinder.presentation.webapp import serve

def main() -> None:
    init_storage()
    rescore_all()
    enrich_missing_compensation()
    serve(open_browser="--no-browser" not in sys.argv)

if __name__ == "__main__": main()
