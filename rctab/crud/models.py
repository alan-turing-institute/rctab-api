from typing import List, Mapping, Sequence, Tuple

import asyncpg
import databases
import sqlalchemy
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import ClauseElement

from rctab.settings import get_settings

DATABASE_URL = get_settings().postgres_dsn

database = databases.Database(str(DATABASE_URL), force_rollback=get_settings().testing)


def _compile(
    _database: databases.Database, query: ClauseElement, values: Sequence[Mapping]
) -> Tuple[str, List[list]]:
    # pylint: disable=W0212
    compiled = query.compile(dialect=_database._backend._dialect)
    compiled_params = sorted(compiled.params.items())

    sql_mapping = {}
    param_mapping = {}
    for i, (key, _) in enumerate(compiled_params):
        sql_mapping[key] = "$" + str(i + 1)
        param_mapping[key] = i
    compiled_query = compiled.string % sql_mapping

    processors = compiled._bind_processors
    args = []
    for dikt in values:
        series = [None] * len(compiled_params)
        args.append(series)
        for key, val in dikt.items():
            series[param_mapping[key]] = (
                processors[key](val) if key in processors else val
            )

    return compiled_query, args


async def executemany(
    _database: databases.Database, query: ClauseElement, values: Sequence[Mapping]
) -> None:

    sql, args = _compile(_database, query, values)
    async with _database.connection() as connection:
        assert isinstance(connection.raw_connection, asyncpg.Connection)
        await connection.raw_connection.executemany(sql, args)


metadata = sqlalchemy.MetaData()

user_cache = sqlalchemy.Table(
    "user_cache",
    metadata,
    sqlalchemy.Column("oid", UUID(as_uuid=True), primary_key=True),
    sqlalchemy.Column("cache", sqlalchemy.Text, nullable=False),
)

# Hash of all usage data files
user_rbac = sqlalchemy.Table(
    "user_rbac",
    metadata,
    sqlalchemy.Column("oid", UUID, primary_key=True),
    sqlalchemy.Column("username", sqlalchemy.Text, nullable=False),
    sqlalchemy.Column("has_access", sqlalchemy.Boolean, nullable=False),
    sqlalchemy.Column("is_admin", sqlalchemy.Boolean, nullable=False),
)
