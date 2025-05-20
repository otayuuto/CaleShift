from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime

# 日付形式の選択肢 (Enumのように使う)
DateFormatType = Literal[
    "YYYY/MM/DD",
    "MM/DD",
    "MM月DD日",
    "DD日 (曜日)",
]

# 時間形式の選択肢 (Enumのように使う)
TimeFormatType = Literal[
    "HH:MM-HH:MM",
    "HH-HH",
    "HH時～HH時",
    "開始時刻と終了時刻が別々の欄",
]

# 休みの表記の選択肢 (Enumのように使う)
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

class WorkplaceSettingsPayload(BaseModel):
    """LIFFから送信される設定内容の基本部分"""
    target_name: str = Field(..., min_length=1, description="シフト表に記載されている名前")
    date_rules: DateRule
    time_rules: TimeRule

class WorkplaceCreate(BaseModel):
    """新しいバイト先設定を作成する際にLIFFから送信されるデータ全体"""
    workplace_name: str = Field(..., min_length=1, description="バイト先の名前")
    settings: WorkplaceSettingsPayload

class WorkplaceResponse(WorkplaceCreate):
    """Firestoreから読み込んだバイト先設定情報（IDやタイムスタンプを含む）"""
    workplace_id: str = Field(..., description="Firestoreでのバイト先ドキュメントID")
    line_user_id: str # どのユーザーの設定かを示す
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True # Firestoreのドキュメントオブジェクトから変換しやすくする
        # from_attributes = True # Pydantic V2