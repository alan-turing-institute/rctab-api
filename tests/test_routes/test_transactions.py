import pytest
from databases import Database
from sqlalchemy import select

from rctab.crud.accounting_models import subscription
from rctab.settings import get_settings
from tests.test_routes.test_routes import create_subscription
from tests.test_routes.utils import no_rollback_test_db  # pylint: disable=unused-import

settings = get_settings()


@pytest.mark.asyncio
async def test_databases_rollback(
    no_rollback_test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check that our databases library allows rollbacks."""

    # This bug only shows up after at least one statement has been executed
    await no_rollback_test_db.execute("select 1")

    transaction = await no_rollback_test_db.transaction()

    await create_subscription(no_rollback_test_db)

    # Should remove the subscription
    await transaction.rollback()

    results = await no_rollback_test_db.fetch_all(select(subscription))

    assert len(results) == 0
