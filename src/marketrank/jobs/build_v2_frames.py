"""Execute resume-checked daily candidates and ranker frames."""
import argparse
import datetime as dt
import json
import resource
import shutil
import time
from pathlib import Path

from marketrank.candidate_pipeline.analytical import DailyBuilder
from marketrank.candidate_pipeline.guards import assert_large_output_path
from marketrank.candidate_pipeline.store import HistoricalStore
from marketrank.evidence import write_json


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--scratch-root", type=Path, required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--split", choices=["ranker_fit", "val_tune", "val_calib", "test", "holdout"])
    p.add_argument("--spine-type", choices=["active_day", "replay_day"], default="active_day")
    p.add_argument("--pilot", action="store_true")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--memory", default="4GB")
    a = p.parse_args(argv)
    root = assert_large_output_path(a.root, a.scratch_root)
    if a.pilot and (a.start, a.end, a.split) != ("2020-07-15", "2020-07-21", "ranker_fit"):
        raise ValueError("pilot must match the complete frozen seven-day window")
    free = shutil.disk_usage(root).free
    if free < 64 * 1024**3:
        raise ValueError("bounded local pilot requires at least 64 GiB free")
    store = HistoricalStore(root / "store", threads=a.threads, memory=a.memory)
    builder = DailyBuilder(store, root / "bundle")
    name = "pilot" if a.pilot else a.split if a.spine_type == "active_day" else "replay"
    started, results = time.monotonic(), []
    day, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    while day <= end:
        results.append(builder.build(day.isoformat(), spine_type=a.spine_type,
            output=root / name / day.isoformat(), split=a.split, pilot=a.pilot))
        size = sum(result["compressed_bytes"] for result in results)
        if a.pilot and size > 20 * 1024**3:
            raise ValueError("pilot exceeded 20 GiB persistent output ceiling")
        day += dt.timedelta(days=1)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write_json(root / f"{name}-run.json", {"status": "complete", "start": a.start, "end": a.end,
        "partitions": len(results), "groups": sum(r["groups"] for r in results),
        "candidate_rows": sum(r["candidate_rows"] for r in results),
        "compressed_bytes": sum(r["compressed_bytes"] for r in results),
        "wall_seconds": time.monotonic()-started, "peak_rss_platform_units": peak,
        "free_bytes_at_start": free, "data_mode": "non_release_pilot" if a.pilot else "historical_offline"})
    store.db.close()


if __name__ == "__main__":
    main()
