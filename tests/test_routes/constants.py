import uuid
from typing import Final

ADMIN_UUID: Final = uuid.UUID("a75693be-1d36-11ec-9621-0242ac130002")
ADMIN_NAME: Final = "Tester"
ADMIN_DICT: Final = {"admin": ADMIN_UUID}

# TEST_SUB_2_UUID exists in tests/data/example.json
TEST_SUB_UUID: Final = uuid.UUID("3fbe12f6-1d39-11ec-9621-0242ac130002")
TEST_SUB_2_UUID: Final = uuid.UUID("ce0f6ae0-2032-11ec-9621-0242ac130002")
