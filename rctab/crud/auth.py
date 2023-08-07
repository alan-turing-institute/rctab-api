from typing import Dict, Optional

import fastapimsal
import msal
from asyncpg.exceptions import UniqueViolationError
from fastapi import Depends, HTTPException
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import select

from rctab.crud.models import database, user_cache, user_rbac
from rctab.crud.schema import UserRBAC


# Define cache functions
async def load_cache(oid: str) -> msal.SerializableTokenCache:

    cache = msal.SerializableTokenCache()
    value = await database.fetch_val(
        select([user_cache.c.cache]).where(user_cache.c.oid == oid)
    )
    if value:
        cache.deserialize(value)
        return cache


async def save_cache(oid: str, cache: msal.SerializableTokenCache) -> None:

    if cache.has_state_changed:
        values = {"oid": oid, "cache": cache.serialize()}

        query = insert(user_cache).on_conflict_do_update(
            index_elements=[user_cache.c.oid],
            set_=values,
        )
        await database.execute(query, values=values)


async def remove_cache(oid: str) -> None:
    query = user_cache.delete().where(user_cache.c.oid == oid)
    await database.execute(query)


async def check_user_access(
    oid: str, username: Optional[str] = None, raise_http_exception: bool = True
) -> UserRBAC:
    """Check if a user has access rights. If not try to make an entry for them

    oid: Users oid
    raise_http_exception: Raise an HTTP exception if user not in database
    """

    statement = select(
        [
            user_rbac.c.oid,
            user_rbac.c.username,
            user_rbac.c.has_access,
            user_rbac.c.is_admin,
        ]
    ).where(user_rbac.c.oid == oid)

    user_status = await database.fetch_one(statement)
    if user_status:
        return UserRBAC(**dict(user_status))

    # If we have a username put it in RBAC table
    if username:

        insert_q = insert(user_rbac).on_conflict_do_nothing()
        values = {
            "oid": oid,
            "username": username,
            "has_access": False,
            "is_admin": False,
        }
        await database.execute(insert_q, values=values)

    if raise_http_exception:
        raise HTTPException(status_code=401, detail="User not authorized")

    return UserRBAC(oid=oid, username=username, has_access=False, is_admin=False)


async def add_user(oid: str, username: str) -> None:
    """Add an admin user. Does not give them admin permissions which requires admin confirmation"""

    query = user_rbac.insert()

    try:
        await database.execute(
            query=query,
            values={
                "oid": oid,
                "username": username,
                "has_access": False,
                "is_admin": False,
            },
        )

    except UniqueViolationError:
        raise HTTPException(status_code=400, detail="Request already exists")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not complete request")


token_verified = fastapimsal.backend.TokenVerifier(auto_error=True)


async def token_user_verified(token: Dict = Depends(token_verified)) -> UserRBAC:
    """Get user RBAC information from database.
    Raise a 401 if the user is not authorised.
    """
    oid = token["oid"]
    rbac = await check_user_access(oid)

    if not rbac or rbac.has_access is False:
        raise HTTPException(status_code=401, detail="User not authorized")

    return rbac


async def token_admin_verified(
    rbac: UserRBAC = Depends(token_user_verified),
) -> UserRBAC:

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
