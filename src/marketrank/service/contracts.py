"""Strict transport models shared with generated OpenAPI."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False,strict=True)


class SourceEvidence(StrictModel):
    source: Literal["repurchase","category_pop","global_pop","covisit","ann"]
    display_name: Literal["repurchase","category_pop","global_pop","covisit","embedding_retrieval"]
    source_rank: int=Field(ge=1,le=50)


class ArticleMetadata(StrictModel):
    product_type_name: str|None=Field(max_length=100)
    metadata_status: Literal["static_snapshot_attribute","partial_static_snapshot"]


class Recommendation(StrictModel):
    position:int=Field(ge=1,le=12)
    article_id:str=Field(pattern=r"^[0-9]{10}$")
    ordering_score:float
    source_evidence:list[SourceEvidence]=Field(min_length=1,max_length=5)
    article_metadata:ArticleMetadata


class RecommendationsResponse(StrictModel):
    schema_version:Literal["workbench-api.v2"]
    release_id:str=Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    as_of:Literal["2020-09-09","2020-09-16"]
    ranking_mode:Literal["trained_ranker"]
    score_semantics:Literal["ordering_only"]
    warning:str=Field(max_length=512)
    model_available_after:Literal["2020-08-25"]
    calibrator_available_after:Literal["2020-09-01"]
    customer_ref:str=Field(pattern=r"^v2c_[0-9a-f]{24}$")
    recommendations:list[Recommendation]=Field(min_length=1,max_length=12)


class Customer(StrictModel):
    customer_ref:str=Field(pattern=r"^v2c_[0-9a-f]{24}$")
    display_label:str=Field(pattern=r"^Historical customer [0-9]{5}$")


class CustomersResponse(StrictModel):
    schema_version:Literal["workbench-customers.v2"]
    release_id:str
    customers:list[Customer]=Field(max_length=100)
    next_cursor:str|None


class Release(StrictModel):
    release_id:str
    status:Literal["candidate","verified"]
    dates:list[Literal["2020-09-09","2020-09-16"]]
    customer_count:int=Field(ge=1,le=20000)
    ranking_mode:Literal["trained_ranker"]
    score_semantics:Literal["ordering_only"]
    warning:str
    model_available_after:Literal["2020-08-25"]
    calibrator_available_after:Literal["2020-09-01"]


class ReleasesResponse(StrictModel):
    schema_version:Literal["workbench-releases.v2"]
    releases:list[Release]


class QualityResponse(StrictModel):
    schema_version:Literal["workbench-quality.v2"]
    release_id:str
    quality:dict
    provenance:dict
    status:Literal["candidate","verified"]
    warning:str
