import argparse
from pathlib import Path
from marketrank.jobs.train_ranker import load_frames
from marketrank.ranking.model import fit_calibrator


def main(argv=None):
    p = argparse.ArgumentParser(description="Fit offline V2 calibration on unsampled val_calib only")
    p.add_argument("--frames", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    table, _, _ = load_frames(a.frames, "val_calib")
    fit_calibrator(a.model, table, a.out)


if __name__ == "__main__":
    main()
