"""Data protection declaration: public read, admin write.

``GET`` is deliberately unauthenticated so the declaration can be read from
the login screen; ``PUT`` needs the Admin Settings permission. The stored
HTML is sanitized on save (see ``domain.privacy``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from theme_boost_union_test_envs.cross_cutting.logger import log
from theme_boost_union_test_envs.domain import privacy

from ..security import require_settings_admin

router = APIRouter(prefix="/api/privacy", tags=["privacy"])


class PrivacyPage(BaseModel):
    html: str
    updated_at: str = ""
    updated_by: str = ""


class PrivacyUpdate(BaseModel):
    html: str = Field(max_length=privacy.MAX_HTML_LENGTH)


@router.get("", response_model=PrivacyPage)
def get_privacy_page() -> PrivacyPage:
    return PrivacyPage(**privacy.load())


@router.put("", response_model=PrivacyPage)
def put_privacy_page(
    payload: PrivacyUpdate,
    user: dict[str, Any] = Depends(require_settings_admin),
) -> PrivacyPage:
    name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    saved = privacy.save(payload.html, name or str(user.get("email", "")))
    log().info("data protection declaration updated by {}", user.get("email", "?"))
    return PrivacyPage(**saved)
