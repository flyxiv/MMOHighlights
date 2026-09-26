from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Color = Literal["red", "orange", "amber", "green", "cyan", "blue", "violet", "pink"]
COLORS: tuple[Color, ...] = ("red", "orange", "amber", "green", "cyan", "blue", "violet", "pink")
Task = Literal["classification", "detection", "segmentation"]
Status = Literal["todo", "done", "review"]

Name = Field(min_length=1, max_length=60)


class LabelClass(BaseModel):
    # Stable for the project's lifetime; also the YOLO class index.
    id: int = Field(ge=0)
    name: str = Name
    color: Color


class LabelGroup(BaseModel):
    """An image-level classification question with one answer, e.g. fight_state."""

    name: str = Name
    options: list[str] = Field(min_length=1, max_length=50)

    @field_validator("options")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        v = [o.strip() for o in v if o.strip()]
        if not v:
            raise ValueError("A label group needs at least one option.")
        if len(set(v)) != len(v):
            raise ValueError("Options in a label group must be unique.")
        return v


class Project(BaseModel):
    version: int = 1
    slug: str
    name: str
    created_at: datetime
    tasks: list[Task]
    classes: list[LabelClass] = []
    groups: list[LabelGroup] = []
    image_count: int = 0


class ClassIn(BaseModel):
    # Omit for a new class.
    id: int | None = Field(default=None, ge=0)
    name: str = Name
    color: Color | None = None


class ProjectCreate(BaseModel):
    name: str = Name
    tasks: list[Task] = Field(min_length=1)
    classes: list[ClassIn] = []
    groups: list[LabelGroup] = []


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    tasks: list[Task] | None = Field(default=None, min_length=1)
    # Full list. Keep a class's id to rename or recolor it; drop it to delete (only if unused).
    classes: list[ClassIn] | None = None
    groups: list[LabelGroup] | None = None


class Stats(BaseModel):
    total: int
    done: int
    review: int
    todo: int
    class_counts: dict[int, int]


class ProjectOut(Project):
    storage_uri: str
    stats: Stats
    pending_sync: int


class ProjectSummary(BaseModel):
    slug: str
    name: str
    tasks: list[Task]
    created_at: datetime
    image_count: int
    classes: int
    # Known only once the project has been opened on this machine.
    done: int | None


class LabelObject(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    class_id: int = Field(ge=0)
    type: Literal["box", "polygon"] = "box"
    # x, y, width, height in image pixels. Derived from the points for polygons.
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    points: list[tuple[float, float]] | None = None
    source: Literal["manual", "model"] = "manual"
    score: float | None = Field(default=None, ge=0, le=1)
    # Model suggestions stay unaccepted (dashed, not exported) until confirmed.
    accepted: bool = True


class AnnotationIn(BaseModel):
    status: Status = "todo"
    labels: dict[str, str] = {}
    objects: list[LabelObject] = Field(default=[], max_length=2000)


class Annotation(AnnotationIn):
    file: str
    updated_at: datetime | None = None


class ImageRow(BaseModel):
    file: str
    width: int
    height: int
    status: Status
    objects: int
    suggested: int
    labels: dict[str, str]


class ImportRequest(BaseModel):
    # A folder on this machine, or a gs:// prefix.
    source: str = Field(min_length=1)


class Job(BaseModel):
    id: str
    slug: str
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
    files: list[str] = Field(min_length=1, max_length=20000)
    # group -> option, or None to clear.
    labels: dict[str, str | None] = {}
    status: Status | None = None


class BulkResult(BaseModel):
    updated: int


class PredictedObject(BaseModel):
    class_id: int | None = None
    class_name: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    points: list[tuple[float, float]] | None = None
    score: float | None = Field(default=None, ge=0, le=1)


class Prediction(BaseModel):
    file: str
    objects: list[PredictedObject] = []


class PredictionsIn(BaseModel):
    predictions: list[Prediction] = Field(max_length=100000)
    # Drop earlier unaccepted suggestions on those images first.
    replace: bool = True


class PredictionsResult(BaseModel):
    updated: int
    skipped: int


class ExportRequest(BaseModel):
    format: Literal["yolo", "coco"]
    # Also export images that aren't marked done.
    include_unfinished: bool = False


class ExportResult(BaseModel):
    uri: str
    format: str
    images: int
    objects: int


class Health(BaseModel):
    storage: str
    pending_sync: int
    last_sync_error: str | None
