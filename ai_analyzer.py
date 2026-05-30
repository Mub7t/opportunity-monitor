"""
ai_analyzer.py — AI-powered project analysis using OpenAI or Anthropic.

v3 additions:
  - Profile-aware system prompt using Mubarak's SKILL_DOMAINS
  - Retry logic with exponential back-off
  - Rate limiting protection

For each new project the analyzer returns:
  - summary        : concise Arabic summary
  - category       : project category
  - skills         : recommended skills (list)
  - score          : suitability 0-100
  - score_reason   : why this score
  - win_chance     : AI estimated chance (low/medium/high) — used as minor input only
  - profitability  : estimated profitability (low/medium/high)
  - urgency        : urgency level (low/medium/high)
  - recommendation : Apply | Consider | Skip
"""

import json
import logging
import time

from config import (
    AI_ENABLED, AI_PROVIDER, OPENAI_API_KEY, ANTHROPIC_API_KEY, AI_MODEL,
    USER_PROFILE, SKILL_DOMAINS, AI_MAX_RETRIES, RATE_LIMIT_DELAY_S,
)

log = logging.getLogger(__name__)

# Build a compact skill list string for the prompt
_CORE_SKILLS = ", ".join(
    k for k, v in sorted(SKILL_DOMAINS.items(), key=lambda x: -x[1]) if v >= 0.85
)

_SYSTEM_PROMPT = f"""
أنت مساعد ذكي متخصص في تحليل مشاريع المستقلين على المنصات العربية.

معلومات المستخدم (مبارك):
  الاسم: {USER_PROFILE['name']}
  التخصصات الأساسية: {_CORE_SKILLS}
  جميع المهارات: {USER_PROFILE['skills']}
  الخبرة: {USER_PROFILE['experience']}

تعليمات التقييم:
  - المشاريع التي تتطابق مع التخصصات الأساسية (تصوير، فيديو، موشن، تصميم، تطوير ويب، AI، أتمتة) → score أعلى
  - المشاريع خارج هذه المجالات → score أقل حتى لو كانت كبيرة مالياً
  - win_chance هو تقدير نوعي فقط — ليس الاحتمال الفعلي

مهمتك: تحليل المشروع المرسل وإرجاع JSON فقط بالشكل الآتي (بدون أي نص خارجه):
{{
  "summary": "ملخص قصير للمشروع بالعربية (جملة أو جملتان)",
  "category": "الفئة (مثل: تصميم جرافيك، تطوير ويب، إنتاج فيديو، ذكاء اصطناعي، ...)",
  "skills": ["مهارة1", "مهارة2"],
  "score": 75,
  "score_reason": "سبب النقاط بجملة واحدة",
  "win_chance": "medium",
  "profitability": "high",
  "urgency": "low",
  "recommendation": "Apply"
}}

قواعد:
- score بين 0 و 100. يرتفع كلما تطابق المشروع مع تخصصات مبارك وكلما كان مربحًا.
- win_chance: low | medium | high  (تقدير نوعي فقط)
- profitability: low | medium | high
- urgency: low | medium | high
- recommendation: Apply (score≥70) | Consider (40-69) | Skip (<40)
- أجب بـ JSON صالح فقط، بدون markdown أو backticks.
""".strip()


def _call_openai(project_text: str) -> dict:
    import urllib.request
    payload = json.dumps({
        "model":    AI_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": project_text},
        ],
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return json.loads(data["choices"][0]["message"]["content"])


def _call_anthropic(project_text: str) -> dict:
    import urllib.request
    payload = json.dumps({
        "model":      "claude-haiku-4-5-20251001",
        "max_tokens": 512,
        "system":     _SYSTEM_PROMPT,
        "messages":   [{"role": "user", "content": project_text}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return json.loads(data["content"][0]["text"])


def _default_analysis(project: dict | None = None) -> dict:
    # Use pre-detected category_hint when AI is off or fails
    category = (project or {}).get("category_hint", "") or "غير محدد"
    return {
        "summary":        "",
        "category":       category,
        "skills":         [],
        "score":          50,
        "score_reason":   "لم يتم التحليل",
        "win_chance":     "medium",
        "profitability":  "medium",
        "urgency":        "low",
        "recommendation": "Consider",
    }


def _validate(result: dict) -> dict:
    """Validate and clamp AI response fields."""
    for key in ("score", "recommendation", "summary"):
        if key not in result:
            raise ValueError(f"Missing key '{key}' in AI response")
    result["score"] = max(0, min(100, int(result["score"])))
    result["win_chance"]    = result.get("win_chance", "medium").lower()
    result["profitability"] = result.get("profitability", "medium").lower()
    result["urgency"]       = result.get("urgency", "low").lower()
    if result["win_chance"]    not in ("low", "medium", "high"): result["win_chance"]    = "medium"
    if result["profitability"] not in ("low", "medium", "high"): result["profitability"] = "medium"
    if result["urgency"]       not in ("low", "medium", "high"): result["urgency"]       = "low"
    return result


def analyze_project(project: dict) -> dict:
    """
    Analyze a project with AI. Returns analysis dict.
    Includes retry logic and rate-limit protection.
    Falls back to defaults if AI is disabled or all retries fail.
    """
    if not AI_ENABLED:
        return _default_analysis(project)

    project_text = (
        f"عنوان المشروع: {project.get('title', '')}\n"
        f"الوصف: {project.get('description', project.get('raw_text', ''))[:800]}\n"
        f"الرابط: {project.get('url', '')}"
    )

    call_fn = _call_anthropic if AI_PROVIDER == "anthropic" else _call_openai

    for attempt in range(1, AI_MAX_RETRIES + 2):
        try:
            # Rate limiting: small delay between calls
            if attempt > 1:
                delay = RATE_LIMIT_DELAY_S * (2 ** (attempt - 2))
                log.info("AI retry %d/%d in %.1fs …", attempt, AI_MAX_RETRIES + 1, delay)
                time.sleep(delay)

            result = _validate(call_fn(project_text))

            # If AI returned blank/default category, use the pre-detected hint
            if not result.get("category") or result["category"] in ("غير محدد", ""):
                hint = project.get("category_hint", "")
                if hint:
                    result["category"] = hint

            log.info(
                "AI analysis for '%s': score=%d, rec=%s, category=%s",
                project.get("title", "")[:40], result["score"],
                result["recommendation"], result.get("category", "—"),
            )
            return result

        except Exception as exc:
            log.warning(
                "AI analysis attempt %d failed for '%s': %s",
                attempt, project.get("title", "")[:40], exc
            )
            if attempt > AI_MAX_RETRIES:
                log.error("All AI retries exhausted for '%s'. Using defaults.", project.get("title", "")[:40])
                return _default_analysis(project)

    return _default_analysis(project)
