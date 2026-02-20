"""
UGIE AI Router — Gemini-powered chat endpoint
──────────────────────────────────────────────
POST /ai/chat         — Streaming chat with Gemini, repo-context aware
POST /ai/task-create  — Extract task from conversation & save to DB
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.routers.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.utils.logging import get_logger
from supabase import Client

logger = get_logger(__name__)
router = APIRouter(prefix="/ai", tags=["AI"])
settings = get_settings()


# ─── Schemas ────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str          # "user" | "model"
    content: str


class RepoContext(BaseModel):
    repo_full_name: Optional[str] = None
    project_name: Optional[str] = None
    deadline: Optional[str] = None
    total_commits_7d: Optional[int] = None
    open_issues: Optional[int] = None
    open_prs: Optional[int] = None
    dormant_days: Optional[int] = None
    top_contributors: Optional[list[dict]] = None  # [{login, commits}]
    collaborators: Optional[list[dict]] = None
    current_view: Optional[str] = None  # The page/section the user currently has open


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    context: Optional[RepoContext] = None


class TaskCreateRequest(BaseModel):
    messages: list[ChatMessage]
    context: Optional[RepoContext] = None
    frontend_project_id: str          # required — the localStorage project UUID
    repo_id: Optional[str] = None     # optional linked Supabase repo UUID


# ─── System Prompt Builder ──────────────────────────────────────────────────

def build_system_prompt(context: Optional[RepoContext]) -> str:
    base = """You are CodePolice AI, an expert software project management assistant embedded inside the CodePolice platform. You help engineering managers and developers understand their projects, identify risks, and make data-driven decisions.

You are concise, insightful, and technically precise. You use markdown formatting naturally — bullet points, bold text, code blocks — but only when it adds clarity. You never fabricate data; if you don't know something, you say so.

Capabilities you have:
- Analyzing GitHub repository activity and contributor patterns
- Identifying project risks, bottlenecks, and delays
- Summarizing team performance and velocity
- Providing actionable recommendations for project health
- Explaining technical concepts clearly
"""

    if not context:
        return base

    ctx_parts = ["\n## Current Project Context\n"]

    if context.project_name:
        ctx_parts.append(f"**Project:** {context.project_name}")
    if context.repo_full_name:
        ctx_parts.append(f"**Repository:** {context.repo_full_name}")
    if context.deadline:
        ctx_parts.append(f"**Deadline:** {context.deadline}")
    if context.total_commits_7d is not None:
        ctx_parts.append(f"**Commits (last 7 days):** {context.total_commits_7d}")
    if context.open_issues is not None:
        ctx_parts.append(f"**Open Issues:** {context.open_issues}")
    if context.open_prs is not None:
        ctx_parts.append(f"**Open PRs:** {context.open_prs}")
    if context.dormant_days is not None and context.dormant_days > 0:
        ctx_parts.append(f"**⚠️ Dormant Days (no commits):** {context.dormant_days}")

    if context.top_contributors:
        contrib_lines = "\n".join(
            f"  - @{c.get('login', '?')}: {c.get('commits', 0)} commits"
            for c in context.top_contributors[:5]
        )
        ctx_parts.append(f"**Top Contributors (30d):**\n{contrib_lines}")

    if context.collaborators:
        collab_lines = "\n".join(
            f"  - @{c.get('login', '?')} ({c.get('permission', 'read')})"
            for c in context.collaborators[:8]
        )
        ctx_parts.append(f"**Collaborators:**\n{collab_lines}")

    if context.current_view:
        ctx_parts.append(
            f"\n**Currently open page:** {context.current_view}\n"
            "The user is looking at this section right now. Tailor your response to be "
            "especially relevant to what they are viewing."
        )

    ctx_parts.append(
        "\nUse this project data to provide specific, grounded answers. "
        "Reference actual numbers and names when relevant."
    )

    return base + "\n".join(ctx_parts)


# ─── Streaming Generator ─────────────────────────────────────────────────────

async def gemini_stream(request: ChatRequest, user: dict):
    """Yields Server-Sent Events with Gemini token chunks."""
    try:
        import google.generativeai as genai

        api_key = settings.gemini_api_key
        if not api_key:
            yield f"data: {json.dumps({'error': 'GEMINI_API_KEY not configured'})}\n\n"
            return

        genai.configure(api_key=api_key)

        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=build_system_prompt(request.context),
        )

        # Build Gemini conversation history (all but the last message)
        history = []
        for msg in request.messages[:-1]:
            history.append({
                "role": "user" if msg.role == "user" else "model",
                "parts": [msg.content],
            })

        chat = model.start_chat(history=history)

        # Stream the last user message
        last_msg = request.messages[-1].content
        response = chat.send_message(last_msg, stream=True)

        for chunk in response:
            text = chunk.text
            if text:
                payload = json.dumps({"text": text})
                yield f"data: {payload}\n\n"

        # Signal end of stream
        yield f"data: {json.dumps({'done': True})}\n\n"

    except Exception as exc:
        logger.error("Gemini stream error", extra={"error": str(exc), "user": user.get("login")})
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"


# ─── Route ───────────────────────────────────────────────────────────────────

@router.post("/chat", summary="Streaming AI chat with Gemini")
async def ai_chat(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Accepts a conversation history + optional repo/project context.
    Streams Gemini 2.5 Flash token-by-token via Server-Sent Events.
    """
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    return StreamingResponse(
        gemini_stream(request, current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Task-Create Route ────────────────────────────────────────────────────────

_TASK_EXTRACTION_PROMPT = """
You are a task creation assistant embedded in a project management tool.
Given a conversation, extract a task to create — or ask a follow-up if you need more information.

DB schema for the task record (all fields you can populate):
  title          TEXT        — short imperative sentence, e.g. "Build login UI"
  assignee       TEXT        — GitHub login or display name of the person responsible
  priority       TEXT        — one of: low | medium | high | critical
  deadline       DATE        — YYYY-MM-DD or null
  tags           TEXT[]      — max 3 short lowercase words inferred from context
  story_points   INT (1–13)  — effort estimate; default 1 if unclear
  status                     — always "todo" for new tasks

Return ONLY valid JSON — no markdown, no explanation — in this exact shape:
{{
  "has_enough_info": true,
  "title": "...",
  "description": null,
  "assignee": null,
  "priority": "medium",
  "deadline": null,
  "tags": [],
  "story_points": 1,
  "followup_question": null
}}

Rules:
- "has_enough_info" is true ONLY if "title" is present and non-empty.
- If the user says "give a task to X" / "assign to X" but hasn't described the task,
  set has_enough_info=false and followup_question="What should the task for [X] be? Briefly describe what needs to be done."
- Use project member names/logins below to resolve "assignee" — match by first name or login.
- Infer story_points from complexity (1=trivial, 3=easy, 5=medium, 8=hard, 13=very hard).
- Write "title" as an action phrase (verb + object).

Project members (login names):
{collaborators}

Today's date: {today}
"""


@router.post("/task-create", summary="Extract task from conversation and save to DB")
async def ai_task_create(
    request: TaskCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """
    Uses Gemini to extract task fields from the conversation.
    If enough info is present, saves to ugie_tasks and returns the created task.
    Otherwise returns a follow-up question.
    """
    try:
        import google.generativeai as genai

        api_key = settings.gemini_api_key
        if not api_key:
            raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured")

        genai.configure(api_key=api_key)

        # Build collaborator list for the prompt
        collaborators_text = "None listed"
        if request.context and request.context.collaborators:
            collaborators_text = ", ".join(
                c.get("login", "?") for c in request.context.collaborators
            )
        elif request.context and request.context.top_contributors:
            collaborators_text = ", ".join(
                c.get("login", "?") for c in request.context.top_contributors
            )

        system = _TASK_EXTRACTION_PROMPT.format(
            collaborators=collaborators_text,
            today=date.today().isoformat(),
        )

        # Build conversation text for the extraction model
        conv_text = "\n".join(
            f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}"
            for m in request.messages
        )

        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system,
        )
        response = model.generate_content(
            f"Conversation:\n{conv_text}\n\nExtract the task as JSON.",
            generation_config={"response_mime_type": "application/json"},
        )

        raw = response.text.strip()
        # Strip markdown code fences that Gemini occasionally adds
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]  # drop the ```json line
            raw = raw.rsplit("```", 1)[0]  # drop trailing ```
        raw = raw.strip()
        extracted: dict = json.loads(raw)

    except json.JSONDecodeError as exc:
        logger.error("Task extraction JSON parse error", extra={"raw": raw, "error": str(exc)})
        return {
            "created": False,
            "task": None,
            "message": "I had trouble understanding that. Could you describe the task more clearly?",
        }
    except Exception as exc:
        logger.error("Task extraction error", extra={"error": str(exc)})
        return {
            "created": False,
            "task": None,
            "message": f"Something went wrong: {exc}",
        }

    if not extracted.get("has_enough_info"):
        return {
            "created": False,
            "task": None,
            "message": extracted.get("followup_question") or "Can you give me more details about the task?",
        }

    # ── Save to Supabase ──────────────────────────────────────────────────────
    row = {
        "user_id": current_user["id"],
        "frontend_project_id": request.frontend_project_id,
        "repo_id": request.repo_id,
        "title": extracted["title"],
        "assignee": extracted.get("assignee"),
        "priority": extracted.get("priority", "medium"),
        "deadline": extracted.get("deadline"),
        "tags": extracted.get("tags", []),
        "status": "todo",
        "story_points": extracted.get("story_points", 1),
        "created_by": current_user.get("login"),
        "source": "ai",
    }
    # Retry loop: strip any column that the live table doesn't have yet
    # Handles: 23503 (FK violation) and PGRST204 (column not in schema cache)
    import re as _re
    FK_COLUMNS = ("user_id", "repo_id")
    saved = None
    current_row = {k: v for k, v in row.items()}
    last_exc = None
    for _attempt in range(10):  # max 10 strips before giving up
        try:
            result = db.table("ugie_tasks").insert(current_row).execute()
            if result.data:
                saved = result.data[0]
                break
        except Exception as exc:
            exc_str = str(exc)
            last_exc = exc_str
            stripped_col = None
            if "23503" in exc_str:
                # FK violation — find which FK column and strip it
                for fk_col in FK_COLUMNS:
                    if fk_col in exc_str and fk_col in current_row:
                        stripped_col = fk_col
                        break
            elif "PGRST204" in exc_str:
                # Column doesn't exist in live table — parse column name from message
                m = _re.search(r"find the '([^']+)' column", exc_str)
                if m and m.group(1) in current_row:
                    stripped_col = m.group(1)
            if stripped_col:
                logger.warning(f"ugie_tasks: stripping column '{stripped_col}' and retrying",
                               extra={"error": exc_str})
                current_row = {k: v for k, v in current_row.items() if k != stripped_col}
            else:
                break  # unrecoverable error

    if saved is None:
        logger.error("Task DB insert failed after retries", extra={"error": last_exc})
        return {
            "created": False,
            "task": None,
            "message": f"I extracted the task but couldn't save it: {last_exc}",
        }

    # ── Build friendly confirmation message ───────────────────────────────────
    parts = [f'✅ Task created: **{saved["title"]}**']
    if saved.get("assignee"):
        parts.append(f'👤 Assigned to **{saved["assignee"]}**')
    if saved.get("deadline"):
        parts.append(f'📅 Due **{saved["deadline"]}**')
    if saved.get("priority") and saved["priority"] != "medium":
        parts.append(f'🔥 Priority: **{saved["priority"]}**')

    message = "\n".join(parts)

    return {
        "created": True,
        "task": saved,
        "message": message,
    }
