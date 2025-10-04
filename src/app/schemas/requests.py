from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class QuoteRequest(BaseModel):
    symbol: str


class OrderbookRequest(BaseModel):
    symbol: str
    depth: int = Field(default=10, ge=1, le=100)


class BarsRequest(BaseModel):
    symbol: str
    timeframe: str
    start: Optional[str] = None
    end: Optional[str] = None


class TradesLatestRequest(BaseModel):
    symbol: str


class AccountRequest(BaseModel):
    account_id: str


class OrdersListRequest(BaseModel):
    account_id: str


class OrderGetRequest(BaseModel):
    account_id: str
    order_id: str


class TradesRequest(BaseModel):
    account_id: str
    start: Optional[str] = None
    end: Optional[str] = None


class TransactionsRequest(BaseModel):
    account_id: str
    start: Optional[str] = None
    end: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1, le=1000)


class OrderCreate(BaseModel):
    instrument: str
    side: str
    type: str
    quantity: int
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: Optional[str] = None


class OrderCreateRequest(BaseModel):
    account_id: str
    order: OrderCreate


class OrderCancelRequest(BaseModel):
    account_id: str
    order_id: str


class SessionDetailsRequest(BaseModel):
    pass


class SessionCreateRequest(BaseModel):
    pass


class SystemTimeRequest(BaseModel):
    pass



class AssetsListRequest(BaseModel):
    pass


class ExchangesListRequest(BaseModel):
    pass


class AssetInfoRequest(BaseModel):
    symbol: str


class AssetParamsRequest(BaseModel):
    symbol: str
    account_id: Optional[str] = None


class AssetScheduleRequest(BaseModel):
    symbol: str


class AssetOptionsRequest(BaseModel):
    symbol: str


