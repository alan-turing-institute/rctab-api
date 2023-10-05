"""Pydantic models for the RCTab API."""
import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, confloat


# pylint: disable=W0613
class HashBaseModel(BaseModel):
    """BaseModel with hash.

    This allows unique data generation for property based tests.
    """

    def __hash__(self) -> int:
        """Hash the object."""
        return hash((type(self),) + tuple(self.__dict__.values()))


class UserRBAC(BaseModel):
    """The access that a user has to RCTab."""

    oid: UUID
    username: Optional[str]
    has_access: bool
    is_admin: bool


class Usage(HashBaseModel):
    """A usage object from the Azure usage API."""

    # See https://docs.microsoft.com/en-us/rest/api/consumption/usage-details/list#legacyusagedetail
    id: str
    name: Optional[str]
    type: Optional[str]
    tags: Optional[Dict[str, str]]
    billing_account_id: Optional[str]
    billing_account_name: Optional[str]
    billing_period_start_date: Optional[datetime.date]
    billing_period_end_date: Optional[datetime.date]
    billing_profile_id: Optional[str]
    billing_profile_name: Optional[str]
    account_owner_id: Optional[str]
    account_name: Optional[str]
    subscription_id: UUID
    subscription_name: Optional[str]
    date: datetime.date
    product: Optional[str]
    part_number: Optional[str]
    meter_id: Optional[str]
    quantity: Optional[float]
    effective_price: Optional[float]
    cost: Optional[float]
    amortised_cost: Optional[float]
    total_cost: float
    unit_price: Optional[float]
    billing_currency: Optional[str]
    resource_location: Optional[str]
    consumed_service: Optional[str]
    resource_id: Optional[str]
    resource_name: Optional[str]
    service_info1: Optional[str]
    service_info2: Optional[str]
    additional_info: Optional[str]
    invoice_section: Optional[str]
    cost_center: Optional[str]
    resource_group: Optional[str]
    reservation_id: Optional[str]
    reservation_name: Optional[str]
    product_order_id: Optional[str]
    offer_id: Optional[str]
    is_azure_credit_eligible: Optional[bool]
    term: Optional[str]
    publisher_name: Optional[str]
    publisher_type: Optional[str]
    plan_name: Optional[str]
    charge_type: Optional[str]
    frequency: Optional[str]
    monthly_upload: Optional[datetime.date]


class AllUsage(BaseModel):
    """A wrapper for a list of Usage objects."""

    usage_list: List[Usage]


class CMUsage(HashBaseModel):
    """A usage object from the Azure cost management API."""

    subscription_id: UUID
    name: Optional[str]
    start_datetime: datetime.date
    end_datetime: datetime.date
    cost: confloat(ge=0.0)  # type: ignore
    billing_currency: str


class AllCMUsage(BaseModel):
    """A wrapper for a list of CMUsage objects."""

    cm_usage_list: List[CMUsage]


class RoleAssignment(HashBaseModel):
    """A role assignment on Azure."""

    role_definition_id: str
    role_name: str
    principal_id: str
    display_name: str
    mail: Optional[str]
    scope: Optional[str]


class SubscriptionState(str, Enum):
    """The current state of a subscription."""

    # See https://docs.microsoft.com/en-us/azure/cost-management-billing/manage/subscription-states
    DELETED = "Deleted"
    DISABLED = "Disabled"
    ENABLED = "Enabled"
    PASTDUE = "PastDue"
    WARNED = "Warned"
    EXPIRED = "Expired"


class SubscriptionStatus(HashBaseModel):
    """The current status of a subscription."""

    # See https://docs.microsoft.com/en-us/rest/api/resources/subscriptions/list#subscription
    subscription_id: UUID
    display_name: str
    state: SubscriptionState
    role_assignments: Tuple[RoleAssignment, ...]


class DesiredState(HashBaseModel):
    """The desired state of a subscription."""

    subscription_id: UUID
    desired_state: SubscriptionState


class AllSubscriptionStatus(HashBaseModel):
    """A wrapper for a list of SubscriptionStatus."""

    status_list: List[SubscriptionStatus]


class BillingStatus(str, Enum):
    """The reason for a subscription being disabled."""

    OVER_BUDGET = "OVER_BUDGET"
    EXPIRED = "EXPIRED"
    OVER_BUDGET_AND_EXPIRED = "OVER_BUDGET_AND_EXPIRED"


class SubscriptionDetails(HashBaseModel):
    """A summary of a subscription."""

    subscription_id: UUID
    name: Optional[str] = None
    role_assignments: Optional[Tuple[RoleAssignment, ...]] = None
    status: Optional[SubscriptionState] = None
    approved_from: Optional[datetime.date] = None
    approved_to: Optional[datetime.date] = None
    always_on: Optional[bool] = None
    approved: Optional[float] = None
    allocated: Optional[float] = None
    cost: Optional[float] = None
    amortised_cost: Optional[float] = None
    total_cost: Optional[float] = None
    remaining: Optional[float] = None
    first_usage: Optional[datetime.date] = None
    latest_usage: Optional[datetime.date] = None
    desired_status_info: Optional[BillingStatus]
    abolished: bool


DEFAULT_CURRENCY = "GBP"


class Allocation(BaseModel):
    """An amount that a subscription can spend from an approved budget."""

    sub_id: UUID
    ticket: str
    amount: float
    currency: str = DEFAULT_CURRENCY


class AllocationListItem(BaseModel):
    """A list of allocations with a time_created field."""

    ticket: str
    amount: float
    currency: str = DEFAULT_CURRENCY
    time_created: datetime.datetime


class Approval(BaseModel):
    """An amount that a subscription can spend in a given time period."""

    sub_id: UUID
    ticket: str
    amount: float
    currency: str = DEFAULT_CURRENCY
    allocate: bool = False
    date_from: datetime.date
    date_to: datetime.date
    force: bool = False


class ApprovalListItem(BaseModel):
    """An Approval with a time_created field."""

    ticket: str
    amount: float
    currency: str = DEFAULT_CURRENCY
    date_from: datetime.date
    date_to: datetime.date
    time_created: datetime.datetime


class Finance(BaseModel):
    """An amount that can be billed to finance_code in a given time period."""

    subscription_id: UUID
    ticket: str
    amount: float
    priority: int
    finance_code: str
    date_from: datetime.date
    date_to: datetime.date


class FinanceListItem(BaseModel):
    """A Finance with a time_created field."""

    ticket: str
    amount: float
    priority: int
    finance_code: str
    date_from: datetime.date
    date_to: datetime.date
    time_created: datetime.datetime


class FinanceWithID(Finance):
    """A Finance with a Finance ID."""

    id: int


class CostRecovery(BaseModel):
    """Costs that should, be recovered from finance_code."""

    finance_id: int
    subscription_id: UUID
    month: datetime.date
    finance_code: str
    amount: float
    date_recovered: Optional[datetime.date] = None


class Currency(str, Enum):
    """Recognised currencies."""

    USD = "USD"
    GBP = "GBP"
