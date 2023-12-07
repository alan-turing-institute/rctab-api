"""The entrypoint of the FastAPI application."""
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Final

import fastapimsal
import secure
from asyncpg.exceptions import UniqueViolationError
from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException
from starlette.templating import _TemplateResponse

from rctab.constants import __version__
from rctab.crud.auth import (
    add_user,
    load_cache,
    remove_cache,
    save_cache,
    token_admin_verified,
    token_verified,
    user_authenticated,
)
from rctab.crud.models import database
from rctab.logutils import set_log_handler
from rctab.routers import accounting, frontend
from rctab.routers.accounting import routes
from rctab.settings import get_settings

templates = Jinja2Templates(directory=Path("rctab/templates"))

app = FastAPI(
    title="RCTab API",
    description="API for RCTab",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

server = secure.Server().set("Secure")

csp = (
    secure.ContentSecurityPolicy()
    .default_src("'none'")
    .base_uri("'self'")
    .connect_src("'self'")
    .frame_src("'none'")
    .img_src("'self'")
    .style_src(
        "'self'", "'unsafe-inline'", "fonts.googleapis.com", "cdn.datatables.net"
    )
    .script_src(
        "'self'", "'unsafe-inline'", "ajax.googleapis.com", "cdn.datatables.net"
    )
    .font_src("'self'", "fonts.gstatic.com")
)

hsts = secure.StrictTransportSecurity().include_subdomains().preload().max_age(2592000)

referrer = secure.ReferrerPolicy().no_referrer()

permissions_value = secure.PermissionsPolicy()

cache_value = secure.CacheControl().must_revalidate()

SECURE_HEADERS: Final = secure.Secure(
    server=server,
    csp=csp,
    hsts=hsts,
    referrer=referrer,
    permissions=permissions_value,
    cache=cache_value,
)


@app.middleware("http")
async def set_secure_headers(request: Any, call_next: Callable[[Any], Any]) -> Any:
    """Set security headers for HTTP response."""
    response = await call_next(request)
    SECURE_HEADERS.framework.fastapi(response)
    return response


# Add session middleware and authentication routes
fastapimsal.init_auth(
    app, f_load_cache=load_cache, f_save_cache=save_cache, f_remove_cache=remove_cache
)


@app.on_event("startup")
async def startup() -> None:
    """Start the server up."""
    await database.connect()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    set_log_handler()
    if not settings.ignore_whitelist:
        logger = logging.getLogger(__name__)
        logger.warning(
            "Starting server with subscription whitelist: %s", settings.whitelist
        )


@app.on_event("shutdown")
async def shutdown() -> None:
    """Shut the server down."""
    logger = logging.getLogger(__name__)
    logger.warning("Shutting down server...")

    logger.info("Disconnecting from database")
    await database.disconnect()


@app.exception_handler(UniqueViolationError)
async def unicorn_exception_handler(
    _: Request, exc: UniqueViolationError
) -> JSONResponse:
    """Handle unique constraint violations."""
    return JSONResponse(
        status_code=409,
        content={"message": f"One of the records already exists. Details: {exc}"},
    )


@app.exception_handler(404)
async def custom_404_handler(request: Request, __: HTTPException) -> _TemplateResponse:
    """Provide a more useful 404 page."""
    return templates.TemplateResponse(
        "404.html",
        {
            "request": request,
            "version": __version__,
        },
        status_code=404,
    )


app.mount(
    "/static",
    StaticFiles(directory=str((Path(__file__).parent / "static").absolute())),
    name="static",
)

app.include_router(frontend.router, prefix="")
app.include_router(accounting.router, prefix="/usage", tags=["Usage"])
app.include_router(accounting.router, prefix="/status", tags=["Status"])
app.include_router(
    accounting.router, prefix=accounting.routes.PREFIX, tags=["Accounting"]
)
app.include_router(routes.router, prefix=routes.PREFIX, tags=["Accounting"])


@app.post("/admin/request-access", response_class=JSONResponse)
async def request_admin_access(token: Dict = Depends(token_verified)) -> Dict[str, str]:
    """Request administrator access."""
    await add_user(token["oid"], token["preferred_username"])
    return {"detail": "Admin request made"}


@app.get("/version", include_in_schema=False)
async def show_version(_: Dict = Depends(token_admin_verified)) -> dict:
    """Get the app version."""
    return {"detail": __version__}


# Place docs behind auth
@app.get("/openapi.json", include_in_schema=False)
async def get_open_api_endpoint(
    _: Dict = Depends(user_authenticated),
) -> JSONResponse:
    """Serves OpenAPI endpoints."""
    return JSONResponse(
        get_openapi(title="Example API", version="0.0.1", routes=app.routes)
    )


@app.get("/docs", include_in_schema=False)
async def get_documentation(_: Dict = Depends(user_authenticated)) -> HTMLResponse:
    """Serves swagger API docs."""
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")


@app.get("/redoc", include_in_schema=False)
async def get_redocumentation(_: Dict = Depends(user_authenticated)) -> HTMLResponse:
    """Serves Redoc API docs."""
    return get_redoc_html(openapi_url="/openapi.json", title="docs")
