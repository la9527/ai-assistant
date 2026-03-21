"""스킬 레지스트리 — 등록된 스킬 목록 관리와 의도 매칭."""

from __future__ import annotations

import re
from typing import Sequence

from app.skills.base import BaseSkill
from app.skills.base import SkillDescriptor


# ---------------------------------------------------------------------------
# 레지스트리 관리
# ---------------------------------------------------------------------------

_SKILL_REGISTRY: list[SkillDescriptor] = []
_SKILL_RUNTIME_REGISTRY: dict[str, BaseSkill] = {}


def register_skill(descriptor: SkillDescriptor) -> None:
    """스킬을 레지스트리에 추가한다."""
    existing = get_skill_by_id(descriptor.skill_id)
    if existing is not None:
        index = _SKILL_REGISTRY.index(existing)
        _SKILL_REGISTRY[index] = descriptor
        return
    _SKILL_REGISTRY.append(descriptor)


def register_skill_runtime(skill: BaseSkill) -> None:
    """실행 가능한 스킬 구현체를 등록한다."""
    descriptor = skill.descriptor()
    register_skill(descriptor)
    _SKILL_RUNTIME_REGISTRY[descriptor.skill_id] = skill


def get_registry() -> list[SkillDescriptor]:
    """현재 등록된 전체 스킬 목록을 반환한다."""
    return list(_SKILL_REGISTRY)


def get_skill_by_id(skill_id: str) -> SkillDescriptor | None:
    """skill_id로 스킬을 찾는다."""
    for skill in _SKILL_REGISTRY:
        if skill.skill_id == skill_id:
            return skill
    return None


def get_skill_runtime(skill_id: str) -> BaseSkill | None:
    """skill_id로 실행 가능한 스킬 구현체를 찾는다."""
    return _SKILL_RUNTIME_REGISTRY.get(skill_id)


def get_enabled_skills(domain: str | None = None) -> list[SkillDescriptor]:
    """활성화된 스킬 목록을 반환한다."""
    return [
        skill
        for skill in _SKILL_REGISTRY
        if skill.enabled and (domain is None or skill.domain == domain)
    ]


# ---------------------------------------------------------------------------
# 키워드 기반 의도 매칭
# ---------------------------------------------------------------------------


def match_skills_by_keywords(message: str) -> list[tuple[SkillDescriptor, float]]:
    """메시지에서 트리거 키워드를 매칭해 후보 스킬 목록을 반환한다.

    Returns:
        (SkillDescriptor, score) 목록. score가 높은 순 정렬.
    """
    lowered = message.lower()
    results: list[tuple[SkillDescriptor, float]] = []

    for skill in _SKILL_REGISTRY:
        if not skill.enabled:
            continue
        matched = sum(1 for kw in skill.trigger_keywords if kw.lower() in lowered)
        if matched == 0:
            continue
        # 절대 매칭 횟수를 기본 점수로 사용하고, 비율을 보조 점수로 활용한다.
        ratio = matched / max(len(skill.trigger_keywords), 1)
        score = matched + ratio
        results.append((skill, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def classify_intent_from_registry(message: str) -> str | None:
    """레지스트리 기반으로 의도를 분류한다.

    매칭 후보가 없으면 None을 반환하고, 호출자가 기존
    classify_message_intent 결과를 사용할 수 있도록 한다.
    """
    candidates = match_skills_by_keywords(message)
    if not candidates:
        return None

    if len(candidates) > 1:
        top_skill, top_score = candidates[0]
        next_skill, next_score = candidates[1]
        if (
            top_skill.domain == "mail"
            and next_skill.domain == "mail"
            and top_score - next_score < 0.25
        ):
            return None

    # 최고 점수 후보가 유일하거나 확실하면 바로 반환
    top_skill, top_score = candidates[0]
    if top_score > 0 and (len(candidates) == 1 or top_score > candidates[1][1]):
        return top_skill.skill_id

    # 동점인 경우 기존 classify_message_intent에 위임 (None 반환)
    return None


# ---------------------------------------------------------------------------
# 초기화: 각 도메인 모듈의 스킬을 등록한다
# ---------------------------------------------------------------------------

def _auto_discover() -> None:
    """도메인별 스킬 모듈에서 SKILLS 리스트를 가져와 등록한다."""
    # 순환 임포트 방지를 위해 함수 내부에서 임포트
    from app.skills.calendar.descriptor import SKILLS as calendar_skills
    from app.skills.calendar.implementation import SKILL_IMPLEMENTATIONS as calendar_skill_implementations
    from app.skills.browser.implementation import SKILL_IMPLEMENTATIONS as browser_skill_implementations
    from app.skills.mail.descriptor import SKILLS as mail_skills
    from app.skills.mail.implementation import SKILL_IMPLEMENTATIONS as mail_skill_implementations
    from app.skills.macos.implementation import SKILL_IMPLEMENTATIONS as macos_skill_implementations
    from app.skills.note.descriptor import SKILLS as note_skills
    from app.skills.note.implementation import SKILL_IMPLEMENTATIONS as note_skill_implementations
    from app.skills.macos.descriptor import SKILLS as macos_skills
    from app.skills.search.descriptor import SKILLS as search_skills
    from app.skills.search.implementation import SKILL_IMPLEMENTATIONS as search_skill_implementations
    from app.skills.browser.descriptor import SKILLS as browser_skills

    for skill in (*calendar_skills, *mail_skills, *note_skills, *macos_skills, *search_skills, *browser_skills):
        register_skill(skill)
    for skill in (
        *calendar_skill_implementations,
        *mail_skill_implementations,
        *browser_skill_implementations,
        *macos_skill_implementations,
        *note_skill_implementations,
        *search_skill_implementations,
    ):
        register_skill_runtime(skill)


def ensure_initialized() -> None:
    """레지스트리가 비어 있으면 자동 탐색을 실행한다."""
    if not _SKILL_REGISTRY:
        _auto_discover()
