"""Bounded-memory real-data training for the V2 PIT-safe tower."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import torch
from torch.nn import functional as F

from marketrank.evidence import write_json
from .model import PitSafeTwoTower, RetrievalTrainingResult


def load_tensors(path: Path) -> dict[str, torch.Tensor]:
    table = pq.read_table(path)
    return {
        "customer_indices": torch.from_numpy(np.array(table["customer_index"], dtype=np.int64)),
        "recent_article_indices": torch.from_numpy(np.asarray(table["recent"].to_pylist(), dtype=np.int64)),
        "numeric_features": torch.from_numpy(np.asarray(table["numeric"].to_pylist(), dtype=np.float32)),
        "positive_article_indices": torch.from_numpy(np.array(table["article_index"], dtype=np.int64)),
    }


def fit_batched(fit_path: Path, select_path: Path, *, n_customers: int, n_articles: int,
                output: Path, dimension: int = 64, epochs: int = 5, batch_size: int = 1024,
                lr: float = .002, threads: int = 4, device: str = "cpu", seed: int = 20260903) -> RetrievalTrainingResult:
    if epochs <= 0 or batch_size < 2 or not np.isfinite(lr) or lr <= 0:
        raise ValueError("positive epochs/rate and batch_size >=2 are required")
    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    fit, select = load_tensors(fit_path), load_tensors(select_path)
    if not len(fit["customer_indices"]) or not len(select["customer_indices"]):
        raise ValueError("both retrieval splits must be nonempty")
    for tensors in (fit, select):
        if max(tensors["positive_article_indices"]).item() > n_articles:
            raise ValueError("article index exceeds catalog")
        if not torch.isfinite(tensors["numeric_features"]).all():
            raise ValueError("nonfinite customer inputs")
    model = PitSafeTwoTower(n_customers, n_articles, dimension).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    counts = torch.bincount(fit["positive_article_indices"], minlength=n_articles + 1).float().clamp_min(1)
    logq = torch.log(counts / counts.sum()).to(device)
    best, best_state, history = -1., None, []
    generator = torch.Generator().manual_seed(seed)
    output.mkdir(parents=True, exist_ok=True)
    for epoch in range(epochs):
        order = torch.randperm(len(fit["customer_indices"]), generator=generator)
        loss_sum, rows_seen = 0., 0
        model.train()
        for positions in order.split(batch_size):
            batch = {name: tensor[positions].to(device) for name, tensor in fit.items()}
            logits = model(**batch) / .07 - logq[batch["positive_article_indices"]][None, :]
            # A repeated item within the batch is another positive, not a false
            # negative. Mask duplicate off-diagonal copies of that target.
            same = batch["positive_article_indices"][:, None] == batch["positive_article_indices"][None, :]
            same.fill_diagonal_(False)
            logits = logits.masked_fill(same, -torch.inf)
            loss = F.cross_entropy(logits, torch.arange(len(positions), device=device))
            if not torch.isfinite(loss):
                raise ValueError("retrieval training produced nonfinite loss")
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            loss_sum += float(loss.detach()) * len(positions)
            rows_seen += len(positions)
        model.eval()
        hits, total = 0, 0
        with torch.no_grad():
            catalog = model.article(torch.arange(1, n_articles + 1, device=device))
            for start in range(0, len(select["customer_indices"]), 256):
                batch = {name: value[start:start + 256].to(device) for name, value in select.items()}
                queries = model.customer(batch["customer_indices"], batch["recent_article_indices"], batch["numeric_features"])
                # Selection catalog is fixed at the retrieval fit boundary.
                ranking = torch.topk(queries @ catalog.T, min(100, n_articles), dim=1).indices + 1
                hits += int((ranking == batch["positive_article_indices"][:, None]).any(dim=1).sum())
                total += len(queries)
        recall = hits / total
        history.append({"epoch": epoch + 1, "fit_loss": loss_sum / rows_seen, "selection_recall_at_100": recall})
        if recall > best:
            best = recall
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        write_json(output / "training-progress.json", {"history": history})
        print(history[-1], flush=True)
    model = model.cpu()
    model.load_state_dict(best_state)
    return RetrievalTrainingResult(model, {
        "data_mode": "non_release_pilot", "fit_split": "retrieval_fit", "selection_split": "retrieval_select",
        "configuration_id": "batched_d64", "dimension": dimension, "epochs": epochs,
        "batch_size": batch_size, "learning_rate": lr, "seed": seed, "temperature": .07,
        "sampled_softmax_logq": True, "duplicate_positive_mask": True,
    }, {"history": history, "selection_recall_at_100": best, "fit_rows": rows_seen,
        "selection_rows": len(select["customer_indices"]), "selection_catalog": "observed_on_or_before_retrieval_fit_end"}, "batched_d64")
