# app/models/shift_history.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ShiftUpdatePayload(BaseModel):
    summary: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[datetime] = None # タイムゾーン付きのdatetime
    end_time: Optional[datetime] = None