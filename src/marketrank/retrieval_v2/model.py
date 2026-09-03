"""Small deterministic PIT-safe two-tower model and selection routine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .dataset import RetrievalDataset

MODEL_INPUTS = {
    "customer_indices",
    "recent_article_indices",
    "numeric_features",
    "positive_article_indices",
}
MODEL_INPUT_DTYPES = {
    "customer_indices": torch.int64,
    "recent_article_indices": torch.int64,
    "numeric_features": torch.float32,
    "positive_article_indices": torch.int64,
}


class RetrievalModelError(ValueError):
    """Model tensors or training chronology violate the V2 contract."""


class PitSafeTwoTower(nn.Module):
    """Two-tower model whose customer path has only PIT-safe inputs."""

    def __init__(self, n_customers: int, n_articles: int, dimension: int, numeric_width: int = 4):
        super().__init__()
        if min(n_customers, n_articles, dimension, numeric_width) <= 0:
            raise RetrievalModelError("model dimensions must be positive")
        self.dimension = dimension
        self.customer_embedding = nn.Embedding(n_customers + 1, dimension, padding_idx=0)
        self.article_embedding = nn.Embedding(n_articles + 1, dimension, padding_idx=0)
        self.numeric_projection = nn.Linear(numeric_width, dimension, bias=False)

    def customer(
        self,
        customer_indices: torch.Tensor,
        recent_article_indices: torch.Tensor,
        numeric_features: torch.Tensor,
    ) -> torch.Tensor:
        recent = self.article_embedding(recent_article_indices)
        mask = (recent_article_indices != 0).unsqueeze(-1)
        denominator = mask.sum(dim=1).clamp_min(1)
        recent_mean = (recent * mask).sum(dim=1) / denominator
        vector = (
            self.customer_embedding(customer_indices)
            + recent_mean
            + self.numeric_projection(torch.log1p(numeric_features))
        )
        return F.normalize(vector, dim=-1)

    def article(self, article_indices: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.article_embedding(article_indices), dim=-1)

    def forward(
        self,
        customer_indices: torch.Tensor,
        recent_article_indices: torch.Tensor,
        numeric_features: torch.Tensor,
        positive_article_indices: torch.Tensor,
    ) -> torch.Tensor:
        customers = self.customer(customer_indices, recent_article_indices, numeric_features)
        positives = self.article(positive_article_indices)
        return customers @ positives.T


def validate_model_inputs(inputs: Mapping[str, torch.Tensor]) -> None:
    if set(inputs) != MODEL_INPUTS:
        raise RetrievalModelError(
            f"model inputs mismatch; missing={sorted(MODEL_INPUTS - set(inputs))}, "
            f"extra={sorted(set(inputs) - MODEL_INPUTS)}"
        )
    for name, tensor in inputs.items():
        if not isinstance(tensor, torch.Tensor) or tensor.dtype != MODEL_INPUT_DTYPES[name]:
            raise RetrievalModelError(f"model input {name} has invalid tensor dtype")


@dataclass(frozen=True)
class RetrievalTrainingResult:
    model: PitSafeTwoTower
    training_arguments: Mapping[str, Any]
    metrics: Mapping[str, Any]
    selected_configuration_id: str


def _validate_dataset_pair(fit: RetrievalDataset, select: RetrievalDataset) -> None:
    if fit.split != "retrieval_fit" or select.split != "retrieval_select":
        raise RetrievalModelError(
            "training requires retrieval_fit data and selection requires retrieval_select data"
        )
    if max(fit.scoring_dates) >= min(select.scoring_dates):
        raise RetrievalModelError("retrieval_fit and retrieval_select chronology overlaps or is reordered")


def _recall_at_one(model: PitSafeTwoTower, dataset: RetrievalDataset, n_articles: int) -> float:
    tensors = dataset.tensors()
    with torch.no_grad():
        customer_vectors = model.customer(
            tensors["customer_indices"],
            tensors["recent_article_indices"],
            tensors["numeric_features"],
        )
        article_indices = torch.arange(1, n_articles + 1, dtype=torch.int64)
        article_vectors = model.article(article_indices)
        top = (customer_vectors @ article_vectors.T).argmax(dim=1) + 1
        return float((top == tensors["positive_article_indices"]).float().mean().item())


def train_and_select_retriever(
    fit: RetrievalDataset,
    select: RetrievalDataset,
    *,
    n_customers: int,
    n_articles: int,
    configurations: Iterable[Mapping[str, Any]] | None = None,
    seed: int = 20260903,
) -> RetrievalTrainingResult:
    """Deterministically fit on retrieval_fit and select on retrieval_select."""

    _validate_dataset_pair(fit, select)
    configs = list(configurations or [{"configuration_id": "synthetic_d4", "dimension": 4, "epochs": 8, "lr": 0.05}])
    if not configs:
        raise RetrievalModelError("at least one retriever configuration is required")
    results: list[tuple[float, str, PitSafeTwoTower, dict[str, Any]]] = []
    for config in configs:
        if set(config) != {"configuration_id", "dimension", "epochs", "lr"}:
            raise RetrievalModelError("retriever configuration keys mismatch")
        config_id = config["configuration_id"]
        if not isinstance(config_id, str) or not config_id:
            raise RetrievalModelError("configuration_id must be a non-empty string")
        torch.manual_seed(seed)
        np.random.seed(seed)
        torch.use_deterministic_algorithms(True)
        model = PitSafeTwoTower(n_customers, n_articles, int(config["dimension"]))
        optimizer = torch.optim.SGD(model.parameters(), lr=float(config["lr"]))
        tensors = fit.tensors()
        validate_model_inputs(tensors)
        losses = []
        for _ in range(int(config["epochs"])):
            optimizer.zero_grad()
            logits = model(**tensors)
            labels = torch.arange(len(fit), dtype=torch.int64)
            loss = F.cross_entropy(logits, labels)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().item()))
        recall = _recall_at_one(model, select, n_articles)
        results.append((recall, config_id, model, {"final_fit_loss": losses[-1], "selection_recall_at_1": recall}))
    recall, config_id, model, selected_metrics = sorted(results, key=lambda item: (-item[0], item[1]))[0]
    arguments = {
        "data_mode": "synthetic_fixture",
        "seed": seed,
        "fit_split": "retrieval_fit",
        "selection_split": "retrieval_select",
        "configuration_id": config_id,
        "dimension": model.dimension,
    }
    metrics = {
        **selected_metrics,
        "selection_metric": "retrieval_select_recall_at_1",
        "configurations_evaluated": len(results),
    }
    return RetrievalTrainingResult(model, arguments, metrics, config_id)
