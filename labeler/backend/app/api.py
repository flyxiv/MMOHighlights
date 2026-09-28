"""HTTP API. Handlers are sync so FastAPI runs them in its thread pool (storage and SQLite calls block)."""

from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse

from app.labeler import Labeler
from app.schemas import (
    BulkRequest,
    BulkResult,
    Dataset,
    DatasetCreate,
    DatasetSummary,
    Health,
    ImportRequest,
    Job,
    LabelingPatch,
    PredictionsIn,
    PredictionsResult,
    ReleaseRequest,
    ReleaseResult,
    Sample,
    SampleRow,
    SampleSave,
    UploadResult,
)

router = APIRouter(prefix="/api")

# Sample ids are content hashes, so an id's image never changes and browsers may cache it.
IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}


def labeler(request: Request) -> Labeler:
    return request.app.state.labeler


@router.get("/health", response_model=Health)
def health(request: Request):
    lb = labeler(request)
    return Health(
        storage=lb.store.uri(), pending_sync=lb.index.pending_count(), last_sync_error=lb.last_sync_error
    )


@router.get("/datasets", response_model=list[DatasetSummary])
def list_datasets(request: Request):
    return labeler(request).list_datasets()


@router.post("/datasets", response_model=Dataset, status_code=201)
def create_dataset(body: DatasetCreate, request: Request):
    return labeler(request).create_dataset(body)


@router.get("/datasets/{name}", response_model=Dataset)
def get_dataset(name: str, request: Request):
    return labeler(request).dataset(name)


@router.patch("/datasets/{name}/labeling", response_model=Dataset)
def update_labeling(name: str, body: LabelingPatch, request: Request):
    return labeler(request).update_labeling(name, body)


@router.get("/datasets/{name}/samples", response_model=list[SampleRow])
def list_samples(name: str, request: Request):
    return labeler(request).rows(name)


@router.get("/datasets/{name}/samples/{sid}", response_model=Sample)
def get_sample(name: str, sid: str, request: Request):
    return labeler(request).sample(name, sid)


@router.put("/datasets/{name}/samples/{sid}", response_model=Sample)
def save_sample(name: str, sid: str, body: SampleSave, request: Request):
    return labeler(request).save_sample(name, sid, body)


@router.get("/datasets/{name}/samples/{sid}/image")
def sample_image(name: str, sid: str, request: Request):
    return FileResponse(labeler(request).image_path(name, sid), headers=IMMUTABLE)


@router.get("/datasets/{name}/samples/{sid}/thumb")
def sample_thumb(name: str, sid: str, request: Request):
    return FileResponse(labeler(request).thumb_path(name, sid), media_type="image/webp", headers=IMMUTABLE)


@router.post("/datasets/{name}/bulk", response_model=BulkResult)
def bulk(name: str, body: BulkRequest, request: Request):
    return BulkResult(updated=labeler(request).bulk(name, body))


@router.post("/datasets/{name}/imports", response_model=Job, status_code=202)
def start_import(name: str, body: ImportRequest, request: Request):
    return labeler(request).start_import(name, body.source)


@router.get("/datasets/{name}/imports", response_model=list[Job])
def list_imports(name: str, request: Request):
    return labeler(request).jobs(name)


@router.get("/imports/{job_id}", response_model=Job)
def get_import(job_id: str, request: Request):
    return labeler(request).job(job_id)


@router.post("/datasets/{name}/uploads", response_model=UploadResult)
def upload(name: str, request: Request, files: Annotated[list[UploadFile], File()]):
    items = [(f.filename or "", f.file.read()) for f in files]
    return labeler(request).upload(name, items)


@router.post("/datasets/{name}/predictions", response_model=PredictionsResult)
def predictions(name: str, body: PredictionsIn, request: Request):
    return labeler(request).apply_predictions(name, body)


@router.post("/datasets/{name}/releases", response_model=ReleaseResult, status_code=201)
def cut_release(name: str, body: ReleaseRequest, request: Request):
    return labeler(request).release(name, body)
