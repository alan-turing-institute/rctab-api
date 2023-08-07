from uuid import UUID

import pytest
from databases import Database

from rctab.crud.auth import check_user_access
from tests.test_routes.test_routes import test_db  # pylint: disable=unused-import

# pylint: disable=redefined-outer-name
# pylint: disable=unused-argument


@pytest.mark.asyncio
async def test_check_user_access(test_db: Database) -> None:
    """
    Test the check_user_access function in the crud module.
    """
    result = await check_user_access(str(UUID(int=880)), "me@my.org", False)
    assert result.username == "me@my.org"
