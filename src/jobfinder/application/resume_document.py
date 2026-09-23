"""Generate Eli's application-ready resume PDF from editable builder data."""
from __future__ import annotations

from html import escape
from pathlib import Path
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from jobfinder.config import ACTUAL_RESUME_PATH


INK = colors.HexColor("#13251e")
ACCENT = colors.HexColor("#1f7053")
MUTED = colors.HexColor("#53635d")
RULE = colors.HexColor("#b9c8c0")

DEFAULT_RESUME_CONTENT: dict[str, Any] = {
    "version": 1,
    "contact": {
        "name": "",
        "headline": "Senior Software Engineer",
        "location": "",
        "phone": "",
        "email": "",
        "linkedin": "",
        "linkedin_url": "",
    },
    "summary": "",
    "skills": {
        "Languages": "",
        "Platforms & Systems": "",
        "Leadership": "",
    },
    "experience": [],
    "education": [],
}


def _text(value: Any) -> str:
    return escape(str(value or "").strip())


def _emphasized_text(value: Any) -> str:
    text = _text(value)
    for phrase in (
        "distributed systems",
        "technical leadership",
        "production reliability",
        "cross-team architecture",
    ):
        safe_phrase = escape(phrase)
        text = re.sub(re.escape(safe_phrase), f"<b>{safe_phrase}</b>", text, flags=re.IGNORECASE)
    for pattern in (
        r"\b\d+(?:\.\d+)?%",
        r"\$\s?\d[\d,.]*[KMB]?\+?",
        r"\bP\d{2}\b",
        r"\b\d+(?:\.\d+)? seconds\b",
    ):
        text = re.sub(pattern, lambda match: f"<b>{match.group(0)}</b>", text, flags=re.IGNORECASE)
    return text


def _bullet(text: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    words = text.rsplit(" ", 1)
    if len(words) == 2 and len(words[1]) <= 24:
        text = f"{words[0]}\u00a0{words[1]}"
    return Paragraph(f"<bullet>&bull;</bullet>{_emphasized_text(text)}", styles["bullet"])


def build_actual_resume(data: dict[str, Any] | None = None, output_path: Path = ACTUAL_RESUME_PATH) -> Path:
    content = data or DEFAULT_RESUME_CONTENT
    contact = content.get("contact") or {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base = getSampleStyleSheet()
    styles = {
        "name": ParagraphStyle("Name", parent=base["Title"], fontName="Helvetica-Bold", fontSize=23, leading=25, textColor=INK, alignment=TA_CENTER, spaceAfter=3),
        "title": ParagraphStyle("Title", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=ACCENT, alignment=TA_CENTER, tracking=1.0, spaceAfter=4),
        "contact": ParagraphStyle("Contact", parent=base["Normal"], fontName="Helvetica", fontSize=8.8, leading=11, textColor=MUTED, alignment=TA_CENTER),
        "section": ParagraphStyle("Section", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=12, textColor=ACCENT, tracking=1.1, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("Body", parent=base["Normal"], fontName="Helvetica", fontSize=8.8, leading=11.3, textColor=INK, spaceAfter=3),
        "company": ParagraphStyle("Company", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9.8, leading=11.8, textColor=INK, spaceBefore=5, spaceAfter=1.5),
        "group_role_first": ParagraphStyle("GroupRoleFirst", parent=base["Normal"], fontName="Helvetica", fontSize=8.8, leading=10.8, textColor=MUTED, spaceAfter=3),
        "group_role": ParagraphStyle("GroupRole", parent=base["Normal"], fontName="Helvetica", fontSize=8.8, leading=10.8, textColor=MUTED, spaceBefore=4, spaceAfter=3),
        "role": ParagraphStyle("Role", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9.5, leading=11.5, textColor=INK, spaceBefore=4, spaceAfter=1),
        "meta": ParagraphStyle("Meta", parent=base["Normal"], fontName="Helvetica-Oblique", fontSize=8.4, leading=10.5, textColor=MUTED, spaceAfter=3),
        "bullet": ParagraphStyle("Bullet", parent=base["Normal"], fontName="Helvetica", fontSize=8.55, leading=10.8, textColor=INK, leftIndent=12, firstLineIndent=-7, bulletIndent=0, spaceAfter=2.2),
        "skills": ParagraphStyle("Skills", parent=base["Normal"], fontName="Helvetica", fontSize=8.55, leading=11.2, textColor=INK, spaceAfter=2),
    }

    full_name = str(contact.get("name") or "Candidate")
    headline = str(contact.get("headline") or "Senior Backend Software Engineer")

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(document.leftMargin, 0.43 * inch, letter[0] - document.rightMargin, 0.43 * inch)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(document.leftMargin, 0.27 * inch, f"{full_name} - {headline}")
        canvas.drawRightString(letter[0] - document.rightMargin, 0.27 * inch, f"Page {document.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(output_path), pagesize=letter, rightMargin=0.50 * inch, leftMargin=0.50 * inch, topMargin=0.48 * inch, bottomMargin=0.55 * inch, title=f"{full_name} - {headline}", author=full_name)
    contact_parts = [_text(contact.get(key)) for key in ("location", "phone", "email") if contact.get(key)]
    linkedin_label = contact.get("linkedin")
    linkedin_url = contact.get("linkedin_url")
    if linkedin_label:
        if linkedin_url:
            contact_parts.append(
                f'<link href="{_text(linkedin_url)}" color="#1f7053"><u>{_text(linkedin_label)}</u></link>'
            )
        else:
            contact_parts.append(_text(linkedin_label))
    contact_line = " &nbsp;|&nbsp; ".join(contact_parts)
    story: list[Any] = [
        Paragraph(_text(full_name).upper(), styles["name"]),
        Paragraph(_text(headline).upper(), styles["title"]),
        Paragraph(contact_line, styles["contact"]),
        Spacer(1, 5), HRFlowable(width="100%", thickness=1.1, color=ACCENT),
        Paragraph("<u>SUMMARY</u>", styles["section"]),
        Paragraph(_text(content.get("summary")), styles["body"]),
        Paragraph("<u>CORE SKILLS</u>", styles["section"]),
    ]
    for label, values in (content.get("skills") or {}).items():
        if values:
            story.append(Paragraph(f"<b>{_text(label)}:</b> {_text(values)}", styles["skills"]))

    story.append(Paragraph("<u>EXPERIENCE</u>", styles["section"]))
    active_group: tuple[str, str] | None = None
    for item in content.get("experience") or []:
        company = _text(item.get("company"))
        business_unit = _text(item.get("business_unit"))
        role = _text(item.get("role"))
        location = _text(item.get("location"))
        dates = _text(item.get("dates"))
        bullets = [str(value).strip() for value in item.get("bullets") or [] if str(value).strip()]
        group_key = (company.casefold(), business_unit.casefold())
        starts_group = group_key != active_group
        emphasized_role = f'<b><font color="#13251e">{role}</font></b>' if role else ""
        role_line = " | ".join(value for value in (emphasized_role, location, dates) if value)
        heading = []
        if starts_group:
            company_line = " - ".join(value for value in (company.upper(), business_unit) if value)
            heading.append(Paragraph(company_line, styles["company"]))
        heading.append(Paragraph(role_line, styles["group_role_first" if starts_group else "group_role"]))
        active_group = group_key
        if bullets:
            heading.append(_bullet(bullets[0], styles))
        story.append(KeepTogether(heading))
        story.extend(_bullet(value, styles) for value in bullets[1:])

    story.append(Paragraph("<u>EDUCATION</u>", styles["section"]))
    for item in content.get("education") or []:
        school, degree = _text(item.get("school")), _text(item.get("degree"))
        story.append(Paragraph(f"<b>{school}</b>{' - ' if school and degree else ''}{degree}", styles["body"]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output_path


if __name__ == "__main__":
    print(build_actual_resume())
