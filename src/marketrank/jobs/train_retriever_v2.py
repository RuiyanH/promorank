"""Create a bounded real V2 retriever from a pinned source export."""
import argparse
import json
from pathlib import Path

import torch

from marketrank.candidate_pipeline.guards import assert_large_output_path
from marketrank.candidate_pipeline.store import HistoricalStore
from marketrank.evidence import revision, sha256
from marketrank.retrieval_v2.bundle import assemble_inference_bundle
from marketrank.retrieval_v2.training import fit_batched


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--scratch-root", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--cohort", type=Path, required=True)
    p.add_argument("--customers", type=int, default=100000)
    p.add_argument("--selection-customers", type=int, default=10000)
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--device", default="cpu")
    a = p.parse_args(argv)
    root = assert_large_output_path(a.root, a.scratch_root)
    store = HistoricalStore(root / "store", threads=a.threads)
    store.initialize(a.source, a.cohort)
    export = root / "retrieval-data"
    if not (export / "manifest.json").exists():
        customers, articles = store.export_retrieval(export, customer_limit=a.customers, selection_customers=a.selection_customers)
    else:
        customers = json.loads((export / "customer_vocabulary.json").read_text())
        articles = json.loads((export / "article_vocabulary.json").read_text())
    store.db.close()
    result = fit_batched(export / "fit.parquet", export / "select.parquet", n_customers=len(customers),
                         n_articles=len(articles), output=root / "training", epochs=a.epochs,
                         threads=a.threads, device=a.device)
    ids = sorted(articles)
    with torch.no_grad():
        vectors = result.model.article(torch.tensor([articles[x] for x in ids])).numpy()
    bundle = assemble_inference_bundle(root / "bundle", bundle_id="v2_pit_safe_real_20260916",
        data_mode="non_release_pilot", training_result=result, customer_vocabulary=customers,
        article_vocabulary=articles, article_ids=ids, article_vectors=vectors, recent_k=10,
        code_revision=revision(), dependency_lock_sha256=sha256(Path("uv.lock")))
    print({"bundle_complete": True, "manifest_sha256": sha256(bundle / "manifest.json")}, flush=True)


if __name__ == "__main__":
    main()
