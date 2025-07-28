# app/models/shift.py
from pydantic import BaseModel
from typing import List
from app.utils.image_parser import ShiftInfo

class RegisterShiftsPayload(BaseModel):
    line_user_id: str
    workplace_id: str
    pending_id: str # どの保留データに基づくか
    shifts_to_register: List[ShiftInfo]