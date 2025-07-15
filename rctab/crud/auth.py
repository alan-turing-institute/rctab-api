"""User authentication with Active Directory."""

from typing import Dict, Optional

import fastapimsal
import msal
from asyncpg.exceptions import UniqueViolationError
from fastapi import Depends, HTTPException
from rctab_models.models import UserRBAC
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import select

from rctab.crud.models import user_cache, user_rbac
from rctab.db import AsyncConnection, get_async_connection


# Define cache functions
async def load_cache(oid: str, conn: AsyncConnection) -> msal.SerializableTokenCache:
    """Load a user's token cache from the database."""
    cache = msal.SerializableTokenCache()
    # todo : handle case where cache is empty
    value = await conn.scalar(
        select(user_cache.c.cache).where(user_cache.c.oid == oid)
    )
    if value:
        cache.deserialize(value)
        return cache


async def save_cache(oid: str, cache: msal.SerializableTokenCache, conn: AsyncConnection) -> None:
    """Save a user's token cache to the database."""
    if cache.has_state_changed:
        values = {"oid": oid, "cache": cache.serialize()}

        query = insert(user_cache).on_conflict_do_update(
            index_elements=[user_cache.c.oid],
            set_=values,
        ).values(values)
        await conn.execute(query)


async def remove_cache(oid: str, conn: AsyncConnection) -> None:
    """Delete a user's token cache from the database."""
    query = user_cache.delete().where(user_cache.c.oid == oid)
    await conn.execute(query)


async def check_user_access(
    conn: AsyncConnection, oid: str, username: Optional[str] = None, raise_http_exception: bool = True
) -> UserRBAC:
    """Check if a user has access rights.

    If not try to make an entry for them.

    Args:
        oid: User's oid.
        username: User's username.
        raise_http_exception: Raise an exception if the user isn't found.
    """
    statement = select(
        user_rbac.c.oid,
        user_rbac.c.username,
        user_rbac.c.has_access,
        user_rbac.c.is_admin,
    ).where(user_rbac.c.oid == oid)

    result = await conn.execute(statement)
    user_status = result.first()
    if user_status:
        return UserRBAC(**user_status._mapping)

    # If we have a username put it in RBAC table
    if username:

        values = {
            "oid": oid,
            "username": username,
            "has_access": False,
            "is_admin": False,
        }
        insert_q = insert(user_rbac).values(values).on_conflict_do_nothing()
        await conn.execute(insert_q)

    if raise_http_exception:
        raise HTTPException(status_code=401, detail="User not authorized")

    return UserRBAC(oid=oid, username=username, has_access=False, is_admin=False)


async def add_user(oid: str, username: str) -> None:
    """Add an admin user.

    Does not give them admin permissions which requires admin confirmation.
    """
    query = user_rbac.insert().values(
        {
            "oid": oid,
            "username": username,
            "has_access": False,
            "is_admin": False,
        }
    )

    try:
        await conn.execute(
            query=query,
        )

    except UniqueViolationError:
        raise HTTPException(status_code=400, detail="Request already exists")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not complete request")


token_verified = fastapimsal.backend.TokenVerifier(auto_error=True)


async def token_user_verified(conn: AsyncConnection = Depends(get_async_connection), token: Dict = Depends(token_verified)) -> UserRBAC:
    """Get user RBAC information from database.

    Raise a 401 if the user is not authorised.
    """
    oid = token["oid"]
    rbac = await check_user_access(conn, oid)

    if not rbac or rbac.has_access is False:
        raise HTTPException(status_code=401, detail="User not authorized")

    return rbac


async def token_admin_verified(
    rbac: UserRBAC = Depends(token_user_verified),
) -> UserRBAC:
    """Authenticate a user and check whether they are an admin."""
    if rbac.is_admin is False:
        raise HTTPException(
            status_code=401, detail="User does not have admin privileges"
        )

    return rbac


user_authenticated = fastapimsal.frontend.UserAuthenticatedToken(
    load_cache, save_cache, auto_error=True
)
user_authenticated_no_error = fastapimsal.frontend.UserAuthenticatedToken(
    load_cache, save_cache, auto_error=False
)
