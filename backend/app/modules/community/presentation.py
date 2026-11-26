from collections.abc import Callable
from typing import Annotated, Any, Self, Literal, TypeVar
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.modules.identity.api import ActorProvider, VerifiedActor
from app.modules.events.api import EventContext, InaccessibleEvent
from app.presentation.contracts import Problem
from .application import CommunityService
from .domain import Comment, HiddenComment, StaleComment, InteractionConflict, validate_comment

T = TypeVar('T')


class ReactionBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active: bool = Field(strict=True)


class CommentVisibility(BaseModel):
    model_config = ConfigDict(extra='forbid')
    removed: bool = Field(strict=True)


class CommentBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(strict=True,min_length=1,max_length=1000)

    @model_validator(mode='after')
    def valid(self) -> Self:
        validate_comment(self.text)
        return self


class SummaryOutput(BaseModel):
    likes: int
    participants: int
    liked: bool
    participating: bool


class CommentOutput(BaseModel):
    id: UUID
    text: str
    version: int
    mine: bool
    organizer: bool
    removed: bool
    can_remove: bool
    can_restore: bool

    @classmethod
    def of(cls, comment: Comment, actor: UUID, event: EventContext) -> 'CommentOutput':
        content = comment.text if not comment.removed or comment.removed_by == actor else ''
        return cls(id=comment.id,text=content,version=comment.version,mine=comment.actor_id==actor,
            organizer=comment.actor_id==event.owner_id,removed=comment.removed,
            can_remove=comment.may_remove(actor,event.owner_id),can_restore=comment.may_restore(actor))


class CommentPage(BaseModel):
    items: list[CommentOutput]
    next_offset: int | None


def community_router(service: CommunityService | None, actor: Callable[...,VerifiedActor],
                     eligible: Callable[...,VerifiedActor]) -> APIRouter:
    failure: dict[str,Any] = {'description':'Sanitized Problem Details','content':{
        'application/problem+json':{'schema':Problem.model_json_schema()}},'headers':{
        'Cache-Control':{'schema':{'type':'string','const':'no-store'}},
        'X-Correlation-ID':{'schema':{'type':'string','pattern':'^[0-9a-f]{32}$'}}}}
    failures: dict[int | str,dict[str,Any]] = {code:failure for code in (400,401,403,404,408,409,412,413,422,428,429,500,503)}
    router = APIRouter(prefix='/api/v1/events/{event_id}/community',tags=['community'],responses=failures)

    def success(revision: bool=False,location: bool=False) -> dict[str,Any]:
        headers: dict[str,Any] = dict(failure['headers'])
        if revision: headers['ETag'] = {'schema':{'type':'string','pattern':'^"[1-9][0-9]*"$'}}
        if location: headers['Location'] = {'schema':{'type':'string'}}
        return {'description':'Authorized response','headers':headers}

    def current() -> CommunityService:
        if service is None: raise HTTPException(503)
        return service

    def provider(acting: VerifiedActor) -> ActorProvider:
        return lambda: acting

    def perform(operation: Callable[[],T]) -> T:
        try: return operation()
        except (InaccessibleEvent,HiddenComment): raise HTTPException(404) from None
        except StaleComment: raise HTTPException(412) from None
        except InteractionConflict: raise HTTPException(409) from None

    @router.get('',response_model=SummaryOutput,operation_id='readEventCommunity',responses={200:success()})
    def summary(event_id: UUID,acting: Annotated[VerifiedActor,Depends(actor)]) -> SummaryOutput:
        value = perform(lambda: current().summary(provider(acting),event_id))
        return SummaryOutput(likes=value.likes,participants=value.participants,liked=value.liked,participating=value.participating)

    @router.put('/reactions/{kind}',status_code=204,operation_id='setEventReaction',responses={204:success()})
    def reaction(event_id: UUID,kind: Literal['like','participation'],body: ReactionBody,
                 acting: Annotated[VerifiedActor,Depends(eligible)]) -> Response:
        perform(lambda: current().reaction(provider(acting),event_id,kind,body.active))
        return Response(status_code=204)

    @router.get('/comments',response_model=CommentPage,operation_id='listEventComments',responses={200:success()})
    def comments(event_id: UUID,acting: Annotated[VerifiedActor,Depends(actor)],include_removed: bool=False,
                 limit: int=Query(default=25,ge=1,le=50),offset: int=Query(default=0,ge=0,le=5000)) -> CommentPage:
        event,rows = perform(lambda: current().comments(provider(acting),event_id,include_removed,limit,offset))
        return CommentPage(items=[CommentOutput.of(row,acting.user_id,event) for row in rows[:limit]],
            next_offset=offset+limit if len(rows)>limit else None)

    @router.post('/comments',response_model=CommentOutput,status_code=201,operation_id='createEventComment',
                 responses={200:{**success(True,True),'model':CommentOutput},201:success(True,True)})
    def create(event_id: UUID,body: CommentBody,acting: Annotated[VerifiedActor,Depends(eligible)],response: Response,
               idempotency_key: Annotated[UUID,Header()]) -> CommentOutput:
        event,comment,created = perform(lambda: current().create_comment(provider(acting),event_id,idempotency_key,body.text))
        response.status_code = 201 if created else 200
        response.headers['ETag'] = f'"{comment.version}"'
        response.headers['Location'] = f'/api/v1/events/{event_id}/community/comments/{comment.id}'
        return CommentOutput.of(comment,acting.user_id,event)

    @router.get('/comments/{comment_id}',response_model=CommentOutput,operation_id='readEventComment',responses={200:success(True)})
    def detail(event_id: UUID,comment_id: UUID,acting: Annotated[VerifiedActor,Depends(actor)],response: Response) -> CommentOutput:
        event,comment = perform(lambda: current().comment(provider(acting),event_id,comment_id))
        response.headers['ETag'] = f'"{comment.version}"'
        return CommentOutput.of(comment,acting.user_id,event)

    @router.put('/comments/{comment_id}/visibility',response_model=CommentOutput,operation_id='setCommentVisibility',responses={200:success(True)})
    def visibility(event_id: UUID,comment_id: UUID,body: CommentVisibility,
                   acting: Annotated[VerifiedActor,Depends(eligible)],response: Response,
                   if_match: Annotated[str,Header(pattern='^"[1-9][0-9]{0,9}"$')]) -> CommentOutput:
        event,comment = perform(lambda: current().visibility(provider(acting),event_id,comment_id,body.removed,int(if_match.strip('"'))))
        response.headers['ETag'] = f'"{comment.version}"'
        return CommentOutput.of(comment,acting.user_id,event)

    return router
