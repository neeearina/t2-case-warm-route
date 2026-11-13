from typing import Literal
from pydantic import AwareDatetime, BaseModel, Field, ConfigDict


class Report(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    external_id: str = Field(min_length=1, max_length=100)
    occurred_at: AwareDatetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    category: Literal['ice', 'snow', 'delay']
    text: str = Field(min_length=1, max_length=2000)
    synthetic: bool = False


class Context(BaseModel):
    segment_id: int
    observed_at: AwareDatetime
    value: float = Field(ge=0, le=1)
    synthetic: bool


class StatusChange(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    status: Literal['ACTIVE', 'RESOLVED', 'RECHECK', 'CLOSED']
    reason: str = Field(min_length=1, max_length=500)


class TransportSample(BaseModel):
    external_id: str
    segment_id: int
    observed_at: AwareDatetime
    delay_minutes: float = Field(ge=0, le=180)
