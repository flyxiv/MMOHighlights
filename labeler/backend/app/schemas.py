"""API models. Label data uses the uniform dataset format (datasets/STRUCTURE.md in RaidDesigner):
labels are {task: {"type": ..., "value": ...}} with class names, and boxes are absolute-pixel xyxy.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

LabelType = Literal[
    "class", "multilabel", "bbox", "polygon", "mask", "keypoints", "span", "scalar", "text", "ref"
]
# Types the labeler can edit. Other tasks are carried along untouched and shown read-only.
EDITABLE: tuple[str, ...] = ("class", "multilabel", "bbox", "polygon")
Status = Literal["todo", "review", "done", "excluded"]

NAME_PATTERN = r"^[a-z0-9][a-z0-9_]{1,63}$"
TASK_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class TaskSpec(BaseModel):
    type: LabelType
    unit: str | None = None
    description: str | None = None


class Card(BaseModel):
    """Fields for dataset.json that exist before the first release (kept in labeling/project.json)."""

    name: str = Field(pattern=NAME_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    description: str | None = None
    modality: list[Literal["image", "video", "audio", "3d", "text", "tabular"]] = ["image"]
    license: str = "private"
    project: str | None = None
    tags: list[str] = []


class DatasetCreate(Card):
    tasks: dict[str, TaskSpec] = Field(min_length=1)
    classes: dict[str, list[str]] = {}


class LabelingPatch(BaseModel):
    # Full task map: add tasks, or drop ones that are unused and not in a release.
    tasks: dict[str, TaskSpec] | None = None
    # Full vocabulary per task. Released classes must stay first and in order; append new ones.
    classes: dict[str, list[str]] | None = None


class Stats(BaseModel):
    total: int
    todo: int
    review: int
    done: int
    excluded: int
    new: int
    # Edited here but not marked done: those edits don't go into the next release.
    edited_not_done: int
    # task -> class -> number of objects (bbox/polygon) or images (class/multilabel)
    class_counts: dict[str, dict[str, int]]


class Dataset(BaseModel):
    name: str
    title: str
    description: str | None
    tasks: dict[str, TaskSpec]
    classes: dict[str, list[str]]
    base_release: str | None
    latest: str | None
    releases: list[str]
    next_release: str
    storage_uri: str
    stats: Stats
    pending_sync: int


class DatasetSummary(BaseModel):
    name: str
    title: str
    tasks: dict[str, TaskSpec]
    latest: str | None
    samples: int | None
    # False when the dataset exists but nobody has labeled it here yet.
    labeling: bool
    created: str | None


class SampleRow(BaseModel):
    id: str
    name: str
    status: Status
    objects: int
    suggested: int
    # class/multilabel tasks -> value
    labels: dict[str, str | list[str]]
    split: str
    new: bool
    reviewed: bool


class Sample(BaseModel):
    id: str
    name: str
    image: str
    width: int
    height: int
    status: Status
    labels: dict[str, dict[str, Any]]
    suggestions: dict[str, dict[str, Any]]
    split: str
    new: bool
    meta: dict[str, Any]
    updated_at: datetime | None


class SampleSave(BaseModel):
    status: Status = "todo"
    # Complete labels for the editable tasks. Tasks of other types are kept from the stored sample.
    labels: dict[str, dict[str, Any]] = {}
    suggestions: dict[str, dict[str, Any]] = {}


class ImportRequest(BaseModel):
    # A folder on this machine, or a gs:// prefix.
    source: str = Field(min_length=1)


class Job(BaseModel):
    id: str
    dataset: str
    state: Literal["running", "done", "failed"] = "running"
    source: str
    total: int = 0
    processed: int = 0
    added: int = 0
    skipped: int = 0
    errors: list[str] = []
    message: str | None = None


class UploadResult(BaseModel):
    added: int
    skipped: int
    errors: list[str]


class BulkRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=50000)
    # class task -> value (or list for multilabel), None clears it
    labels: dict[str, str | list[str] | None] = {}
    status: Status | None = None


class BulkResult(BaseModel):
    updated: int


class Prediction(BaseModel):
    id: str
    # {task: {"type": "bbox", "value": [{"class", "xyxy", "score"}]}} — same shape as labels
    suggestions: dict[str, dict[str, Any]]


class PredictionsIn(BaseModel):
    predictions: list[Prediction] = Field(max_length=100000)


class PredictionsResult(BaseModel):
    updated: int
    skipped: int


class ReleaseRequest(BaseModel):
    notes: str = ""


class ReleaseResult(BaseModel):
    version: str
    uri: str
    samples: int
    reviewed: int
    splits: dict[str, int]
    warnings: list[str]


class Health(BaseModel):
    storage: str
    pending_sync: int
    last_sync_error: str | None
