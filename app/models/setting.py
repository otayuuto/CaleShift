# app/models/setting.py

from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime

# --- 共通の型定義 ---
DateFormatType = Literal[
    "YYYY/MM/DD",
    "MM/DD",
    "MM月DD日",
    "DD日 (曜日)",
    "DD",
]

TimeFormatType = Literal[
    "HH:MM-HH:MM",
    "HH-HH",
    "HH時～HH時",
    "開始時刻と終了時刻が別々の欄",
    "H",
]

RestIndicatorType = Literal[
    "休",
    "OFF",
    "×",
    "／",
    "空白セル",
    "指定なし",
]

class DateRule(BaseModel):
    format_type: DateFormatType
    custom_description: Optional[str] = None

class TimeRule(BaseModel):
    format_type: TimeFormatType
    rest_indicators: List[RestIndicatorType] = Field(default_factory=list)
    custom_description: Optional[str] = None

# --- バイト先の共通情報に関するモデル ---
class WorkplaceBase(BaseModel):
    workplace_name: str = Field(..., min_length=1, description="バイト先の名前")

class WorkplaceSharedSettings(BaseModel):
    date_rules: DateRule
    time_rules: TimeRule

class WorkplaceCreatePayload(WorkplaceBase): # APIリクエストボディ用
    settings: WorkplaceSharedSettings
    current_line_user_id: str # このバイト先情報を登録するユーザーのID

class WorkplaceResponse(WorkplaceBase): # APIレスポンス用
    workplace_id: str = Field(..., description="Firestoreでのバイト先ドキュメントID")
    settings: WorkplaceSharedSettings
    created_by_user_id: str = Field(..., description="このバイト先情報を最初に登録したユーザーのID")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- ユーザーごとの、特定のバイト先に対する設定に関するモデル ---
class MyWorkplaceSettingBase(BaseModel):
    target_name_in_shift: str = Field(..., min_length=1, description="このバイト先のシフト表における自分の名前")

class MyWorkplaceSettingCreatePayload(MyWorkplaceSettingBase): # APIリクエストボディ用
    pass

class MyWorkplaceSettingResponse(MyWorkplaceSettingBase): # APIレスポンス用
    workplace_id: str = Field(..., description="対象となるバイト先のID")
    line_user_id: str = Field(..., description="この設定の持ち主であるユーザーのID")
    linked_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True