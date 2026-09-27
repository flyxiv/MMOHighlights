from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import schemas
from app.db import get_session
from app.models import Game, Tier

router = APIRouter(prefix="/api", tags=["labels"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/games", response_model=list[schemas.GameOut])
async def list_games(session: Session):
    games = (
        await session.execute(select(Game).options(selectinload(Game.tiers)).order_by(Game.name))
    ).scalars()
    return [schemas.GameOut.model_validate(g) for g in games]


@router.post("/games", response_model=schemas.GameOut, status_code=status.HTTP_201_CREATED)
async def create_game(body: schemas.GameCreate, session: Session):
    game = Game(name=body.name.strip())
    session.add(game)
    try:
        await session.commit()
    except IntegrityError as e:
        raise HTTPException(409, f"{body.name} already exists.") from e
    return schemas.GameOut(id=game.id, name=game.name, tiers=[])


@router.post("/tiers", response_model=schemas.TierOut, status_code=status.HTTP_201_CREATED)
async def create_tier(body: schemas.TierCreate, session: Session):
    if await session.get(Game, body.game_id) is None:
        raise HTTPException(422, "No such game.")
    tier = Tier(game_id=body.game_id, name=body.name.strip(), archived=False)
    session.add(tier)
    try:
        await session.commit()
    except IntegrityError as e:
        raise HTTPException(409, f"{body.name} already exists for this game.") from e
    return schemas.TierOut.model_validate(tier)


@router.patch("/tiers/{tier_id}", response_model=schemas.TierOut)
async def update_tier(tier_id: int, body: schemas.TierUpdate, session: Session):
    tier = await session.get(Tier, tier_id)
    if tier is None:
        raise HTTPException(404, "No such tier.")
    if body.name is not None:
        tier.name = body.name.strip()
    if body.archived is not None:
        tier.archived = body.archived
    try:
        await session.commit()
    except IntegrityError as e:
        raise HTTPException(409, "A tier with that name already exists for this game.") from e
    return schemas.TierOut.model_validate(tier)
