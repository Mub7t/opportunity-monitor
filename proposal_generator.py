"""
proposal_generator.py — Generate professional Arabic proposals for matching projects.

Uses AI when enabled, falls back to template-based generation.
"""

import logging
from config import AI_ENABLED, AI_PROVIDER, OPENAI_API_KEY, ANTHROPIC_API_KEY, AI_MODEL, USER_PROFILE

log = logging.getLogger(__name__)


_PROPOSAL_CATEGORIES = {
    "تصوير": "تصوير",
    "فيديو": "إنتاج فيديو",
    "مونتاج": "مونتاج",
    "موشن": "موشن جرافيك",
    "تصميم": "تصميم",
    "جرافيك": "تصميم جرافيك",
    "هوية": "هوية بصرية",
    "موقع": "تطوير ويب",
    "برمجة": "تطوير",
    "تطبيق": "تطوير تطبيقات",
    "ذكاء اصطناعي": "ذكاء اصطناعي",
    "أتمتة": "أتمتة",
    "automation": "أتمتة",
    "AI": "ذكاء اصطناعي",
}


def _detect_domain(project: dict) -> str:
    text = (project.get("title", "") + " " + project.get("raw_text", "")).lower()
    for kw, domain in _PROPOSAL_CATEGORIES.items():
        if kw.lower() in text:
            return domain
    return "خدمات متكاملة"


def _template_proposal(project: dict) -> str:
    domain  = _detect_domain(project)
    name    = USER_PROFILE.get("name", "")
    exp     = USER_PROFILE.get("experience", "")
    skills  = USER_PROFILE.get("skills", "")
    title   = project.get("title", "المشروع")

    return (
        f"السلام عليكم،\n\n"
        f"اطلعت على مشروعكم \"{title}\" وأرى أنني مؤهل لتنفيذه بكفاءة عالية.\n\n"
        f"أنا {name}، متخصص في {domain} مع خبرة {exp} في {skills}.\n\n"
        f"سأقدم لكم:\n"
        f"• نتائج احترافية تلبي متطلباتكم بدقة\n"
        f"• التزام كامل بالمواعيد المتفق عليها\n"
        f"• تواصل مستمر طوال مراحل التنفيذ\n"
        f"• تعديلات مجانية حتى رضاكم التام\n\n"
        f"يسعدني مناقشة التفاصيل والبدء فورًا.\n\n"
        f"مع التقدير،\n{name}"
    )


def _ai_proposal(project: dict) -> str:
    import json
    import urllib.request

    prompt = (
        f"اكتب عرضًا احترافيًا مختصرًا باللغة العربية لمشروع مستقل.\n"
        f"المشروع: {project.get('title', '')}\n"
        f"الوصف: {project.get('description', project.get('raw_text', ''))[:400]}\n\n"
        f"معلومات المقدم:\n"
        f"الاسم: {USER_PROFILE.get('name', '')}\n"
        f"التخصصات: {USER_PROFILE.get('skills', '')}\n"
        f"الخبرة: {USER_PROFILE.get('experience', '')}\n\n"
        f"المتطلبات:\n"
        f"- نبرة احترافية ومقنعة\n"
        f"- قصير (150-200 كلمة)\n"
        f"- جاهز للنسخ واللصق مباشرة\n"
        f"- ابدأ بالتحية ولا تضع عنوانًا\n"
        f"- لا تضع markdown"
    )

    try:
        if AI_PROVIDER == "anthropic":
            payload = json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            return data["content"][0]["text"].strip()
        else:
            payload = json.dumps({
                "model": AI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.6,
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()

    except Exception as exc:
        log.warning("AI proposal generation failed: %s. Using template.", exc)
        return _template_proposal(project)


def generate_proposal(project: dict) -> str:
    """Generate an Arabic proposal for the given project."""
    if AI_ENABLED:
        return _ai_proposal(project)
    return _template_proposal(project)
