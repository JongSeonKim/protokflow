from typing import TYPE_CHECKING

from fastapi.routing import APIRoute, _IncludedRouter
from starlette.routing import BaseRoute, Mount, Route

if TYPE_CHECKING:
    from fastapi import FastAPI


def get_all_route_names(
    routes: list[BaseRoute], current_prefix: str = ""
) -> list[tuple[Route, str]]:
    """Recursively walk routes to find all APIRoutes and their fully resolved paths.

    Plain Starlette ``Route`` entries (``/openapi.json``, ``/docs``, …) are collected
    too, so callers that need APIRoute-only attributes must narrow with ``isinstance``.
    """

    res: list[tuple[Route, str]] = []
    for r in routes:
        if isinstance(r, APIRoute):
            path = (current_prefix + r.path).replace("//", "/")
            res.append((r, path))
        elif isinstance(r, _IncludedRouter):
            ctx = getattr(r, "include_context", None)
            p = ctx.prefix if ctx else ""
            res.extend(
                get_all_route_names(r.original_router.routes, current_prefix + p)
            )
        elif isinstance(r, Route):
            path = (current_prefix + r.path).replace("//", "/")
            res.append((r, path))
        elif isinstance(r, Mount):
            res.extend(get_all_route_names(r.routes, current_prefix + r.path))
    return res


def simplify_operation_ids(app: FastAPI) -> None:
    """
    Simplify operation IDs so that generated clients have simpler API function names.

    :param app: FastAPI application instance
    :return:
    """
    for route, _ in get_all_route_names(app.routes):
        # Plain Starlette routes have no operation_id; assigning one on them is inert
        # and preserved as-is rather than filtered out.
        route.operation_id = route.name  # type: ignore[attr-defined]


def ensure_unique_route_names(app: FastAPI) -> None:
    """
    Check if the route name is unique

    :param app: FastAPI application instance
    :return:
    """
    temp_routes = set()
    for route, _ in get_all_route_names(app.routes):
        if route.name in temp_routes:
            raise ValueError(f"Non-unique route name: {route.name}")
        temp_routes.add(route.name)
