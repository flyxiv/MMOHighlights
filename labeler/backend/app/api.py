"""HTTP API. Handlers are sync so FastAPI runs them in its thread pool (storage and SQLite calls block)."""

from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse

from app.labeler import Labeler
from app.schemas import (
    Annotation,
    AnnotationIn,
    BulkRequest,
    BulkResult,
    ExportRequest,
    ExportResult,
    Health,
    ImageRow,
    ImportRequest,
    Job,
    PredictionsIn,
    PredictionsResult,
    ProjectCreate,
    ProjectOut,
    ProjectPatch,
    ProjectSummary,
    UploadResult,
)

router = APIRouter(prefix="/api")

# Image names never change content (re-imports of a name are skipped), so browsers may cache them.
IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}


def labeler(request: Request) -> Labeler:
    return request.app.state.labeler


@router.get("/health", response_model=Health)
def health(request: Request):
    lb = labeler(request)
    return Health(
        storage=lb.store.uri(), pending_sync=lb.index.pending_count(), last_sync_error=lb.last_sync_error
    )


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(request: Request):
    return labeler(request).list_projects()


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, request: Request):
    return labeler(request).create_project(body)


@router.get("/projects/{slug}", response_model=ProjectOut)
def get_project(slug: str, request: Request):
    return labeler(request).project(slug)


@router.patch("/projects/{slug}", response_model=ProjectOut)
def update_project(slug: str, body: ProjectPatch, request: Request):
    return labeler(request).update_project(slug, body)


@router.get("/projects/{slug}/images", response_model=list[ImageRow])
def list_images(slug: str, request: Request):
    return labeler(request).images(slug)


@router.get("/projects/{slug}/files/{file:path}")
def image_file(slug: str, file: str, request: Request):
    return FileResponse(labeler(request).image_path(slug, file), headers=IMMUTABLE)


@router.get("/projects/{slug}/thumbs/{file:path}")
def image_thumb(slug: str, file: str, request: Request):
    return FileResponse(labeler(request).thumb_path(slug, file), media_type="image/webp", headers=IMMUTABLE)


@router.get("/projects/{slug}/annotations/{file:path}", response_model=Annotation)
def get_annotation(slug: str, file: str, request: Request):
    return labeler(request).annotation(slug, file)


@router.put("/projects/{slug}/annotations/{file:path}", response_model=Annotation)
def put_annotation(slug: str, file: str, body: AnnotationIn, request: Request):
    return labeler(request).save_annotation(slug, file, body)


@router.post("/projects/{slug}/bulk", response_model=BulkResult)
def bulk(slug: str, body: BulkRequest, request: Request):
    return BulkResult(updated=labeler(request).bulk(slug, body))


@router.post("/projects/{slug}/imports", response_model=Job, status_code=202)
def start_import(slug: str, body: ImportRequest, request: Request):
    return labeler(request).start_import(slug, body.source)


@router.get("/projects/{slug}/imports", response_model=list[Job])
def list_imports(slug: str, request: Request):
    return labeler(request).jobs(slug)


@router.get("/imports/{job_id}", response_model=Job)
def get_import(job_id: str, request: Request):
    return labeler(request).job(job_id)


@router.post("/projects/{slug}/uploads", response_model=UploadResult)
def upload(slug: str, request: Request, files: Annotated[list[UploadFile], File()]):
    items = [(f.filename or "", f.file.read()) for f in files]
    return labeler(request).upload(slug, items)


@router.post("/projects/{slug}/predictions", response_model=PredictionsResult)
def predictions(slug: str, body: PredictionsIn, request: Request):
    return labeler(request).apply_predictions(slug, body)


@router.post("/projects/{slug}/exports", response_model=ExportResult)
def export(slug: str, body: ExportRequest, request: Request):
    return labeler(request).export(slug, body)
