from __future__ import annotations
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from email_validator import validate_email, EmailNotValidError


def address(value: str) -> str:
    try:
        result = validate_email(value.strip(), check_deliverability=False, allow_smtputf8=False)
    except EmailNotValidError:
        raise ValueError('请输入有效的邮箱地址（不支持中文邮箱用户名）') from None
    return result.normalized.lower()

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_max_length=50000)

class PasswordInput(Input):
    password: str = Field(min_length=12, max_length=128)

class ProfileInput(Input):
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=255, pattern=r'^[A-Za-z0-9.\-:]+$')
    port: int = Field(ge=1, le=65535)
    security: Literal['ssl','starttls']
    username: str = Field(min_length=1, max_length=254)
    sender_name: str = Field(min_length=1, max_length=100)
    sender_email: str
    reply_to: str = ''
    password: str | None = Field(default=None, max_length=1024)
    is_default: bool = False
    default_concurrency: int = Field(default=1, ge=1, le=5, strict=True)
    default_interval: int = Field(default=3, ge=1, le=60, strict=True)

    @field_validator('sender_email')
    @classmethod
    def email(cls,v): return address(v)

    @field_validator('reply_to')
    @classmethod
    def reply(cls,v): return address(v) if v else ''

    @field_validator('name','host','username','sender_name')
    @classmethod
    def no_headers(cls,v):
        if not v.strip() or '\r' in v or '\n' in v: raise ValueError('内容不能为空或包含换行符')
        return v.strip()

class NameInput(Input):
    name: str = Field(min_length=1, max_length=100)
    @field_validator('name')
    @classmethod
    def clean(cls,v):
        if not v.strip() or '\r' in v or '\n' in v: raise ValueError('名称不能为空或包含换行符')
        return v.strip()

class StudentInput(NameInput):
    email: str
    @field_validator('email')
    @classmethod
    def email_valid(cls,v): return address(v)

class ImportConfirm(Input):
    preview_id: str
    valid_only: bool = False
    overwrite_conflicts: bool = False

class NoticeInput(Input):
    subject: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    course: str = Field(min_length=1, max_length=100)
    assignment: str = Field(min_length=1, max_length=150)
    deadline: str = Field(min_length=1, max_length=60)
    submission_email: str = Field(min_length=1, max_length=254)
    delta: dict
    profile_id: str = ''
    class_id: str = ''
    student_ids: list[str] = Field(default_factory=list, max_length=5000)
    interval: int = Field(default=3, ge=1, le=60, strict=True)
    concurrency: int = Field(default=1, ge=1, le=5, strict=True)

    @field_validator('deadline')
    @classmethod
    def valid_deadline(cls,v):
        from datetime import datetime
        try:
            if len(v)<16: raise ValueError()
            parsed=datetime.fromisoformat(v)
            if parsed.tzinfo:
                from zoneinfo import ZoneInfo
                parsed=parsed.astimezone(ZoneInfo('Asia/Shanghai'))
        except ValueError: raise ValueError('截止时间需为明确的日期和时间') from None
        return parsed.strftime('%Y-%m-%dT%H:%M')

    @field_validator('submission_email')
    @classmethod
    def submission_address(cls,v):
        return address(v)

    @field_validator('subject','title','course','assignment','deadline')
    @classmethod
    def field_clean(cls,v):
        if not v.strip() or '\r' in v or '\n' in v: raise ValueError('内容不能为空或包含换行符')
        return v.strip()

class TemplateInput(Input):
    name: str = Field(min_length=1,max_length=100)
    subject: str = Field(min_length=1,max_length=200)
    title: str = Field(min_length=1,max_length=200)
    delta: dict

class PreviewInput(Input):
    notice: NoticeInput
    student_id: str | None = None

class TestInput(PreviewInput):
    to: str
    @field_validator('to')
    @classmethod
    def email_valid(cls,v): return address(v)

class SendInput(Input):
    notice: NoticeInput
    idempotency_key: str = Field(min_length=16,max_length=100,pattern=r'^[A-Za-z0-9_\-]+$')

class RetryInput(Input):
    idempotency_key: str = Field(min_length=16,max_length=100,pattern=r'^[A-Za-z0-9_\-]+$')

class DraftInput(Input):
    content: dict
    @field_validator('content')
    @classmethod
    def valid_content(cls,v):
        from .compat import draft_content
        v=draft_content(v)
        allowed=set(NoticeInput.model_fields)
        if set(v)-allowed: raise ValueError('草稿包含未知字段')
        for key,value in v.items():
            if key=='delta':
                from .rendering import validate_delta
                if value != {'ops':[{'insert':'\n'}]}: validate_delta(value)
            elif key=='student_ids':
                if not isinstance(value,list) or len(value)>5000 or any(not isinstance(x,str) or len(x)>100 for x in value): raise ValueError('草稿收件人格式错误')
            elif key=='interval':
                if type(value) is not int or not 1<=value<=60: raise ValueError('发送间隔格式错误')
            elif key=='concurrency':
                if type(value) is not int or not 1<=value<=5: raise ValueError('并发数需为 1–5 的整数')
            elif not isinstance(value,str) or len(value)>5000: raise ValueError('草稿字段格式错误或过长')
        return v
