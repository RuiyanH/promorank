"""Append frozen final-period data to an existing restricted store."""
import argparse
from pathlib import Path

from marketrank.candidate_pipeline.guards import assert_large_output_path
from marketrank.candidate_pipeline.store import HistoricalStore
from marketrank.ranking.freeze import validate_freeze


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--scratch-root",type=Path,required=True)
    args=parser.parse_args(argv)
    root=assert_large_output_path(args.root,args.scratch_root)
    source=assert_large_output_path(args.source,args.scratch_root)
    freeze=root/"evaluation-freeze.json"
    validate_freeze(freeze)
    if not (root/"store/restricted.duckdb").is_file():
        raise ValueError("source extension requires an existing initialized store")
    store=HistoricalStore(root/"store")
    try:
        store.extend_source(source,freeze)
        print({"source_extension":"complete","transactions":store.db.execute("SELECT count(*) FROM tx").fetchone()[0]},flush=True)
    finally:
        store.db.close()


if __name__=="__main__":main()
