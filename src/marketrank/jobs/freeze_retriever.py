"""Freeze an accepted pilot retriever for offline frames without retraining."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from marketrank.evidence import revision, sha256
from marketrank.retrieval.inference_bundle import load_inference_bundle
from marketrank.retrieval_v2.bundle import assemble_inference_bundle
from marketrank.retrieval_v2.model import PitSafeTwoTower, RetrievalTrainingResult


def run(source: Path, output: Path, export: Path):
    bundle=load_inference_bundle(source)
    if bundle.data_mode!="non_release_pilot":
        raise ValueError("only a verified real pilot can be frozen for full offline execution")
    export_manifest=json.loads((export/"manifest.json").read_text())
    for name,key in (("fit.parquet","fit_sha256"),("select.parquet","select_sha256")):
        if sha256(export/name)!=export_manifest[key]:raise ValueError("retrieval input checksum mismatch")
    customers=json.loads(bundle.artifact_path("customer_vocabulary").read_text())
    articles=json.loads(bundle.artifact_path("article_vocabulary").read_text())
    model=PitSafeTwoTower(max(customers.values()),max(articles.values()),bundle.dimension)
    with np.load(bundle.artifact_path("model_weights"),allow_pickle=False) as arrays:
        model.load_state_dict({k:torch.from_numpy(arrays[k].copy()) for k in arrays.files})
    args=json.loads(bundle.artifact_path("training_arguments").read_text())
    args.update({"pilot_bundle_manifest_sha256":sha256(source/"manifest.json"),
        "input_manifest_sha256":sha256(export/"manifest.json"),"population":export_manifest["population_rule"],
        "customer_limit":export_manifest["customer_limit"],"selection_customers":export_manifest["selection_customers"]})
    metrics=json.loads(bundle.artifact_path("metrics").read_text())
    result=RetrievalTrainingResult(model,args,metrics,args["configuration_id"])
    with np.load(bundle.artifact_path("catalog_arrays"),allow_pickle=False) as arrays:
        assemble_inference_bundle(output,bundle_id="v2_pit_safe_frozen_20260916",data_mode="historical_offline",
            training_result=result,customer_vocabulary=customers,article_vocabulary=articles,
            article_ids=arrays["article_ids"].tolist(),article_vectors=arrays["article_vectors"].copy(),recent_k=10,
            code_revision=revision(),dependency_lock_sha256=sha256(Path("uv.lock")))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--export",type=Path,required=True)
    a=p.parse_args();run(a.source,a.out,a.export)
