"""Pydantic validation gates. Invalid payloads go to raw.rejects, never crash the run."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, ValidationError


class Money(BaseModel):
    amount: str


class MoneySet(BaseModel):
    shopMoney: Money


class Ref(BaseModel):
    id: str


class OrderRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    createdAt: datetime
    processedAt: datetime
    updatedAt: datetime
    currencyCode: str
    totalPriceSet: MoneySet
    subtotalPriceSet: MoneySet
    customer: Optional[Ref] = None


class ProductRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    status: str
    createdAt: datetime
    updatedAt: datetime


class CustomerRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    displayName: str
    createdAt: datetime
    updatedAt: datetime


MODELS = {
    "orders": OrderRecord,
    "products": ProductRecord,
    "customers": CustomerRecord,
}


def validate_record(entity, record):
    """Returns (True, None) or (False, short_reason)."""
    try:
        MODELS[entity].model_validate(record)
        return True, None
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return False, f"{loc}: {first['msg']}"
