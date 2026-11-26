from app.platform.telemetry import METRICS, classify_failure, measure
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
import logging
import re
from http import HTTPStatus
from uuid import uuid4
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.responses import Response

from app.application.health import ReadinessProbe, is_ready
from app.platform.config import Settings, load_settings
from app.platform.database import Database
from app.platform.logging import configure_logging
from app.presentation.contracts import HealthResponse, Problem
from app.modules.identity.application import IdentityService
from app.modules.events.application import EventService
from app.modules.garage.application import GarageService
from app.modules.garage.infrastructure import PostgresGarage
from app.modules.garage.presentation import garage_router
from app.modules.community.application import CommunityService
from app.modules.community.infrastructure import PostgresCommunity
from app.modules.community.presentation import community_router
from app.modules.events.infrastructure import PostgresEvents
from app.modules.events.presentation import events_router, business_errors, success_headers
from app.modules.discovery.application import DiscoveryService
from app.modules.discovery.infrastructure import SignedCursor
from app.modules.discovery.presentation import discovery_router
from app.platform.business_ingress import BusinessIngress
from app.platform.realtime import EventBus
from app.modules.events.realtime import StreamSettings, updates_router
from app.modules.identity.body_limit import IdentityBodyLimit
from app.modules.identity.firebase import FirebaseVerifier, UnconfiguredVerifier
from app.modules.identity.infrastructure import PostgresIdentityRepository
from app.modules.identity.ports import IdentityRepository, TokenVerifier
from app.modules.identity.presentation import LocalLimits, identity_router, identity_security


def problem_response(request: Request, status: int, title: str, detail: str) -> JSONResponse:
    body = Problem(type="about:blank", title=title, status=status, detail=detail,
                   correlation_id=request.state.correlation_id)
    return JSONResponse(body.model_dump(), status_code=status,
                        media_type="application/problem+json")


def create_app(settings: Settings | None = None, probe: ReadinessProbe | None = None, *,
               firebase: FirebaseVerifier | None = None,
               identity_test: tuple[TokenVerifier, IdentityRepository] | None = None,
               test_verifier: TokenVerifier | None = None,
               test_limits: LocalLimits | None = None,
               test_streams: StreamSettings | None = None) -> FastAPI:
    configuration = settings or load_settings()
    if configuration.db_user != "np_runtime":
        raise ValueError("API requires the runtime role")
    if configuration.environment != "test" and (identity_test is not None or test_verifier is not None or test_limits is not None or test_streams is not None):
        raise ValueError("Test identity composition requires an explicit test environment")
    if test_verifier is not None and (identity_test is not None or firebase is not None):
        raise ValueError("Choose one explicit identity composition")
    if firebase is not None and firebase.configuration.environment != configuration.environment:
        raise ValueError("Firebase and API environments must match")
    database = Database(configuration) if probe is None else None
    if probe is not None:
        readiness = probe
    else:
        assert database is not None
        readiness = database
    configure_logging()
    logger = logging.getLogger("nightpoint")

    event_bus=EventBus()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            event_bus.close()
            if database is not None:
                database.close()

    application = FastAPI(
        title="NightPoint Foundation", version="0.1.0", lifespan=lifespan,
        openapi_url="/api/v1/openapi.json", docs_url="/docs", redoc_url=None,
    )
    # Correlation middleware registered below wraps this parser budget.
    limits = test_limits or LocalLimits()
    application.state.identity_limits = limits
    application.add_middleware(IdentityBodyLimit, limits=limits)
    application.add_middleware(BusinessIngress)

    @application.middleware("http")
    async def correlation(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        supplied = request.headers.get("X-Correlation-ID")
        valid = supplied is None or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied) is not None
        # Never echo/log client-controlled correlation data, even if syntactically valid.
        request.state.correlation_id = uuid4().hex
        try:
            if not valid:
                response = problem_response(request, 400, "Bad Request", "Invalid correlation identifier")
            else:
                with measure("http.dispatch"):
                    response = await call_next(request)
        except Exception as error:
            METRICS.exception(error)
            category = classify_failure(error)
            request.state.failure_category = category
            METRICS.failure(category)
            response = problem_response(request, 500, "Internal Server Error", "Unexpected failure")
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["Cache-Control"] = "no-store"
        with measure("http.logging"):
            logger.info("http_request", extra={"correlation_id": request.state.correlation_id,
                        "status": response.status_code,"failure_category":getattr(request.state,"failure_category","none")})
        return response

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        # Do not reflect arbitrary exception detail or URL into public output.
        title = HTTPStatus(exc.status_code).phrase if exc.status_code in HTTPStatus._value2member_map_ else "HTTP Error"
        response = problem_response(request, exc.status_code, title, "Request could not be served")
        safe_headers = {"allow", "retry-after", "www-authenticate", "content-range"}
        for header, value in (exc.headers or {}).items():
            if header.lower() in safe_headers and not any(c in value for c in "\r\n\x00"):
                if header.lower() != "www-authenticate" or exc.status_code == 401:
                    response.headers[header] = value
        return response

    @application.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.method in {"PATCH","PUT","POST"} and any(e["type"] == "missing" and tuple(e["loc"]) == ("header", "if-match") for e in exc.errors()):
            return problem_response(request, 428, "Precondition Required", "If-Match is required")
        return problem_response(request, 422, "Unprocessable Content", "Request validation failed")

    problem_contract: dict[str, Any] = {"description": "Sanitized Problem Details", "content": {
        "application/problem+json": {"schema": Problem.model_json_schema()}}}
    response_headers = {"X-Correlation-ID": {"description": "Server-generated opaque identifier",
        "schema": {"type": "string", "pattern": "^[0-9a-f]{32}$"}}}
    problem_contract["headers"] = response_headers
    errors: dict[int | str, dict[str, Any]] = {code: problem_contract for code in (400, 422, 500)}
    errors[200] = {"description": "Healthy", "headers": response_headers}
    correlation_contract = {"parameters": [{"name": "X-Correlation-ID", "in": "header",
        "required": False, "schema": {"type": "string", "maxLength": 64,
        "pattern": "^[A-Za-z0-9_-]{1,64}$"}}]}

    @application.get("/api/v1/health/live", response_model=HealthResponse,
                     operation_id="liveness", responses=errors, openapi_extra=correlation_contract)
    def live() -> HealthResponse:
        return HealthResponse()

    @application.get("/api/v1/health/ready", response_model=HealthResponse,
                     operation_id="readiness", responses={**errors, 503: problem_contract},
                     openapi_extra=correlation_contract)
    def ready(request: Request) -> HealthResponse | JSONResponse:
        if not is_ready(readiness) or (firebase is not None and not firebase.ready()):
            return problem_response(request, 503, "Service Unavailable", "Dependency unavailable")
        return HealthResponse()

    verifier: TokenVerifier = firebase if firebase is not None else UnconfiguredVerifier()
    if test_verifier is not None:
        verifier = test_verifier
    service = IdentityService(PostgresIdentityRepository(database)) if database is not None else None
    if identity_test is not None:
        verifier, repository = identity_test
        service = IdentityService(repository)
    security=identity_security(verifier,service,limits)
    application.include_router(identity_router(verifier,service,limits,security))
    garage_service=GarageService(PostgresGarage(database)) if database is not None else None
    application.include_router(garage_router(garage_service,security.actor))
    event_repository=PostgresEvents(database) if database is not None else None
    event_service=EventService(event_repository,event_bus) if event_repository is not None else None
    application.include_router(events_router(event_service,security.actor,security.publisher))
    application.state.database=database
    application.state.event_service=event_service
    application.state.event_bus=event_bus
    community_service=CommunityService(PostgresCommunity(database),event_service,event_bus) if database is not None and event_service is not None else None
    application.include_router(community_router(community_service,security.actor,security.publisher))
    application.include_router(updates_router(event_service,security.actor,event_bus,test_streams or StreamSettings()))
    discovery_service=DiscoveryService(event_repository,SignedCursor()) if event_repository is not None else None
    application.include_router(discovery_router(discovery_service,security.actor,{**business_errors(408,413),
        200:{"description":"Authorized nearby page","headers":{k:v for k,v in success_headers().items() if k!="ETag"}}}))
    return application
