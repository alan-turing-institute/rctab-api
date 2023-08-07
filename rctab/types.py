from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Generator


class Currency(str, Enum):

    USD = "USD"
    GBP = "GBP"


class CurrencyCoversion(float, Enum):

    USD = 1.0
    GBP = 1.33501


class InputFileType(str, Enum):

    EDUHUB = "eduhub"
    SPONSORSHIP = "sponsorship"
    COVID = "covid"


@dataclass
class ValidatedFileInfo:
    end_date: date
    file_type: InputFileType


@dataclass
class StartEndDate:
    start_date: date
    end_date: date


class DateFirst(date):
    """
    A date that must be before '2018-10-01'
    """

    @classmethod
    def __get_validators__(cls) -> Generator:
        yield cls.validate

    @classmethod
    def validate(cls, v: Any) -> date:

        v_date = date.fromisoformat(v)
        if v_date < date(2018, 10, 1):
            raise ValueError("Must be from 2018-10-01 or later")

        return v_date
