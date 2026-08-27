import ast
import asyncio
import base64
import copy
from dataclasses import replace
import inspect
import json
import logging
import os
import random
import re
import sys
import textwrap
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional
from uuid import uuid4

from aiocache import cached
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from open_webui.config import (
    CACHE_DIR,
    CODE_INTERPRETER_BLOCKED_MODULES,
    CODE_INTERPRETER_PYODIDE_PROMPT,
    DEFAULT_CODE_INTERPRETER_PROMPT,
    DEFAULT_TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE,
    DEFAULT_VOICE_MODE_PROMPT_TEMPLATE,
)
from open_webui.constants import TASKS
from open_webui.env import (
    BYPASS_MODEL_ACCESS_CONTROL,
    CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS,
    CHAT_RESPONSE_STREAM_DELTA_CHUNK_SIZE,
    ENABLE_API_OUTLET_FILTERS,
    ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION,
    ENABLE_QUERIES_CACHE,
    ENABLE_REALTIME_CHAT_SAVE,
    ENABLE_RESPONSES_API_STATEFUL,
    GLOBAL_LOG_LEVEL,
    RAG_SYSTEM_CONTEXT,
)
from open_webui.models.chats import Chats
from open_webui.models.config import Config
from open_webui.models.folders import Folders
from open_webui.models.functions import Functions
from open_webui.models.models import Models
from open_webui.models.oauth_sessions import OAuthSessions
from open_webui.models.tools import Tools as ToolModels
from open_webui.models.users import UserModel, Users
from open_webui.retrieval.utils import get_sources_from_items
from open_webui.routers.images import (
    CreateImageForm,
    EditImageForm,
    image_edits,
    image_generations,
)
from open_webui.routers.pipelines import (
    process_pipeline_inlet_filter,
    process_pipeline_outlet_filter,
)
from open_webui.routers.retrieval import (
    SearchForm,
    process_web_search,
)
from open_webui.routers.tasks import (
    generate_chat_tags,
    generate_follow_ups,
    generate_image_prompt,
    generate_queries,
    generate_title,
)
from open_webui.socket.main import (
    get_event_call,
    get_event_emitter,
)
from open_webui.utils.access_control import has_connection_access, has_permission
from open_webui.utils.access_control.files import get_accessible_folder_files
from open_webui.utils.chat import generate_chat_completion
from open_webui.utils.code_interpreter import execute_code_jupyter
from open_webui.utils.context_compaction import compact_messages_for_request
from open_webui.utils.files import (
    convert_markdown_base64_images,
    get_file_url_from_base64,
    get_image_base64_from_url,
    get_image_url_from_base64,
)
from open_webui.utils.filter import (
    FilterContext,
    get_sorted_filter_ids,
    process_filter_functions,
)
from open_webui.utils.kahle_knowledge_harness import (
    build_decision as build_knowledge_harness_decision,
    plan_retrieval as plan_knowledge_retrieval,
    rag_result_from_sources,
    resolve_query_aliases,
    validate_answer as validate_knowledge_harness_answer,
)
from open_webui.utils.personio_directory_client import PersonioDirectoryClient

from open_webui.utils.mcp.client import MCPClient
from open_webui.utils.memory import add_memory_context, review_memory_after_turn
from open_webui.utils.misc import (
    add_or_update_system_message,
    add_or_update_user_message,
    convert_logit_bias_input_to_json,
    convert_output_to_messages,
    deep_update,
    extract_urls,
    get_content_from_message,
    get_last_assistant_message,
    get_last_user_message,
    get_last_user_message_item,
    get_message_list,
    get_system_message,
    is_string_allowed,
    merge_system_messages,
    prepend_to_first_user_message_content,
    replace_system_message_content,
    set_last_user_message_content,
    strip_empty_content_blocks,
)
from open_webui.utils.payload import apply_system_prompt_to_body, resolve_system_prompt
from open_webui.utils.plugin import load_function_module_by_id
from open_webui.utils.response import merge_usage, normalize_usage
from open_webui.utils.sanitize import sanitize_code
from open_webui.utils.task import (
    get_task_model_id,
    rag_template,
    tools_function_calling_generation_template,
)
from open_webui.utils.tools import (
    build_tool_server_headers,
    get_builtin_tools,
    get_terminal_tools,
    get_tools,
    get_updated_tool_function,
)
from open_webui.utils.webhook import post_webhook
from starlette.responses import JSONResponse, Response, StreamingResponse

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)


async def _evict_stale_local_tool_cache(request: Request, tool_ids: list[str] | None) -> None:
    if not tool_ids:
        return
    cached_tools = getattr(request.app.state, 'TOOLS', None)
    if not isinstance(cached_tools, dict):
        return
    cached_contents = getattr(request.app.state, 'TOOL_CONTENTS', None)
    if not isinstance(cached_contents, dict):
        cached_contents = {}
        request.app.state.TOOL_CONTENTS = cached_contents
    for tool_id in tool_ids:
        tool_id = str(tool_id or '')
        if not tool_id or tool_id.startswith('server:mcp:') or tool_id not in cached_tools:
            continue
        tool = await ToolModels.get_tool_by_id(tool_id)
        current_content = getattr(tool, 'content', None) if tool else None
        if isinstance(current_content, str) and cached_contents.get(tool_id) != current_content:
            cached_tools.pop(tool_id, None)
            cached_contents.pop(tool_id, None)


async def _remember_loaded_local_tool_contents(request: Request, tool_ids: list[str] | None) -> None:
    if not tool_ids:
        return
    cached_tools = getattr(request.app.state, 'TOOLS', None)
    if not isinstance(cached_tools, dict):
        return
    cached_contents = getattr(request.app.state, 'TOOL_CONTENTS', None)
    if not isinstance(cached_contents, dict):
        cached_contents = {}
        request.app.state.TOOL_CONTENTS = cached_contents
    for tool_id in tool_ids:
        tool_id = str(tool_id or '')
        if not tool_id or tool_id.startswith('server:mcp:') or tool_id not in cached_tools:
            continue
        tool = await ToolModels.get_tool_by_id(tool_id)
        current_content = getattr(tool, 'content', None) if tool else None
        if isinstance(current_content, str):
            cached_contents[tool_id] = current_content


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _knowledge_harness_mode() -> str:
    mode = str(os.getenv('KAHLE_KNOWLEDGE_HARNESS_MODE') or 'shadow').strip().lower()
    return mode if mode in {'off', 'shadow', 'active'} else 'shadow'


def _knowledge_harness_answer_timeout_seconds() -> float:
    try:
        value = float(os.getenv('KAHLE_ANSWER_STREAM_TIMEOUT_SECONDS') or 60)
    except (TypeError, ValueError):
        value = 60
    return min(300.0, max(5.0, value))


async def _await_kahle_answer_stream(awaitable: Any, *, timeout_seconds: float) -> bool:
    """Return true when an active Harness answer stream exceeds its deadline."""
    try:
        await asyncio.wait_for(awaitable, timeout=timeout_seconds)
        return False
    except asyncio.TimeoutError:
        return True


def _knowledge_harness_permission_scope(user: Any) -> dict[str, Any]:
    if isinstance(user, dict):
        get_value = user.get
    else:
        get_value = lambda name, default=None: getattr(user, name, default)
    groups = get_value('groups', [])
    return {
        'user_id': str(get_value('id', '') or ''),
        'role': str(get_value('role', '') or ''),
        'groups': list(groups) if isinstance(groups, (list, tuple, set)) else [],
    }


def _plan_kahle_retrieval_gate(
    *,
    query: str,
    resolved_query: str,
    messages: list[dict[str, Any]],
    model_id: str,
    permission_scope: dict[str, Any],
    tools_dict: dict[str, Any],
    legacy_rag_request: bool,
    harness_mode: str,
) -> Any:
    """Plan directory needs independently of the narrower legacy RAG gate."""
    plan = plan_knowledge_retrieval(
        query=query,
        resolved_query=resolved_query,
        messages=messages,
        model_id=model_id,
        permission_scope=permission_scope,
    )
    required_tools = tuple(getattr(plan, 'required_tools', ()) or ())
    if harness_mode == 'off':
        if legacy_rag_request and 'rag_chat' in tools_dict:
            return replace(plan, required_tools=('rag_chat',))
        return None
    if 'personio_directory' in required_tools:
        return plan
    if (
        legacy_rag_request
        and 'rag_chat' in required_tools
        and 'rag_chat' in tools_dict
    ):
        return plan
    return None


async def _execute_kahle_retrieval_plan(
    retrieval_plan: Any,
    *,
    query: str,
    directory_intent: str,
    supervisor_candidate_query: str = '',
    user_id: str,
    user_role: str,
    personio_client: Any,
    rag_retriever: Any,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Execute exactly the adapters selected by the deterministic Harness plan."""
    if user_role not in {'user', 'admin'}:
        metadata['kahle_retrieval_tools'] = []
        metadata['kahle_retrieval_access_denied'] = True
        return {'rag_result': '', 'personio_result': None}

    required_tools = tuple(getattr(retrieval_plan, 'required_tools', ()) or ())

    async def retrieve_personio() -> Any:
        return await personio_client.search(
            query,
            directory_intent,
            user_id,
            user_role,
            candidate_query=supervisor_candidate_query,
        )

    if required_tools == ('personio_directory', 'rag_chat'):
        personio_result, rag_result = await asyncio.gather(
            retrieve_personio(), rag_retriever()
        )
    elif required_tools == ('personio_directory',):
        personio_result = await retrieve_personio()
        rag_result = ''
    elif required_tools == ('rag_chat',):
        personio_result = None
        rag_result = await rag_retriever()
    else:
        personio_result = None
        rag_result = ''

    metadata['kahle_retrieval_tools'] = list(required_tools)
    return {'rag_result': rag_result, 'personio_result': personio_result}


def _personio_directory_intent(query: str) -> str:
    """Map a directory need to the private API's bounded sub-intent."""
    raw_query = str(query or '')
    folded = _ascii_fold(raw_query)
    if (
        'onboard' in folded
        and re.search(r'\b(?:wer|welche|mitarbeiter|personen)\b', folded)
        and 'onboarding-prozess' not in folded
    ):
        return 'onboarding_search'
    if re.search(r'\b(?:fuhrungskraft|fuehrungskraft|vorgesetzt\w*)\b', folded):
        return 'supervisor_lookup'
    if re.search(r'\bmit\s+wem\b.*\b(?:arbeitet|zusammen)\b', folded):
        return 'coworker_lookup'
    if re.search(
        r'(?iu)\b(?:'
        r'wie\s+erreiche(?:\s+ich)?\s+'
        r'|wie\s+kann\s+ich\s+'
        r'|wie\s+(?:ist|sind|lautet|lauten)\s+die\s+'
        r'(?:kontakt(?:daten|informationen|m(?:ö|oe)glichkeiten)|telefonnummer|e-?mail(?:-adresse)?|durchwahl)\s+(?:von|f(?:ü|ue)r)\s+'
        r'|(?:nenne|gib|zeige)(?:\s+mir)?\s+die\s+'
        r'(?:kontakt(?:daten|informationen|m(?:ö|oe)glichkeiten)|telefonnummer|e-?mail(?:-adresse)?|durchwahl)\s+(?:von|f(?:ü|ue)r)\s+'
        r'|welche\s+(?:telefonnummer|e-?mail(?:-adresse)?|durchwahl)\s+hat\s+'
        r')'
        r'(?:unser(?:e|en)?\s+)?[A-ZÄÖÜ][\w.-]+\s+[A-ZÄÖÜ][\w.-]+',
        raw_query,
    ):
        return 'person_lookup'
    if re.search(
        r'\b(?:wer\s+ist|wo\s+arbeitet|was\s+macht|'
        r'was\s+weisst\s+du(?:\s+alles)?\s+u(?:e)?ber|'
        r'was\s+hat|wie\s+haengen)\b',
        folded,
    ):
        return 'person_lookup'
    return 'directory_search'


def _supervisor_candidate_query(messages: list[dict[str, Any]], query: str) -> str:
    """Return only the immediately preceding user request for a supervisor follow-up."""
    if _personio_directory_intent(query) != 'supervisor_lookup':
        return ''
    current = str(query or '').strip()
    prior_user_messages = [
        str(message.get('content') or '').strip()
        for message in messages
        if isinstance(message, dict) and message.get('role') == 'user'
    ]
    for candidate in reversed(prior_user_messages):
        if candidate and candidate != current:
            return candidate
    return ''


def _knowledge_harness_metadata_payload(decision: Any) -> dict[str, Any]:
    """Return a PII-free technical summary; full evidence stays request-local."""
    payload = decision.to_dict()
    retrieval = payload.get('retrieval_plan') or {}
    evidence = payload.get('evidence_bundle') or {}
    answer_contract = payload.get('answer_contract') or {}
    sources = []
    for source in evidence.get('sources') or ():
        if not isinstance(source, dict):
            continue
        source_id = str(
            source.get('id') or source.get('number') or source.get('source_id') or ''
        ).lstrip('#').upper()
        if not re.fullmatch(r'[PR]\d+', source_id):
            continue
        kind = (
            'personio_directory'
            if source_id.startswith('P')
            else 'rag_chat'
        )
        sources.append({'id': source_id, 'kind': kind})
    sync_completed_at = evidence.get('sync_completed_at')
    if not (
        isinstance(sync_completed_at, str)
        and re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z',
            sync_completed_at,
        )
    ):
        sync_completed_at = None
    return {
        'required_tools': list(retrieval.get('required_tools') or ()),
        'evidence_status': str(evidence.get('status') or ''),
        'sources': sources,
        'stale': evidence.get('stale') is True,
        'sync_completed_at': sync_completed_at,
        'validation': {
            key: value
            for key, value in answer_contract.items()
            if isinstance(value, bool)
        },
    }


def _store_ephemeral_kahle_harness_payload(
    request: Any, payload: dict[str, Any]
) -> None:
    setattr(request.state, '_kahle_knowledge_harness_payload', payload)


def _ephemeral_kahle_harness_payload(request: Any) -> dict[str, Any] | None:
    payload = getattr(request.state, '_kahle_knowledge_harness_payload', None)
    return payload if isinstance(payload, dict) else None


def _knowledge_harness_direct_answer(
    decision: Any, payload: dict[str, Any]
) -> str:
    retrieval = payload.get('retrieval_plan') or {}
    evidence = payload.get('evidence_bundle') or {}
    resolved_context = payload.get('resolved_context') or {}
    query = str(resolved_context.get('retrieval_query') or '')
    folded_query = (
        query.casefold()
        .replace('ä', 'a')
        .replace('ö', 'o')
        .replace('ü', 'u')
        .replace('ß', 'ss')
    )
    if re.search(
        r'\b(?:wichtig\w*|rangliste|auswahl)\b.*\bfuhrungskraft\w*\b',
        folded_query,
    ):
        return (
            'Eine Rangliste oder Auswahl wichtiger Führungskräfte kann ich nicht '
            'verlässlich bestimmen. Personio liefert dafür keine freigegebene Evidenz.'
        )
    if (
        tuple(retrieval.get('required_tools') or ()) == ('personio_directory',)
        and 'onboard' in folded_query
        and evidence.get('status') == 'supported'
    ):
        entries = []
        for claim in evidence.get('supported_claims') or ():
            if not isinstance(claim, dict):
                continue
            name = str(claim.get('display_name') or '').strip()
            if not name:
                continue
            details = [
                str(claim.get(field) or '').strip()
                for field in ('position', 'department', 'team', 'office')
                if str(claim.get(field) or '').strip()
            ]
            entries.append(f"- {name}" + (f" – {' · '.join(details)}" if details else ''))
        if entries:
            return (
                f"Aktuell sind {len(entries)} Mitarbeiter im Onboarding:\n\n"
                + "\n".join(entries)
            )
        return (
            'Dazu finde ich im aktuellen Personio-Mitarbeiterverzeichnis keine '
            'passende freigegebene Information.'
        )
    if (
        tuple(retrieval.get('required_tools') or ()) == ('personio_directory',)
        and evidence.get('status') == 'unsupported'
    ):
        return (
            'Dazu finde ich im aktuellen Personio-Mitarbeiterverzeichnis keine '
            'passende freigegebene Information.'
        )
    return str(decision.direct_answer() or '')


def _knowledge_harness_tool_called(metadata: dict[str, Any]) -> str:
    tools = list(metadata.get('kahle_retrieval_tools') or [])
    if len(tools) > 1:
        return 'multi_source'
    return str(tools[0]) if tools else ''


def _should_prepare_knowledge_route(
    tools_dict: dict[str, Any], knowledge_request: bool
) -> bool:
    return bool(tools_dict) or bool(knowledge_request)


def _should_execute_kahle_retrieval(
    retrieval_plan: Any, tools_dict: dict[str, Any]
) -> bool:
    if retrieval_plan is None:
        return False
    required_tools = tuple(getattr(retrieval_plan, 'required_tools', ()) or ())
    return (
        'personio_directory' in required_tools
        or ('rag_chat' in required_tools and 'rag_chat' in tools_dict)
    )


# We believe in one maker of all models, seen and unseen,
# and in the reasoning which proceeds from the architect.
# We look for the resurrection of dead processes and the
# inference of the world to come.
DEFAULT_REASONING_TAGS = [
    ('<think>', '</think>'),
    ('<thinking>', '</thinking>'),
    ('<reason>', '</reason>'),
    ('<reasoning>', '</reasoning>'),
    ('<thought>', '</thought>'),
    ('<Thought>', '</Thought>'),
    ('<|begin_of_thought|>', '<|end_of_thought|>'),
    ('◁think▷', '◁/think▷'),
]

DEFAULT_SOLUTION_TAGS = [('<|begin_of_solution|>', '<|end_of_solution|>')]
DEFAULT_CODE_INTERPRETER_TAGS = [('<code_interpreter>', '</code_interpreter>')]
FINAL_NOTICE_PREFIX = '<<<FINAL_NOTICE>>>\n'
FINAL_NOTICE_SUFFIX = '\n<<<END_FINAL_NOTICE>>>'


def output_id(prefix: str) -> str:
    """Generate OR-style ID: prefix + 24-char hex UUID."""
    return f'{prefix}_{uuid4().hex[:24]}'


def merge_streamed_reasoning_details(target: list, details) -> None:
    items = details if isinstance(details, list) else [details]
    for item in items:
        if not isinstance(item, dict):
            continue

        index = item.get('index')
        existing = (
            next((detail for detail in target if detail.get('index') == index), None)
            if isinstance(index, int)
            else None
        )
        if existing is None:
            target.append(dict(item))
            continue

        for key, value in item.items():
            if key in ('text', 'summary') and isinstance(value, str) and isinstance(existing.get(key), str):
                existing[key] += value
            else:
                existing[key] = value


def _extract_final_notice(tool_result: Any) -> str:
    if not isinstance(tool_result, str):
        return ''
    text = tool_result.strip()
    if not text.startswith(FINAL_NOTICE_PREFIX.strip()):
        return ''
    start = len(FINAL_NOTICE_PREFIX.strip())
    if text.startswith(FINAL_NOTICE_PREFIX):
        start = len(FINAL_NOTICE_PREFIX)
    end = text.find(FINAL_NOTICE_SUFFIX.strip(), start)
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def _ascii_fold(text: str) -> str:
    return (
        unicodedata.normalize('NFKC', text or '')
        .lower()
        .replace('\u00e4', 'ae')
        .replace('\u00f6', 'oe')
        .replace('\u00fc', 'ue')
        .replace('\u00df', 'ss')
    )


def _kahle_document_comparison_block_reason(tool_function_name: str, user_text: str) -> str:
    name = str(tool_function_name or '').strip().lower()
    is_document_write_tool = name.endswith('_save') and name.startswith(
        ('file_', 'docx_', 'pdf_', 'xlsx_', 'pptx_', 'text_', 'bundle_')
    )
    if not is_document_write_tool:
        return ''

    folded = _ascii_fold(str(user_text or '').lower())
    comparison_markers = (
        'vergleich',
        'compare',
        'gegenueberstell',
        'unterschied',
        'difference',
        'abweich',
        'was wurde geaendert',
        'was hat sich geaendert',
        'welche aenderungen',
        'aenderungen zwischen',
        'geaendert worden',
        'ueberarbeitet worden',
        'was wurde ueberarbeitet',
        'what changed',
        'changes between',
        'changed between',
        'alte und neue',
        'alt und neu',
        'old and new',
        'versionspruefung',
        'versionsvergleich',
    )
    has_comparison_intent = any(marker in folded for marker in comparison_markers) or bool(
        re.search(r'\bwas wurde\b.{0,120}\b(?:geaendert|ueberarbeitet)\b', folded)
    )
    if not has_comparison_intent:
        return ''

    return (
        'DATEIVERGLEICH_TOOLCALL_BLOCKIERT: Das schreibende oder konvertierende Dokumenttool '
        f'{name} wurde nicht ausgefuehrt. Der Nutzer moechte Dokumente inhaltlich vergleichen, '
        'nicht bearbeiten, konvertieren oder herunterladen. Verwende keine weiteren *_save-Tools. '
        'Rufe stattdessen files_extract_text genau einmal mit allen exakt relevanten Upload-Dateien auf. '
        'Fuehre den Vergleich danach anhand der zurueckgegebenen Dokumenttexte aus und antworte im Chat.'
    )

def _kahle_uploaded_conversion_block_reason(tool_function_name: str, user_text: str) -> str:
    name = str(tool_function_name or '').strip().lower()
    folded = _ascii_fold(str(user_text or ''))
    mentions_word = bool(re.search(r'\b(?:word|docx|worddatei|word-datei|worddokument)\b', folded))
    conversion_intent = any(
        marker in folded
        for marker in (
            'umwandel',
            'wandle',
            'konvertier',
            'als markdown',
            'in markdown',
            'als md',
            'als pdf',
            'in pdf',
            'zu pdf',
            'daraus eine pdf',
            'daraus ein pdf',
            'ausgeben',
        )
    )
    if not mentions_word or not conversion_intent:
        return ''

    wants_markdown = 'markdown' in folded or bool(re.search(r'\bals\s+md\b', folded))
    if wants_markdown and name != 'file_to_md_save' and name in {
        'file_to_docx_save',
        'docx_create_save',
        'kahle_workflow_execute',
    }:
        return (
            'DATEIKONVERTIERUNG_TOOLCALL_BLOCKIERT: Der Nutzer moechte eine angehaengte Word/DOCX-Datei '
            'unveraendert nach Markdown konvertieren. Das ausgewaehlte Tool '
            f'{name} wurde nicht ausgefuehrt. Rufe ausschliesslich file_to_md_save mit dem exakten Uploadpfad auf. '
            'Fuehre keine Recherche, Zusammenfassung, Umschreibung oder inhaltliche Anreicherung aus.'
        )

    wants_pdf = bool(re.search(r'\bpdf\b', folded))
    if wants_pdf and name != 'docx_to_pdf_save' and name in {
        'kahle_workflow_execute',
        'pdf_create_save',
        'file_to_docx_save',
    }:
        return (
            'DATEIKONVERTIERUNG_TOOLCALL_BLOCKIERT: Der Nutzer moechte eine angehaengte Word/DOCX-Datei '
            'unveraendert als PDF konvertieren. Das ausgewaehlte Tool '
            f'{name} wurde nicht ausgefuehrt. Rufe ausschliesslich docx_to_pdf_save mit dem exakten Uploadpfad auf. '
            'Fuehre keine Recherche, Zusammenfassung, Umschreibung oder inhaltliche Anreicherung aus.'
        )

    return ''

def _contains_token(folded: str, token: str) -> bool:
    if token == 'intern':
        return re.search(r'\bintern(e|en|es|er)?\b', folded) is not None
    return token in folded


def _looks_like_raw_email_text(text: str) -> bool:
    folded = _ascii_fold(text)
    if not folded:
        return False

    folded = re.sub(
        r'^\s*(beantworte|beantworten|antworte auf|antwort auf|formuliere eine antwort auf)\s+(die\s+)?mail\s*:?\s*',
        '',
        folded,
    ).strip()

    lines = [line.strip() for line in folded.splitlines() if line.strip()]
    if len(lines) < 3:
        return False

    has_mail_header = any(
        token in folded
        for token in (
            '\nvon:',
            '\ngesendet:',
            '\nan:',
            '\nbetreff:',
            '-----urspruengliche nachricht-----',
            '-----weitergeleitete nachricht-----',
        )
    )
    starts_with_salutation = re.match(
        r'^(hallo|moin|servus|guten tag|sehr geehrte|sehr geehrter|liebe|lieber)\b',
        lines[0],
    ) is not None
    has_signoff = any(
        token in folded
        for token in (
            'mit freundlichen gruessen',
            'viele gruesse',
            'beste gruesse',
            'freundliche gruesse',
        )
    )
    has_mail_body_signals = any(
        token in folded
        for token in (
            'ich benoetige',
            'ich brauche',
            'ich habe',
            'bitte',
            'koennten sie',
            'kannst du',
            'anbei',
            'siehe anhang',
        )
    )
    has_system_or_file_terms = any(
        token in folded
        for token in (
            'csv',
            'catch',
            'gudat',
            'dokumenten-id',
            'datei',
            'auftrag',
            'termin',
            'center',
        )
    )

    return has_mail_header or (
        starts_with_salutation
        and len(folded) > 180
        and (has_signoff or (has_mail_body_signals and has_system_or_file_terms))
    )


def _looks_like_email_drafting_request(text: str) -> bool:
    folded = _ascii_fold(text)
    if not folded:
        return False
    return bool(
        re.search(
            r'\b(?:verfass(?:e|en)|formulier(?:e|en)|schreib(?:e|en)|entwirf|erstelle?)\b'
            r'.{0,80}\b(?:e-?mail|mail|kundenanschreiben|antwort)\b',
            folded,
        )
        or re.search(
            r'\b(?:e-?mail|mail|kundenanschreiben)\b.{0,80}'
            r'\b(?:verfass(?:e|en)|formulier(?:e|en)|schreib(?:e|en)|entwirf|erstelle?)\b',
            folded,
        )
    )


def _looks_like_user_supplied_email_drafting_request(text: str) -> bool:
    """Keep email drafting separate from factual internal lookup.

    The user's supplied scenario is valid drafting input.  Merely mentioning a
    KAHLE process, customer, system or colleague must not turn the request into
    a mandatory knowledge lookup whose empty result vetoes the draft.
    """
    folded = _ascii_fold(text)
    if not folded or _has_explicit_internal_lookup_intent(folded):
        return False
    return _looks_like_email_drafting_request(text)


def _is_general_kahle_vinci_model(model: dict[str, Any]) -> bool:
    identifiers = {
        _ascii_fold(str(model.get('id') or '')).replace('_', '-'),
        _ascii_fold(str(model.get('name') or '')).replace('_', '-'),
    }
    return any(
        value == 'kahle-vinci'
        or (value.startswith('kahle-vinci-') and not value.startswith('kahle-vinci-admin'))
        for value in identifiers
    ) or 'vinci-2-clone-clone-clone' in identifiers


def _general_vinci_mail_redirect(model: dict[str, Any], text: str) -> str:
    if not _is_general_kahle_vinci_model(model):
        return ''
    if not _looks_like_email_drafting_request(text):
        return ''
    return (
        'Bitte wechsle links in der Modellauswahl zum „Mailer-Vinci“. '
        'Er ist für E-Mail-Entwürfe vorgesehen und stellt dir vor dem ersten '
        'Entwurf gezielte Rückfragen.'
    )


def _is_mailer_vinci_model(model: dict[str, Any]) -> bool:
    identifiers = {
        _ascii_fold(str(model.get('id') or '')).replace('_', '-'),
        _ascii_fold(str(model.get('name') or '')).replace('_', '-'),
    }
    return bool(
        {'kahle-email-vinci', 'mailer-vinci', 'kahle-mailer'} & identifiers
    )


def _mailer_initial_questions(text: str) -> list[str]:
    raw_text = str(text or '').strip()
    pasted_mail_is_ambiguous = bool(
        re.search(r'(?im)^\s*(?:hallo|guten\s+tag|sehr\s+geehrt)', raw_text)
        and re.search(r'(?im)^\s*(?:viele|freundliche|mit\s+freundlichen)\s+gr(?:ü|ue)ße', raw_text)
        and not re.search(r'(?i)\b(?:beantworte|antwort(?:e|en)|verbessere|überarbeite|ueberarbeite)\b', raw_text)
    )
    recipient_match = re.search(
        r'\ban\s+(Herrn|Frau|herrn|frau)\s+'
        r'([A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]+)?)',
        str(text or ''),
    )
    if pasted_mail_is_ambiguous:
        goal_question = 'Soll ich auf diese Mail antworten oder deinen Entwurf verbessern?'
    elif recipient_match:
        salutation = 'Herr' if recipient_match.group(1).lower() == 'herrn' else 'Frau'
        recipient = f'{salutation} {recipient_match.group(2)}'
        goal_question = (
            f'Welche konkrete Entscheidung oder Reaktion soll {recipient} '
            'nach der Mail geben?'
        )
    else:
        goal_question = (
            'Welche konkrete Entscheidung oder Reaktion soll die empfangende '
            'Person nach der Mail geben?'
        )

    folded = _ascii_fold(text)
    if any(token in folded for token in ('technisch', 'scan', 'system', 'button', 'prozess')):
        facts_question = (
            'Welche Aussagen zur technischen Machbarkeit sind bereits bestätigt '
            'und was ist bisher nur ein Vorschlag?'
        )
    elif any(token in folded for token in ('beschwer', 'unzufrieden', 'wartezeit', 'fehler')):
        facts_question = (
            'Welche Fakten sind intern bestätigt und welche Zusage darf gegenüber '
            'dem Kunden gemacht werden?'
        )
    else:
        facts_question = (
            'Welche noch fehlenden Fakten, Grenzen oder Zusagen muss ich für den '
            'Entwurf kennen?'
        )

    return [
        goal_question,
        facts_question,
        'Welcher nächste Schritt oder Termin soll in der Mail verbindlich vorgeschlagen werden?',
        'Ist die Mail intern oder extern und soll sie formell oder informell geschrieben sein?',
    ]


def _mailer_initial_question_response(
    model: dict[str, Any], messages: list[dict[str, Any]],
) -> str:
    if not _is_mailer_vinci_model(model):
        return ''
    if any(message.get('role') == 'assistant' for message in messages or []):
        return ''
    user_text = next(
        (
            str(message.get('content') or '')
            for message in reversed(messages or [])
            if message.get('role') == 'user'
        ),
        '',
    ).strip()
    if not user_text:
        return ''
    questions = _mailer_initial_questions(user_text)
    numbered = '\n'.join(f'{index}. {question}' for index, question in enumerate(questions, 1))
    return (
        'Bevor ich den Entwurf schreibe, brauche ich noch diese vier Angaben:\n\n'
        f'{numbered}'
    )


def _mailer_followup_uses_supplied_drafting_context(
    model: dict[str, Any], messages: list[dict[str, Any]], user_text: str,
) -> bool:
    if not _is_mailer_vinci_model(model):
        return False
    if _has_explicit_internal_lookup_intent(_ascii_fold(user_text)):
        return False
    return any(
        message.get('role') == 'assistant'
        and str(message.get('content') or '').startswith(
            'Bevor ich den Entwurf schreibe, brauche ich noch diese vier Angaben:'
        )
        for message in messages or []
    )


def _has_explicit_internal_lookup_intent(folded: str) -> bool:
    return any(
        token in folded
        for token in (
            'suche im internen wissen',
            'suche in der knowledgebase',
            'pruefe im internen wissen',
            'pruefe unsere wissensdatenbank',
            'was sagt unsere richtlinie',
            'was steht in der richtlinie',
            'was sagt der prozess',
            'wie ist bei kahle geregelt',
            'welche oeffnungszeiten',
            'welche marken',
            'wie lautet die standort',
            'wer ist ansprechpartner',
        )
    )


def _looks_like_named_person_question(text: str) -> bool:
    """Treat short name lookups as internal unless web research is explicit.

    KAHLE-Vinci is an internal assistant and employee questions are commonly
    phrased without an additional "bei uns" marker (for example "Wer ist Engin
    Bayir?"). Public-person research remains available through an explicit web
    or internet request, which is handled before this signal is evaluated.
    """
    value = str(text or '').strip()
    return bool(
        re.fullmatch(
            r'(?:und\s+)?(?:wer\s+ist|was\s+(?:weißt|weisst|weiß)\s+du\s+(?:über|ueber))\s+'
            r'(?:(?:unser|unsere|unseren|der|die)\s+)?'
            r'[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß.-]+'
            r'(?:\s+[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß.-]+){1,2}\s*[?!.]*',
            value,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_internal_rag_request(text: str) -> bool:
    folded = _ascii_fold(text)
    if not folded:
        return False

    if re.search(r"(?<![A-Za-z0-9])(?:TD|VK|HAN|WUN|WED|WAL|NEU|NIE|STA|SHG)(?![A-Za-z0-9])", str(text or "")):
        return True

    if (
        _looks_like_raw_email_text(text)
        or _looks_like_user_supplied_email_drafting_request(text)
    ) and not _has_explicit_internal_lookup_intent(folded):
        return False

    external_only = (
        'internet',
        'websuche',
        'google',
        'news',
        'aktuell am markt',
        'oeffentliche quelle',
    )
    internal_signals = (
        'kahle',
        'intern',
        'bei uns',
        'unser',
        'unsere',
        'autohaus',
        'standort',
        'service',
        'werkstatt',
        'vaudis',
        'vaudisx',
        'wps',
        'eva',
        'catch',
        'teams-kanal',
        'arbeitsposition',
        'prozess',
        'vorgang',
        'ablauf',
        'richtlinie',
        'arbeitsanweisung',
        'anweisung',
        'gutschein',
        'recovery',
        'rabatt',
        'aktion',
        'auftrag',
        'kunde',
        'kunden',
    )
    action_signals = (
        'was muss',
        'was mache',
        'wie gehe',
        'wie soll',
        'was ist zu tun',
        'vorgehen',
        'einloes',
        'einlos',
        'bearbeiten',
        'machen muss',
    )

    has_internal_signal = any(_contains_token(folded, token) for token in internal_signals)
    if any(token in folded for token in external_only) and not has_internal_signal:
        return False

    if has_internal_signal or _looks_like_named_person_question(text):
        return True

    return any(token in folded for token in action_signals) and any(
        token in folded for token in ('kunde', 'kunden', 'auftrag', 'gutschein', 'rabatt', 'service')
    )


def _is_internal_clarification_followup(messages: list[dict[str, Any]], user_text: str) -> bool:
    """Keep a short answer to an internal clarification inside RAG routing."""
    current = str(user_text or '').strip()
    if not current or len(current) > 120:
        return False
    previous_assistant = ''
    skipped_current_user = False
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get('role') or '')
        if role == 'user' and not skipped_current_user:
            skipped_current_user = True
            continue
        if role == 'assistant':
            previous_assistant = str(message.get('content') or '')
            break
    def fold(value: str) -> str:
        return (
            str(value or '').casefold()
            .replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
        )

    previous = fold(previous_assistant)
    if 'oeffnungszeiten' not in previous or 'welchen standort' not in previous:
        return False
    folded = fold(current)
    return any(
        token in folded
        for token in (
            'allgemein', 'alles', 'alle', 'verkauf', 'service', 'teiledienst',
            'hannover', 'wunstorf', 'wedemark', 'walsrode', 'neustadt',
            'nienburg', 'stadthagen',
        )
    )


def _expanded_internal_rag_query(messages: list[dict[str, Any]], user_text: str) -> str:
    """Turn short clarification replies into complete, unambiguous searches."""
    current = str(user_text or '').strip()
    previous_assistant = ''
    skipped_current_user = False
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get('role') or '')
        if role == 'user' and not skipped_current_user:
            skipped_current_user = True
            continue
        if role == 'assistant':
            previous_assistant = str(message.get('content') or '')
            break
    def fold(value: str) -> str:
        return (
            str(value or '').casefold()
            .replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
        )

    previous = fold(previous_assistant)
    folded = fold(current)
    prior_user = ''
    for message in reversed((messages or [])[:-1]):
        if isinstance(message, dict) and str(message.get('role') or '') == 'user':
            prior_user = fold(str(message.get('content') or ''))
            break
    customer_lock_clarification = (
        'werbung und befragungen' in previous
        and 'allgemeine kundensperre' in previous
        and 'vaudis' in previous
    ) or bool(
        re.search(r'\bkunden?(?:sperr\w*|\s+sperr\w*)\b', prior_user)
        or ('kunde' in prior_user and 'sperr' in prior_user)
    )
    if customer_lock_clarification:
        if any(token in folded for token in (
            'allgemein', 'kundensperre', 'komplett', 'vollstaendig',
            'zweiteres', 'zweite option',
        )):
            return (
                'Wie veranlasse ich eine allgemeine Kundensperre in Vaudis? '
                'Falls dafür keine freigegebene Anleitung vorliegt: Welche '
                'freigegebene Datenschutz-Anlaufstelle nennt das KAHLE-Wissen '
                'für Sperranfragen?'
            )
        if any(token in folded for token in (
            'werbung', 'werbesperre', 'werbewiderspruch', 'befragung',
            'kontaktfreigabe', 'ersteres', 'erste option',
        )):
            return (
                'Wie sperre ich Werbung und automatisierte Befragungen für einen '
                'Kunden in Vaudis über die DSE-Kontaktfreigaben?'
            )
    asks_for_all = any(token in folded for token in ('allgemein', 'alles', 'alle'))
    if asks_for_all and 'oeffnungszeiten' in previous and 'standort' in previous:
        return (
            'Öffnungszeiten Verkauf Service Teiledienst alle Standorte '
            'Hannover Wunstorf Wedemark Walsrode Neustadt am Rübenberge '
            'Nienburg Stadthagen'
        )
    if re.search(r'\b(?:er|sie|ihn|ihm|ihr)\b', folded):
        contact_followup = bool(
            re.search(r'\b(?:erreich\w*|kontakt(?:daten)?|telefon(?:nummer)?|durchwahl|e-?mail)\b', folded)
        )
        if contact_followup:
            for message in reversed((messages or [])[:-1]):
                if not isinstance(message, dict) or message.get('role') != 'user':
                    continue
                prior_user_text = str(message.get('content') or '').strip()
                if re.search(
                    r'(?iu)\b(?:wer\s+ist|wo\s+arbeitet|was\s+macht|'
                    r'was\s+wei(?:ß|ss)t\s+du(?:\s+alles)?\s+über)\s+'
                    r'(?:unser(?:e|en)?\s+)?[A-ZÄÖÜ][\w.-]+\s+[A-ZÄÖÜ][\w.-]+',
                    prior_user_text,
                ):
                    return f'{current}\n{prior_user_text}'
                break
        system_match = re.search(
            r'\b(vaudisx?|wps|eva|catch|kahle[- ]?speak|personio)\b',
            current,
            re.IGNORECASE,
        )
        if system_match:
            prior_text = ' '.join(
                str(message.get('content') or '')
                for message in (messages or [])[:-1]
                if isinstance(message, dict)
            )
            names = re.findall(
                r'\b([A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]+\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]+)\b',
                prior_text,
            )
            excluded = {'Welche Quelle', 'Für welchen', 'Geht es', 'KAHLE Vinci'}
            person = next(
                (name for name in reversed(names) if name not in excluded),
                '',
            )
            if person:
                return (
                    f'Welche belegte Zuständigkeit oder Beziehung hat {person} '
                    f'zu {system_match.group(1)}?'
                )
    return resolve_query_aliases(current)


def _prerouted_rag_tool_output(
    call_id: str, query: str, *, completed: bool,
) -> list[dict[str, Any]]:
    """Represent deterministic pre-routing as a native visible tool call."""
    output = [{
        'type': 'function_call',
        'id': call_id,
        'call_id': call_id,
        'name': 'rag_chat',
        'arguments': json.dumps({'query': query}, ensure_ascii=False),
        'status': 'completed' if completed else 'in_progress',
    }]
    if completed:
        output.append({
            'type': 'function_call_output',
            'id': output_id('fco'),
            'call_id': call_id,
            'output': [{'type': 'input_text', 'text': 'Wissenssuche abgeschlossen.'}],
            'status': 'completed',
        })
    return output


def _should_emit_prerouted_rag_status(retrieval_plan: Any) -> bool:
    """Show native RAG progress only when the fixed plan actually uses RAG."""
    return 'rag_chat' in tuple(
        getattr(retrieval_plan, 'required_tools', ()) or ()
    )


def _internal_rag_source_outcome(sources: list[dict[str, Any]]) -> str:
    """Return ``found`` or ``missing`` for a canonical rag_chat result."""
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        source_name = str((source.get('source') or {}).get('name') or '').lower()
        if 'rag_chat' not in source_name:
            continue
        documents = source.get('document') if isinstance(source.get('document'), list) else []
        text = '\n'.join(str(item or '') for item in documents)
        if re.search(r'^CLARIFICATION_REQUIRED:\s*true\s*$', text, re.IGNORECASE | re.MULTILINE):
            return 'clarification'
        if re.search(r'^FOUND:\s*true\s*$', text, re.IGNORECASE | re.MULTILINE):
            return 'found'
        if re.search(r'^FOUND:\s*false\s*$', text, re.IGNORECASE | re.MULTILINE):
            return 'missing'
    return ''


def _internal_rag_clarification(sources: list[dict[str, Any]]) -> str:
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        source_name = str((source.get('source') or {}).get('name') or '').lower()
        if 'rag_chat' not in source_name:
            continue
        documents = source.get('document') if isinstance(source.get('document'), list) else []
        text = '\n'.join(str(item or '') for item in documents)
        if not re.search(r'^CLARIFICATION_REQUIRED:\s*true\s*$', text, re.IGNORECASE | re.MULTILINE):
            continue
        answer = re.search(r'^ANSWER:\s*(.+)$', text, re.IGNORECASE | re.MULTILINE)
        if answer:
            return answer.group(1).strip()
    return ''


def _build_native_rag_fallback(
    tools: dict[str, Any],
    user_message: str,
    tool_calls: list,
    output: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Force internal knowledge questions through RAG when native FC skips it.

    Tool-capable models are allowed to answer without selecting a tool.  For an
    internal KAHLE question that would bypass the mandatory permission-filtered
    retriever.  Only the initial response is eligible; an existing tool result
    proves the RAG loop already ran and prevents recursion.
    """
    if tool_calls or 'rag_chat' not in tools or not _looks_like_internal_rag_request(user_message):
        return []
    if any(item.get('type') == 'function_call_output' for item in output):
        return []
    return [
        [
            {
                'id': f'call_{uuid4().hex[:24]}',
                'index': 0,
                'function': {
                    'name': 'rag_chat',
                    'arguments': json.dumps({'query': user_message}, ensure_ascii=False),
                },
            }
        ]
    ]


def _split_tool_calls(
    tool_calls: list[dict],
) -> list[dict]:
    """Expand tool calls whose arguments contain multiple back-to-back JSON objects.

    Some models (e.g. GPT-5.4) send multiple complete JSON argument objects
    under the same tool call index, producing concatenated invalid JSON like:
        '{"query":"A","count":5}{"query":"B","count":5}'

    Each such tool call is split into separate entries so each gets executed
    independently. Single-object arguments pass through unchanged.
    """

    def split_json_objects(raw: str) -> list[str]:
        decoder = json.JSONDecoder()
        results = []
        position = 0

        while position < len(raw):
            while position < len(raw) and raw[position].isspace():
                position += 1
            if position >= len(raw):
                break
            try:
                _, end = decoder.raw_decode(raw, position)
                results.append(raw[position:end].strip())
                position = end
            except json.JSONDecodeError:
                return [raw]

        return results or [raw]

    expanded = []
    for tool_call in tool_calls:
        arguments = tool_call.get('function', {}).get('arguments', '')
        split_arguments = split_json_objects(arguments)

        if len(split_arguments) <= 1:
            expanded.append(tool_call)
        else:
            for argument in split_arguments:
                cloned = copy.deepcopy(tool_call)
                cloned['id'] = f'call_{uuid4().hex[:24]}'
                cloned['function']['arguments'] = argument
                expanded.append(cloned)

    return expanded


def _extract_kahle_file_saved_payload(tool_result: Any) -> Optional[dict[str, Any]]:
    """Return canonical file metadata without letting an LLM rewrite signed URLs.

    KAHLE workflow tools may return the file payload directly or nested below
    ``generated_file``. The result may already have been JSON-serialized by
    ``process_tool_result``.
    """
    candidate = tool_result
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except Exception:
            return None

    if not isinstance(candidate, dict):
        return None

    nested = candidate.get('generated_file')
    if isinstance(nested, dict) and nested.get('download_url'):
        candidate = nested

    if not candidate.get('download_url'):
        return None

    return {
        key: candidate.get(key)
        for key in ('download_url', 'filename', 'sha256', 'size_bytes')
        if key in candidate
    }


def _format_kahle_file_saved_content(payload: dict[str, Any]) -> str:
    """Build the exact user-facing response from trusted tool output."""
    return (
        f"Download-Link: [Datei herunterladen]({payload.get('download_url', '')})\n"
        f"Datei: {payload.get('filename', '')}\n"
        f"SHA256: {payload.get('sha256', '')}\n"
        f"Groesse: {payload.get('size_bytes', '')} Bytes"
    )

def get_citation_source_from_tool_result(
    tool_name: str, tool_params: dict, tool_result: str, tool_id: str = ''
) -> list[dict]:
    """
    Parse a tool's result and convert it to source dicts for citation display.

    Follows the source format conventions from get_sources_from_items:
    - source: file/item info object with id, name, type
    - document: list of document contents
    - metadata: list of metadata objects with source, file_id, name fields

    Returns a list of sources (usually one, but query_knowledge_files may return multiple).
    """
    _EXPECTS_LIST = {'search_web', 'query_knowledge_files'}
    _EXPECTS_DICT = {'view_knowledge_file', 'view_file'}

    try:
        try:
            tool_result = json.loads(tool_result)
        except (json.JSONDecodeError, TypeError):
            pass  # keep tool_result as-is (e.g. fetch_url returns plain text)
        if isinstance(tool_result, dict) and 'error' in tool_result:
            return []

        # Validate tool_result type based on what the branch expects
        if tool_name in _EXPECTS_LIST and not isinstance(tool_result, list):
            return []
        elif tool_name in _EXPECTS_DICT and not isinstance(tool_result, dict):
            return []

        if tool_name == 'search_web':
            # Parse JSON array: [{"title": "...", "link": "...", "snippet": "..."}]
            results = tool_result
            documents = []
            metadata = []

            for result in results:
                title = result.get('title', '')
                link = result.get('link', '')
                snippet = result.get('snippet', '')

                documents.append(f'{title}\n{snippet}')
                metadata.append(
                    {
                        'source': link,
                        'name': title,
                        'url': link,
                    }
                )

            return [
                {
                    'source': {'name': 'search_web', 'id': 'search_web'},
                    'document': documents,
                    'metadata': metadata,
                }
            ]

        elif tool_name in ('view_knowledge_file', 'view_file'):
            file_data = tool_result
            filename = file_data.get('filename', 'Unknown File')
            file_id = file_data.get('id', '')
            knowledge_name = file_data.get('knowledge_name', '')

            return [
                {
                    'source': {
                        'id': file_id,
                        'name': filename,
                        'type': 'file',
                    },
                    'document': [file_data.get('content', '')],
                    'metadata': [
                        {
                            'file_id': file_id,
                            'name': filename,
                            'source': filename,
                            **({'knowledge_name': knowledge_name} if knowledge_name else {}),
                        }
                    ],
                }
            ]

        elif tool_name == 'fetch_url':
            url = tool_params.get('url', '')
            content = tool_result if isinstance(tool_result, str) else str(tool_result)
            snippet = content[:500] + ('...' if len(content) > 500 else '')

            return [
                {
                    'source': {'name': url or 'fetch_url', 'id': url or 'fetch_url'},
                    'document': [snippet],
                    'metadata': [
                        {
                            'source': url,
                            'name': url,
                            'url': url,
                        }
                    ],
                }
            ]

        elif tool_name == 'query_knowledge_files':
            chunks = tool_result

            # Group chunks by source for better citation display
            # Each unique source becomes a separate source entry
            sources_by_file = {}

            for chunk in chunks:
                source_name = chunk.get('source', 'Unknown')
                file_id = chunk.get('file_id', '')
                note_id = chunk.get('note_id', '')
                chunk_type = chunk.get('type', 'file')
                content = chunk.get('content', '')

                # Use file_id or note_id as the key
                key = file_id or note_id or source_name

                if key not in sources_by_file:
                    sources_by_file[key] = {
                        'source': {
                            'id': file_id or note_id,
                            'name': source_name,
                            'type': chunk_type,
                        },
                        'document': [],
                        'metadata': [],
                    }

                sources_by_file[key]['document'].append(content)
                sources_by_file[key]['metadata'].append(
                    {
                        'file_id': file_id,
                        'name': source_name,
                        'source': source_name,
                        **({'note_id': note_id} if note_id else {}),
                    }
                )

            # Return all grouped sources as a list
            if sources_by_file:
                return list(sources_by_file.values())

            # Empty result fallback
            return []

        else:
            # Fallback for other tools
            return [
                {
                    'source': {
                        'name': tool_name,
                        'type': 'tool',
                        'id': tool_id or tool_name,
                    },
                    'document': [str(tool_result)],
                    'metadata': [{'source': tool_name, 'name': tool_name}],
                }
            ]
    except Exception as e:
        log.exception(f'Error parsing tool result for {tool_name}: {e}')
        return [
            {
                'source': {'name': tool_name, 'type': 'tool'},
                'document': [str(tool_result)],
                'metadata': [{'source': tool_name}],
            }
        ]


def _strip_pseudo_toolcall_stream_text(text: str) -> str:
    value = str(text or '')
    marker_index = value.find('[TOOL_CALLS]')
    if marker_index >= 0:
        value = value[:marker_index].rstrip()
    # Some models (notably kahle-vinci-thinking on the Responses API) stream a
    # JSON tool call as the visible answer instead of using native function
    # calling, e.g. {"tool": "safe_webcaller", "parameters": {...}}. It arrives
    # incrementally and is often pretty-printed, so an anchored full match only
    # fires once `"tool":` has streamed in — by then the raw `{ "tool" ...`
    # prefix has already flashed in the UI. Decide as soon as the object opens:
    #   * first key is a tool-call key  -> hide it (the outlet guard answers)
    #   * first key is something else    -> keep it (legit JSON answer)
    #   * first key not complete yet     -> hold the partial back (no flash)
    stripped = value.lstrip()
    if stripped.startswith('{'):
        match = re.match(r'\{\s*"((?:[^"\\]|\\.)*)"\s*:', stripped)
        if match:
            if match.group(1).lower() in {'tool', 'tool_calls', 'name', 'function'}:
                return ''
            return value
        # First key not complete yet. Hold the partial back only while it still
        # looks like a JSON object opening a string key (the shape every leaked
        # tool call has: '{', optional ws, a possibly-unterminated quoted key) —
        # so '{', '{"', '{"too', '{"tool"' are suppressed. Anything else that
        # merely starts with '{' (e.g. a '{{template}}') is kept.
        if re.match(r'\{\s*("(?:[^"\\]|\\.)*"?)?\s*$', stripped):
            return ''
        return value
    return value


def _stream_safe_output(output: list, *, suppress_message_text: bool = False) -> list:
    safe_output = copy.deepcopy(output or [])
    for item in safe_output:
        if not isinstance(item, dict):
            continue
        if suppress_message_text and item.get('type') == 'reasoning':
            summaries = item.get('summary', [])
            if isinstance(summaries, list):
                for summary in summaries:
                    if isinstance(summary, dict) and 'text' in summary:
                        summary['text'] = ''
            continue
        if item.get('type') != 'message':
            continue
        parts = item.get('content', [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and 'text' in part:
                part['text'] = (
                    ''
                    if suppress_message_text
                    else _strip_pseudo_toolcall_stream_text(part.get('text', ''))
                )
    return safe_output


def _should_suppress_initial_rag_response(
    *, rag_tool_available: bool, internal_rag_required: bool, prerouted: bool,
) -> bool:
    return rag_tool_available and internal_rag_required and not prerouted


def deep_merge(target, source):
    """
    Merge source into target recursively (returning new structure).
    - Dicts: Recursive merge.
    - Strings: Concatenation.
    - Others: Overwrite.
    """
    if isinstance(target, dict) and isinstance(source, dict):
        new_target = target.copy()
        for k, v in source.items():
            if k in new_target:
                new_target[k] = deep_merge(new_target[k], v)
            else:
                new_target[k] = v
        return new_target
    elif isinstance(target, str) and isinstance(source, str):
        return target + source
    else:
        return source


def handle_responses_streaming_event(
    data: dict,
    current_output: list,
) -> tuple[list, dict | None]:
    """
    Handle Responses API streaming events in a pure functional way.

    Args:
        data: The event data
        current_output: List of output items (treated as immutable)

    Returns:
        tuple[list, dict | None]: (new_output, metadata)
        - new_output: The updated output list.
        - metadata: Metadata to emit (e.g. usage), {} if update occurred, None if skip.
    """
    # Default: no change
    # Note: treating current_output as immutable, but avoiding full deepcopy for perf.
    # We will shallow copy only if we need to modify the list structure or items.

    event_type = data.get('type', '')

    if event_type == 'response.output_item.added':
        item = data.get('item', {})
        if item:
            new_output = list(current_output)
            new_output.append(item)
            return new_output, None
        return current_output, None

    elif event_type == 'response.content_part.added':
        part = data.get('part', {})
        output_index = data.get('output_index', len(current_output) - 1)

        if current_output and 0 <= output_index < len(current_output):
            new_output = list(current_output)
            # Copy the item to mutate it
            item = new_output[output_index].copy()
            new_output[output_index] = item

            if 'content' not in item:
                item['content'] = []
            else:
                # Copy content list
                item['content'] = list(item['content'])

            if item.get('type') == 'reasoning':
                # Reasoning items should not have content parts
                pass
            else:
                item['content'].append(part)
            return new_output, None
        return current_output, None

    elif event_type == 'response.reasoning_summary_part.added':
        part = data.get('part', {})
        output_index = data.get('output_index', len(current_output) - 1)

        if current_output and 0 <= output_index < len(current_output):
            new_output = list(current_output)
            item = new_output[output_index].copy()
            new_output[output_index] = item

            if 'summary' not in item:
                item['summary'] = []
            else:
                item['summary'] = list(item['summary'])

            item['summary'].append(part)
            return new_output, None
        return current_output, None

    elif event_type.startswith('response.') and event_type.endswith('.delta'):
        # Generic Delta Handling
        parts = event_type.split('.')
        if len(parts) >= 3:
            delta_type = parts[1]
            delta = data.get('delta', '')

            output_index = data.get('output_index', len(current_output) - 1)

            if current_output and 0 <= output_index < len(current_output):
                new_output = list(current_output)
                item = new_output[output_index].copy()
                new_output[output_index] = item
                item_type = item.get('type', '')

                # Determine target field and object based on delta_type and item_type
                if delta_type == 'function_call_arguments':
                    key = 'arguments'
                    if item_type == 'function_call':
                        # Function call args are usually strings
                        item[key] = item.get(key, '') + str(delta)
                else:
                    # Generic handling, refined by item type below
                    pass

                    if item_type == 'message':
                        # Message items: "text"/"output_text" -> "text"
                        # "reasoning_text" -> Skipped (should use reasoning item)
                        if delta_type in ['text', 'output_text']:
                            key = 'text'
                        elif delta_type in ['reasoning_text', 'reasoning_summary_text']:
                            # Skip reasoning updates for message items
                            return new_output, None
                        else:
                            key = delta_type

                        content_index = data.get('content_index', 0)
                        if 'content' not in item:
                            item['content'] = []
                        else:
                            item['content'] = list(item['content'])
                        content_list = item['content']

                        while len(content_list) <= content_index:
                            content_list.append({'type': 'text', 'text': ''})

                        # Copy the part to mutate it
                        part = content_list[content_index].copy()
                        content_list[content_index] = part

                        current_val = part.get(key)
                        if current_val is None:
                            # Initialize based on delta type
                            current_val = {} if isinstance(delta, dict) else ''

                        part[key] = deep_merge(current_val, delta)

                    elif item_type == 'reasoning':
                        # Reasoning items: "reasoning_text"/"reasoning_summary_text" -> "text"
                        # "text"/"output_text" -> Skipped (should use message item)
                        if delta_type == 'reasoning_summary_text':
                            # Summary updates -> item['summary']
                            key = 'text'
                            summary_index = data.get('summary_index', 0)
                            if 'summary' not in item:
                                item['summary'] = []
                            else:
                                item['summary'] = list(item['summary'])
                            summary_list = item['summary']

                            while len(summary_list) <= summary_index:
                                summary_list.append({'type': 'summary_text', 'text': ''})

                            part = summary_list[summary_index].copy()
                            summary_list[summary_index] = part

                            target_val = part.get(key, '')
                            part[key] = deep_merge(target_val, delta)

                        elif delta_type == 'reasoning_text':
                            # Reasoning body updates -> item['content']
                            key = 'text'
                            content_index = data.get('content_index', 0)
                            if 'content' not in item:
                                item['content'] = []
                            else:
                                item['content'] = list(item['content'])
                            content_list = item['content']

                            while len(content_list) <= content_index:
                                # Reasoning content parts default to text
                                content_list.append({'type': 'text', 'text': ''})

                            part = content_list[content_index].copy()
                            content_list[content_index] = part

                            target_val = part.get(key, '')
                            part[key] = deep_merge(target_val, delta)

                        elif delta_type in ['text', 'output_text']:
                            return new_output, None
                        else:
                            # Fallback just in case other deltas target reasoning?
                            pass

                    else:
                        # Fallback for other item types
                        if delta_type in ['text', 'output_text']:
                            key = 'text'
                        else:
                            key = delta_type

                        current_val = item.get(key)
                        if current_val is None:
                            current_val = {} if isinstance(delta, dict) else ''
                        item[key] = deep_merge(current_val, delta)

            return new_output, None

    elif event_type.startswith('response.') and event_type.endswith('.done'):
        # Delta Events: response.content_part.done, response.text.done, etc.
        parts = event_type.split('.')
        if len(parts) >= 3:
            type_name = parts[1]

            # 1. Handle specific Delta "done" signals
            if type_name == 'content_part':
                # "Signaling that no further changes will occur to a content part"
                # If payloads contains the full part, we could update it.
                # Usually purely signaling in standard implementation, but we check payload.
                part = data.get('part')
                output_index = data.get('output_index', len(current_output) - 1)

                if part and current_output and 0 <= output_index < len(current_output):
                    new_output = list(current_output)
                    item = new_output[output_index].copy()
                    new_output[output_index] = item

                    if 'content' in item:
                        item['content'] = list(item['content'])
                        content_index = data.get('content_index', len(item['content']) - 1)
                        if 0 <= content_index < len(item['content']):
                            item['content'][content_index] = part
                            return new_output, {}
                return current_output, None

            elif type_name == 'reasoning_summary_part':
                part = data.get('part')
                output_index = data.get('output_index', len(current_output) - 1)

                if part and current_output and 0 <= output_index < len(current_output):
                    new_output = list(current_output)
                    item = new_output[output_index].copy()
                    new_output[output_index] = item

                    if 'summary' in item:
                        item['summary'] = list(item['summary'])
                        summary_index = data.get('summary_index', len(item['summary']) - 1)
                        if 0 <= summary_index < len(item['summary']):
                            item['summary'][summary_index] = part
                            return new_output, {}
                return current_output, None

            # 2. Skip Output Item done (handled specifically below)
            if type_name == 'output_item':
                pass

            # 3. Generic Field Done (text.done, audio.done)
            elif type_name not in ['completed', 'failed']:
                output_index = data.get('output_index', len(current_output) - 1)
                if current_output and 0 <= output_index < len(current_output):
                    key = (
                        'text'
                        if type_name
                        in [
                            'text',
                            'output_text',
                            'reasoning_text',
                            'reasoning_summary_text',
                        ]
                        else type_name
                    )
                    if type_name == 'function_call_arguments':
                        key = 'arguments'

                    if key in data:
                        final_value = data[key]
                        new_output = list(current_output)
                        item = new_output[output_index].copy()
                        new_output[output_index] = item
                        item_type = item.get('type', '')

                        if type_name == 'function_call_arguments':
                            if item_type == 'function_call':
                                item['arguments'] = final_value
                        elif item_type == 'message':
                            content_index = data.get('content_index', 0)
                            if 'content' in item:
                                item['content'] = list(item['content'])
                                if len(item['content']) > content_index:
                                    part = item['content'][content_index].copy()
                                    item['content'][content_index] = part
                                    part[key] = final_value
                        elif item_type == 'reasoning':
                            item['status'] = 'completed'
                        else:
                            item[key] = final_value

                        return new_output, {}

        return current_output, None

    elif event_type == 'response.output_item.done':
        # Delta Event: Output item complete
        item = data.get('item')
        output_index = data.get('output_index', len(current_output) - 1)

        new_output = list(current_output)
        if item and 0 <= output_index < len(current_output):
            new_output[output_index] = item
        elif item:
            new_output.append(item)
        return new_output, {}

    elif event_type == 'response.completed':
        # State Machine Event: Completed
        response_data = data.get('response', {})
        final_output = response_data.get('output')

        new_output = final_output if final_output is not None else current_output

        # Ensure reasoning items are marked as completed in the final output
        if new_output:
            for item in new_output:
                if item.get('type') == 'reasoning' and item.get('status') != 'completed':
                    item['status'] = 'completed'

        return new_output, {
            'usage': response_data.get('usage'),
            'done': True,
            'response_id': response_data.get('id'),
        }

    elif event_type == 'response.in_progress':
        # State Machine Event: In Progress
        # We could extract metadata if needed, but for now just acknowledge iteration
        return current_output, None

    elif event_type == 'response.failed':
        # State Machine Event: Failed
        error = data.get('response', {}).get('error', {})
        return current_output, {'error': error}

    else:
        return current_output, None


def get_source_context(sources: list, source_ids: dict = None, include_content: bool = True) -> str:
    """
    Build <source> tag context string from citation sources.
    """
    context_string = ''
    if source_ids is None:
        source_ids = {}
    for source in sources:
        for doc, meta in zip(source.get('document', []), source.get('metadata', [])):
            source_id = meta.get('source') or source.get('source', {}).get('id') or 'N/A'
            if source_id not in source_ids:
                source_ids[source_id] = len(source_ids) + 1
            src_name = source.get('source', {}).get('name')
            src_type = source.get('source', {}).get('type')
            src_rid = source.get('source', {}).get('id')
            body = doc if include_content else ''
            context_string += (
                f'<source id="{source_ids[source_id]}"'
                + (f' name="{src_name}"' if src_name else '')
                + (f' resource-type="{src_type}"' if src_type else '')
                + (f' resource-id="{src_rid}"' if src_rid else '')
                + f'>{body}</source>\n'
            )
    return context_string


async def apply_source_context_to_messages(
    request: Request,
    messages: list,
    sources: list,
    user_message: str,
    include_content: bool = True,
) -> list:
    """
    Build source context from citation sources and apply to messages.
    Uses RAG template to format context for model consumption.

    When include_content is False, emit <source> tags with id/name but no
    document body — useful when the content is already present elsewhere
    (e.g. in a tool result message) and only citation markers are needed.
    """
    if not sources or not user_message:
        return messages

    context = get_source_context(sources, include_content=include_content)

    context = context.strip()
    if not context:
        return messages

    if RAG_SYSTEM_CONTEXT:
        return add_or_update_system_message(
            await rag_template(await Config.get('rag.template'), context, user_message),
            messages,
            append=True,
        )
    else:
        return add_or_update_user_message(
            await rag_template(await Config.get('rag.template'), context, user_message),
            messages,
            append=False,
        )


async def process_tool_result(
    request,
    tool_function_name,
    tool_result,
    tool_type,
    direct_tool=False,
    metadata=None,
    user=None,
):
    tool_result_embeds = []
    EXTERNAL_TOOL_TYPES = ('external', 'action', 'terminal')

    # Support (HTMLResponse, result_context) tuples: the optional second
    # element lets tool authors provide the LLM with actionable context
    # about the generated embed instead of the generic fallback message.
    result_context = None
    if isinstance(tool_result, tuple) and len(tool_result) == 2 and isinstance(tool_result[0], HTMLResponse):
        tool_result, result_context = tool_result

    if isinstance(tool_result, HTMLResponse):
        content_disposition = tool_result.headers.get('Content-Disposition', '')
        if 'inline' in content_disposition:
            content = tool_result.body.decode('utf-8', 'replace')
            tool_result_embeds.append(content)

            if 200 <= tool_result.status_code < 300:
                if result_context is not None and isinstance(result_context, (str, dict, list)):
                    tool_result = result_context
                else:
                    tool_result = {
                        'status': 'success',
                        'code': 'ui_component',
                        'message': f'{tool_function_name}: Embedded UI result is active and visible to the user.',
                    }
            elif 400 <= tool_result.status_code < 500:
                tool_result = {
                    'status': 'error',
                    'code': 'ui_component',
                    'message': f'{tool_function_name}: Client error {tool_result.status_code} from embedded UI result.',
                }
            elif 500 <= tool_result.status_code < 600:
                tool_result = {
                    'status': 'error',
                    'code': 'ui_component',
                    'message': f'{tool_function_name}: Server error {tool_result.status_code} from embedded UI result.',
                }
            else:
                tool_result = {
                    'status': 'error',
                    'code': 'ui_component',
                    'message': f'{tool_function_name}: Unexpected status code {tool_result.status_code} from embedded UI result.',
                }
        else:
            tool_result = tool_result.body.decode('utf-8', 'replace')

    elif (tool_type in EXTERNAL_TOOL_TYPES and isinstance(tool_result, tuple)) or (
        direct_tool and isinstance(tool_result, list) and len(tool_result) == 2
    ):
        tool_result, tool_response_headers = tool_result

        try:
            if not isinstance(tool_response_headers, dict):
                tool_response_headers = dict(tool_response_headers)
        except Exception as e:
            tool_response_headers = {}
            log.debug(e)

        if tool_response_headers and isinstance(tool_response_headers, dict):
            content_disposition = tool_response_headers.get(
                'Content-Disposition',
                tool_response_headers.get('content-disposition', ''),
            )

            if 'inline' in content_disposition:
                content_type = tool_response_headers.get(
                    'Content-Type',
                    tool_response_headers.get('content-type', ''),
                )
                location = tool_response_headers.get(
                    'Location',
                    tool_response_headers.get('location', ''),
                )

                if 'text/html' in content_type:
                    # Support (html_content, result_context) nested tuple
                    result_context = None
                    html_content = tool_result
                    if isinstance(tool_result, (tuple, list)) and len(tool_result) == 2:
                        html_content, result_context = tool_result

                    # Display as iframe embed
                    tool_result_embeds.append(html_content)
                    if result_context is not None and isinstance(result_context, (str, dict, list)):
                        tool_result = result_context
                    else:
                        tool_result = {
                            'status': 'success',
                            'code': 'ui_component',
                            'message': f'{tool_function_name}: Embedded UI result is active and visible to the user.',
                        }
                elif location:
                    # Support (html_content, result_context) nested tuple for location embeds
                    result_context = None
                    if isinstance(tool_result, (tuple, list)) and len(tool_result) == 2:
                        _, result_context = tool_result

                    tool_result_embeds.append(location)
                    if result_context is not None and isinstance(result_context, (str, dict, list)):
                        tool_result = result_context
                    else:
                        tool_result = {
                            'status': 'success',
                            'code': 'ui_component',
                            'message': f'{tool_function_name}: Embedded UI result is active and visible to the user.',
                        }

    tool_result_files = []

    # Detect base64 image data URIs from tool results (e.g. binary image
    # responses from execute_tool_server).  Move the data URI to
    # tool_result_files and replace tool_result with a text summary.
    if isinstance(tool_result, str) and tool_result.startswith('data:image/'):
        tool_result_files.append({'type': 'image', 'url': tool_result})
        tool_result = f'{tool_function_name}: Image file read successfully.'

    if isinstance(tool_result, list):
        if tool_type == 'mcp':  # MCP
            tool_response = []
            for item in tool_result:
                if isinstance(item, dict):
                    if item.get('type') == 'text':
                        text = item.get('text', '')
                        if isinstance(text, str):
                            try:
                                text = json.loads(text)
                            except json.JSONDecodeError:
                                pass
                        tool_response.append(text)
                    elif item.get('type') in ['image', 'audio']:
                        file_url = await get_file_url_from_base64(
                            request,
                            f'data:{item.get("mimeType")};base64,{item.get("data", item.get("blob", ""))}',
                            {
                                'chat_id': metadata.get('chat_id', None),
                                'message_id': metadata.get('message_id', None),
                                'session_id': metadata.get('session_id', None),
                                'result': item,
                            },
                            user,
                        )

                        tool_result_files.append(
                            {
                                'type': item.get('type', 'data'),
                                'url': file_url,
                            }
                        )
                    elif item.get('type') == 'resource':
                        resource = item.get('resource', {})
                        text = resource.get('text', '')
                        if isinstance(text, str) and text:
                            try:
                                text = json.loads(text)
                            except json.JSONDecodeError:
                                pass
                            tool_response.append(text)
                        elif resource.get('blob'):
                            resource_mime_type = resource.get('mimeType') or 'application/octet-stream'
                            resource_blob = resource.get('blob', '')
                            if resource_mime_type.startswith('image/'):
                                tool_result_files.append(
                                    {
                                        'type': 'image',
                                        'url': f'data:{resource_mime_type};base64,{resource_blob}',
                                    }
                                )
                            else:
                                resource_uri = resource.get('uri', 'resource')
                                tool_response.append(
                                    f'[Resource: {resource_uri}] (binary data, mimeType: {resource_mime_type})'
                                )
                        elif resource.get('uri'):
                            tool_response.append(resource.get('uri'))
            tool_result = tool_response[0] if len(tool_response) == 1 else tool_response
        else:  # OpenAPI
            for item in tool_result:
                if isinstance(item, str) and item.startswith('data:'):
                    tool_result_files.append(
                        {
                            'type': 'data',
                            'content': item,
                        }
                    )
                    tool_result.remove(item)

    if isinstance(tool_result, list):
        tool_result = {'results': tool_result}

    if isinstance(tool_result, dict) or isinstance(tool_result, list):
        tool_result = json.dumps(tool_result, indent=2, ensure_ascii=False)

    # Safety: ensure tool_result is always a string (or None) to prevent
    # downstream TypeError when concatenating (e.g. if an upstream callable
    # returned a tuple that was not unpacked by the branches above).
    if tool_result is not None and not isinstance(tool_result, str):
        if isinstance(tool_result, tuple):
            # execute_tool_server returns (data, headers); unpack the data part
            tool_result = json.dumps(tool_result[0], indent=2, ensure_ascii=False) if len(tool_result) > 0 else ''
        else:
            tool_result = str(tool_result)

    return tool_result, tool_result_files, tool_result_embeds


async def terminal_event_handler(
    tool_function_name: str,
    tool_function_params: dict,
    tool_result,
    event_emitter,
):
    """Emit terminal:* events for Open Terminal tools.

    - display_file  → emits 'terminal:display_file' to open the file preview.
    - write_file / replace_file_content → emits 'terminal:write_file' to refresh.
    - run_command → emits 'terminal:run_command' with cwd to refresh if relevant.
    """
    if not event_emitter:
        return

    if tool_function_name == 'display_file':
        path = tool_function_params.get('path', '')
        if not path:
            return
        # Only emit if the file actually exists
        parsed = tool_result
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(parsed, dict) and parsed.get('exists') is False:
            return

        await event_emitter(
            {
                'type': f'terminal:{tool_function_name}',
                'data': {'path': path},
            }
        )
    elif tool_function_name in ('write_file', 'replace_file_content'):
        path = tool_function_params.get('path', '')
        if not path:
            return
        await event_emitter(
            {
                'type': f'terminal:{tool_function_name}',
                'data': {'path': path},
            }
        )
    elif tool_function_name == 'run_command':
        await event_emitter(
            {
                'type': 'terminal:run_command',
                'data': {},
            }
        )


async def chat_completion_tools_handler(
    request: Request, body: dict, extra_params: dict, user: UserModel, models, tools
) -> tuple[dict, dict]:
    async def get_content_from_response(response) -> Optional[str]:
        content = None
        if hasattr(response, 'body_iterator'):
            async for chunk in response.body_iterator:
                data = json.loads(chunk.decode('utf-8', 'replace'))
                content = data['choices'][0]['message']['content']

            # Cleanup any remaining background tasks if necessary
            if response.background is not None:
                await response.background()
        else:
            content = response['choices'][0]['message']['content']
        return content

    def _extract_attached_file_refs(files: Any) -> list[dict[str, Optional[str]]]:
        refs: list[dict[str, Optional[str]]] = []
        if not isinstance(files, list):
            return refs

        for item in files:
            if not isinstance(item, dict):
                continue

            name = item.get('name')
            exact = None
            item_id = item.get('id')
            if not name:
                file_obj = item.get('file')
                if isinstance(file_obj, dict):
                    name = file_obj.get('filename')
                    item_id = item_id or file_obj.get('id')
                    fpath = file_obj.get('path')
                    if isinstance(fpath, str) and fpath.strip():
                        exact = fpath.replace('\\', '/').split('/')[-1]
                    if not name:
                        meta = file_obj.get('meta')
                        if isinstance(meta, dict):
                            name = meta.get('name')

            if not exact:
                path = item.get('path')
                if isinstance(path, str) and path.strip():
                    exact = path.replace('\\', '/').split('/')[-1]

            if name:
                display = str(name).strip()
                if not display:
                    continue

                if not exact and item_id:
                    exact = f'{item_id}_{display}'

                if isinstance(exact, str):
                    exact = exact.strip().replace('\\', '/')
                    if exact.startswith('uploads/'):
                        exact = exact[len('uploads/') :]

                candidate = {'name': display, 'exact': exact}
                if candidate not in refs:
                    refs.append(candidate)

        return refs

    def _is_placeholder_filename(value: Any) -> bool:
        if not isinstance(value, str):
            return True

        raw = value.strip().lower()
        if raw in ('', 'none', 'null'):
            return True

        return any(
            token in raw
            for token in (
                'your_',
                'your-',
                'filename',
                'dateiname',
                'datenname',
                'anhang',
                '<',
                '>',
                'latest',
                '*.pdf',
                '*.docx',
                '*.txt',
                '*.md',
                '*.xlsx',
                '*.csv',
            )
        )

    def _build_xlsx_auto_updates_from_prompt(prompt_text: Optional[str]) -> list[dict[str, Any]]:
        if not isinstance(prompt_text, str):
            return []

        normalized = re.sub(r'([A-Za-z])\s+(\d)', r'\1\2', prompt_text)
        normalized = unicodedata.normalize('NFKC', normalized)
        lowered = normalized.lower()
        ascii_lowered = (
            lowered.replace('\u00e4', 'ae')
            .replace('\u00f6', 'oe')
            .replace('\u00fc', 'ue')
            .replace('\u00df', 'ss')
        )

        has_random_money_intent = (
            ('zufall' in ascii_lowered or 'zufaell' in ascii_lowered)
            and any(token in ascii_lowered for token in ('geld', 'betrag', 'euro', '\u20ac'))
        )
        if not has_random_money_intent:
            return []

        cells = re.findall(r'\b([A-Za-z]{1,3}\d{1,7})\b', normalized)
        if len(cells) >= 2:
            start = cells[0].upper()
            end = cells[1].upper()
            return [
                {
                    'range': f'{start}:{end}',
                    'generator': 'random_money',
                    'min': 1000,
                    'max': 100000,
                    'decimals': 2,
                }
            ]

        col_match = re.search(r'spalte\s+([A-Za-z]{1,3})', ascii_lowered, re.I)
        rows = re.findall(r'\b(\d{1,7})\b', normalized)
        if col_match and len(rows) >= 2:
            col = col_match.group(1).upper()
            start = f'{col}{rows[0]}'
            end = f'{col}{rows[1]}'
            return [
                {
                    'range': f'{start}:{end}',
                    'generator': 'random_money',
                    'min': 1000,
                    'max': 100000,
                    'decimals': 2,
                }
            ]

        return []

    def _normalize_file_params(
        tool_function_name: str,
        params: dict[str, Any],
        attached_file_names: list[str],
        attached_exact_paths: list[str],
        name_to_exact: dict[str, str],
    ) -> dict[str, Any]:
        updated = dict(params or {})

        def _normalize_name_key(value: str) -> str:
            s = unicodedata.normalize('NFKC', value or '')
            s = s.replace('\u2013', '-').replace('\u2014', '-').replace('\u2212', '-')
            return re.sub(r'\s+', ' ', s).strip().lower()

        def _canonical_filename_key(value: str) -> str:
            s = (value or '').replace('\\', '/').split('/')[-1]
            s = unicodedata.normalize('NFKD', s)
            s = s.replace('\u2013', '-').replace('\u2014', '-').replace('\u2212', '-')
            s = s.lower()
            return ''.join(ch for ch in s if ch.isalnum() or ch == '.')

        def _match_exact_from_attached(raw_value: str) -> Optional[str]:
            key = _normalize_name_key((raw_value or '').replace('\\', '/').split('/')[-1])
            ckey = _canonical_filename_key(raw_value or '')
            if not key:
                return None
            candidates: list[str] = []
            for exact in attached_exact_paths:
                ex_name = (exact or '').replace('\\', '/').split('/')[-1]
                ex_plain = re.sub(r'^[0-9a-fA-F-]{36}_+', '', ex_name)
                if (
                    _normalize_name_key(ex_name) == key
                    or _normalize_name_key(ex_plain) == key
                    or _canonical_filename_key(ex_name) == ckey
                    or _canonical_filename_key(ex_plain) == ckey
                ):
                    candidates.append(exact)
            if len(candidates) == 1:
                return candidates[0]
            return None

        def _normalize_single_value(value: Any) -> Any:
            if not isinstance(value, str):
                return value

            raw = value.strip().replace('\\', '/')
            if raw.startswith('uploads/'):
                raw = raw[len('uploads/') :]

            mapped = _match_exact_from_attached(raw)
            if mapped:
                return mapped

            if raw in name_to_exact:
                return name_to_exact[raw]
            raw_key = _normalize_name_key(raw)
            raw_ckey = _canonical_filename_key(raw)
            if raw_key:
                for name, exact in name_to_exact.items():
                    if _normalize_name_key(name) == raw_key or _canonical_filename_key(name) == raw_ckey:
                        return exact

            if len(attached_exact_paths) == 1:
                if _is_placeholder_filename(raw):
                    return attached_exact_paths[0]
                if len(attached_file_names) == 1 and raw == attached_file_names[0]:
                    return attached_exact_paths[0]

            if len(attached_file_names) == 1 and _is_placeholder_filename(raw):
                return attached_file_names[0]

            return raw

        if 'file_path' in updated:
            updated['file_path'] = _normalize_single_value(updated.get('file_path'))

        if isinstance(updated.get('file_paths'), list):
            updated['file_paths'] = [_normalize_single_value(fp) for fp in updated['file_paths']]

        if 'xlsx_update_cells_save' in (tool_function_name or '').lower():
            if isinstance(updated.get('updates'), list) and len(updated['updates']) == 0:
                auto_updates = _build_xlsx_auto_updates_from_prompt(get_last_user_message(body.get('messages', []) or []))
                if auto_updates:
                    updated['updates'] = auto_updates

        if len(attached_file_names) == 1 or len(attached_exact_paths) == 1:
            if _is_placeholder_filename(updated.get('file_path')):
                updated['file_path'] = attached_exact_paths[0] if len(attached_exact_paths) == 1 else attached_file_names[0]

            if isinstance(updated.get('file_paths'), list) and len(updated['file_paths']) == 0:
                updated['file_paths'] = [attached_exact_paths[0]] if len(attached_exact_paths) == 1 else [attached_file_names[0]]

        if 'pdf_merge_save' in (tool_function_name or '').lower() and attached_exact_paths:
            updated['attachment_exact_paths'] = list(attached_exact_paths)

        return updated

    def _infer_generated_file_output_format(text_value: str) -> str:
        ascii_text = _ascii_fold(unicodedata.normalize('NFKC', text_value or '').lower())
        if any(marker in ascii_text for marker in ('als pdf', 'pdf aus', 'pdf-datei', 'pdf datei', '.pdf')):
            return 'pdf'
        if any(
            marker in ascii_text
            for marker in (
                'als docx',
                'docx',
                'worddatei',
                'word-datei',
                'word datei',
                'worddokument',
                'word-dokument',
                'als word',
                'word zum download',
                '.docx',
            )
        ):
            return 'docx'
        if any(marker in ascii_text for marker in ('markdown', 'md-datei', '.md')):
            return 'md'
        return ''

    def _looks_like_previous_result_file_request(text_value: str) -> bool:
        ascii_text = _ascii_fold(unicodedata.normalize('NFKC', text_value or '').lower())
        if not _infer_generated_file_output_format(ascii_text):
            return False
        if any(marker in ascii_text for marker in ('download', 'herunterladen', 'als datei')):
            return True
        return any(
            marker in ascii_text
            for marker in (
                'ergebnis',
                'antwort',
                'recherche',
                'recherchierten informationen',
                'das ganze',
                'daraus',
                'strukturiere',
                'strukturiert',
                'zusammenfassung',
            )
        )

    def _infer_fallback_tool_calls(result_obj: Any, user_text: Optional[str]) -> list[dict[str, Any]]:
        if isinstance(result_obj, dict) and result_obj.get('tool_calls'):
            return []

        text = unicodedata.normalize('NFKC', user_text or '').lower()
        if not text:
            return []

        ascii_text = _ascii_fold(text)
        generated_output_format = _infer_generated_file_output_format(text)
        if (
            generated_output_format
            and 'kahle_workflow_execute' in tools
            and (
                _looks_like_previous_result_file_request(text)
                or (not attached_file_names and not attached_exact_paths)
            )
        ):
            return [
                {
                    'name': 'kahle_workflow_execute',
                    'parameters': {
                        'auftrag': str(user_text or '').strip(),
                        'output_format': generated_output_format,
                    },
                }
            ]

        if 'rag_chat' in tools and _looks_like_internal_rag_request(user_text or ''):
            return [
                {
                    'name': 'rag_chat',
                    'parameters': {'query': str(user_text or '').strip()},
                }
            ]

        has_xlsx_intent = (
            ('xlsx' in ascii_text or 'excel' in ascii_text or 'spalte' in ascii_text or 'zelle' in ascii_text)
            and any(
                token in ascii_text
                for token in ('fuege', 'setze', 'trage', 'befuelle', 'zufall', 'zufaell', 'random')
            )
        )
        if not has_xlsx_intent or 'xlsx_update_cells_save' not in tools:
            return []

        xlsx_exacts: list[str] = []
        for path in attached_exact_paths:
            if isinstance(path, str) and path.lower().endswith('.xlsx'):
                xlsx_exacts.append(path)
        for name, exact in name_to_exact.items():
            if isinstance(name, str) and name.lower().endswith('.xlsx') and isinstance(exact, str):
                xlsx_exacts.append(exact)

        xlsx_exacts = list(dict.fromkeys(xlsx_exacts))
        if len(xlsx_exacts) != 1:
            return []

        updates = _build_xlsx_auto_updates_from_prompt(user_text)
        if not updates:
            return []

        return [
            {
                'name': 'xlsx_update_cells_save',
                'parameters': {'file_path': xlsx_exacts[0], 'updates': updates},
            }
        ]

    def _extract_file_saved_payload(tool_result: Any) -> Optional[dict[str, Any]]:
        candidate = tool_result
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except Exception:
                return None

        if not isinstance(candidate, dict):
            return None

        if not (candidate.get('download_url') or candidate.get('output_kind') == 'file_saved'):
            return None

        payload = {}
        for key in ('download_url', 'filename', 'sha256', 'size_bytes'):
            if key in candidate:
                payload[key] = candidate.get(key)
        if not payload.get('download_url'):
            return None
        return payload

    def _is_file_tool_call(tool_function_name: str, tool_function_params: dict[str, Any]) -> bool:
        name = (tool_function_name or '').lower()
        if any(key in tool_function_params for key in ('file_path', 'file_paths')):
            return True
        return any(
            token in name
            for token in ('_save', 'docx_', 'pdf_', 'xlsx_', 'bundle_to_md', 'file_to_md', 'text_apply_ops')
        )

    def _document_comparison_file_tool_validation_error(tool_function_name: str) -> str:
        current_user = str(get_last_user_message(body.get('messages', []) or []) or '')
        comparison_reason = _kahle_document_comparison_block_reason(tool_function_name, current_user)
        if comparison_reason:
            return comparison_reason
        return _kahle_uploaded_conversion_block_reason(tool_function_name, current_user)

    def _calendar_create_validation_error(
        tool_function_name: str,
        tool_function_params: dict[str, Any],
    ) -> str:
        if tool_function_name != 'create_calendar_event':
            return ''

        messages = body.get('messages', []) or []
        current_user = str(get_last_user_message(messages) or '').strip()
        previous_assistant = ''
        for item in reversed(messages[:-1]):
            if item.get('role') == 'assistant':
                previous_assistant = str(get_content_from_message(item) or '').strip()
                if previous_assistant:
                    break

        current_folded = _ascii_fold(unicodedata.normalize('NFKC', current_user).lower())
        previous_folded = _ascii_fold(unicodedata.normalize('NFKC', previous_assistant).lower())
        is_confirmation = bool(
            re.fullmatch(
                r'\s*(?:ja|ja bitte|bestaetigt|bestaetige|ich bestaetige|bitte erstellen|jetzt erstellen|so erstellen|passt|genau so)\s*[.!]?\s*',
                current_folded,
            )
        )
        has_confirmation_request = bool(
            'internen openwebui-kalender' in previous_folded
            and any(token in previous_folded for token in ('soll ich', 'bestaetig', 'jetzt erstellen'))
        )

        title = str(tool_function_params.get('title') or '').strip()
        start = str(tool_function_params.get('start') or '').strip()
        if is_confirmation and has_confirmation_request and title and start:
            return ''

        missing: list[str] = []
        if not title or title.lower() in {'termin', 'kalendereintrag', 'event'}:
            missing.append('Thema/Titel')
        if not start:
            missing.extend(['Datum', 'Uhrzeit'])

        if missing:
            return (
                'KALENDER_TOOLCALL_BLOCKIERT: Es wurde kein Termin erstellt. '
                f"Fehlende Pflichtangaben: {', '.join(dict.fromkeys(missing))}. "
                'Frage den Nutzer in genau einer kurzen Rueckfrage nach allen fehlenden Angaben. '
                'Erfinde keine Werte.'
            )

        return (
            'KALENDER_BESTAETIGUNG_ERFORDERLICH: Es wurde noch kein Termin erstellt. '
            'Zeige dem Nutzer zuerst Titel, Datum, Startzeit, Endzeit oder Dauer, Zeitzone Europe/Berlin, '
            'Ort und Erinnerung. Erklaere, dass dies der interne OpenWebUI-Kalender ist und dass das '
            'aktuelle Werkzeug keine Teilnehmer oder Einladungen verwaltet. Frage anschliessend exakt: '
            '"Soll ich diesen Termin jetzt im internen OpenWebUI-Kalender erstellen?" '
            'Rufe das Werkzeug erst nach der Bestaetigung in der folgenden Nutzernachricht erneut auf.'
        )

    def get_tools_function_calling_payload(
        messages, task_model_id, content, attached_file_names: Optional[list[str]] = None
    ):
        user_message = get_last_user_message(messages)
        attached_file_names = attached_file_names or []

        if attached_file_names:
            file_block = '\n'.join(f'- {name}' for name in attached_file_names)
            suffix = (
                '\n\nAttached files in this message (use exact names for any file tool call):\n'
                f'{file_block}'
            )
            if user_message:
                if 'Attached files in this message' not in user_message:
                    user_message = f'{user_message}{suffix}'
            else:
                user_message = suffix.strip()

        if user_message and messages and messages[-1]['role'] == 'user':
            # Remove the last user message to avoid duplication
            messages = messages[:-1]

        recent_messages = messages[-4:] if len(messages) > 4 else messages
        chat_history = '\n'.join(
            f'{message["role"].upper()}: """{get_content_from_message(message)}"""' for message in recent_messages
        )

        prompt = f'History:\n{chat_history}\nQuery: {user_message}' if chat_history else f'Query: {user_message}'

        return {
            'model': task_model_id,
            'messages': [
                {'role': 'system', 'content': content},
                {'role': 'user', 'content': prompt},
            ],
            'stream': False,
            'metadata': {'task': str(TASKS.FUNCTION_CALLING)},
        }

    event_caller = extra_params['__event_call__']
    event_emitter = extra_params['__event_emitter__']
    metadata = extra_params['__metadata__']
    current_message_refs: list[dict[str, Optional[str]]] = []
    try:
        chat_id = metadata.get('chat_id')
        message_id = metadata.get('message_id')
        if chat_id and message_id and not str(chat_id).startswith('local:'):
            messages_map = await Chats.get_messages_map_by_chat_id(chat_id)
            if isinstance(messages_map, dict):
                current_message = messages_map.get(message_id)
                visited: set[str] = set()
                depth = 0
                while isinstance(current_message, dict) and depth < 8:
                    node_id = str(current_message.get('id') or '')
                    if node_id and node_id in visited:
                        break
                    if node_id:
                        visited.add(node_id)

                    refs = _extract_attached_file_refs(current_message.get('files', []))
                    if refs:
                        current_message_refs = refs
                        break

                    parent_id = current_message.get('parentId') or current_message.get('parent_id')
                    if not parent_id:
                        break
                    current_message = messages_map.get(parent_id)
                    depth += 1

                if not current_message_refs:
                    latest_user_with_files = None
                    latest_ts = -1
                    for msg in messages_map.values():
                        if not isinstance(msg, dict) or msg.get('role') != 'user':
                            continue
                        refs = _extract_attached_file_refs(msg.get('files', []))
                        if not refs:
                            continue
                        try:
                            ts_val = int(msg.get('timestamp') or 0)
                        except Exception:
                            ts_val = 0
                        if ts_val >= latest_ts:
                            latest_ts = ts_val
                            latest_user_with_files = refs
                    if latest_user_with_files:
                        current_message_refs = latest_user_with_files
    except Exception as e:
        log.debug(f'Unable to resolve current message files by chat/message id: {e}')

    last_user_message_item = get_last_user_message_item(body.get('messages', []) or [])
    last_user_refs: list[dict[str, Optional[str]]] = []
    if isinstance(last_user_message_item, dict):
        last_user_refs = _extract_attached_file_refs(last_user_message_item.get('files', []))

    attached_refs = current_message_refs or last_user_refs or _extract_attached_file_refs(metadata.get('files', []))
    attached_file_names: list[str] = []
    attached_exact_paths: list[str] = []
    grouped_exacts: dict[str, set[str]] = {}
    for ref in attached_refs:
        name = ref.get('name')
        exact = ref.get('exact')
        if isinstance(name, str) and name and name not in attached_file_names:
            attached_file_names.append(name)
        if isinstance(exact, str) and exact and exact not in attached_exact_paths:
            attached_exact_paths.append(exact)
        if isinstance(name, str) and name and isinstance(exact, str) and exact:
            grouped_exacts.setdefault(name, set()).add(exact)

    name_to_exact = {key: next(iter(value)) for key, value in grouped_exacts.items() if len(value) == 1}
    log.debug(
        f'tools_handler attached_file_names={attached_file_names} attached_exact_paths={attached_exact_paths}'
    )

    task_model_id = get_task_model_id(
        body['model'],
        await Config.get('task.model.default'),
        await Config.get('task.model.external'),
        models,
    )

    skip_files = False
    sources = []

    specs = [tool['spec'] for tool in tools.values()]
    tools_specs = json.dumps(specs, ensure_ascii=False)

    if await Config.get('task.tools.prompt_template') != '':
        template = await Config.get('task.tools.prompt_template')
    else:
        template = DEFAULT_TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE

    tools_function_calling_prompt = tools_function_calling_generation_template(template, tools_specs)
    user_tool_request = get_last_user_message(body.get('messages', []) or [])
    deterministic_tool_calls = _infer_fallback_tool_calls({}, user_tool_request)
    payload = get_tools_function_calling_payload(
        body['messages'],
        task_model_id,
        tools_function_calling_prompt,
        attached_file_names=attached_file_names,
    )

    try:
        if deterministic_tool_calls:
            # Internal KAHLE lookups and unambiguous generated-file requests do
            # not need another model to decide whether a tool should run. A
            # deterministic pre-route prevents the task model from returning an
            # empty or unsuitable call and lets the actual answer model consume
            # the real tool result in the same request.
            content = json.dumps(
                {'tool_calls': deterministic_tool_calls},
                ensure_ascii=False,
            )
            log.debug(f'deterministic_tool_calls={deterministic_tool_calls}')
        else:
            response = await generate_chat_completion(request, form_data=payload, user=user)
            log.debug(f'{response=}')
            content = await get_content_from_response(response)
            log.debug(f'{content=}')

        if not content:
            return body, {}

        try:
            content = content[content.find('{') : content.rfind('}') + 1]
            if not content:
                raise Exception('No JSON object found in the response')

            result = json.loads(content)
            fallback_tool_calls = _infer_fallback_tool_calls(
                result,
                get_last_user_message(body.get('messages', []) or []),
            )

            async def tool_call_handler(tool_call):
                nonlocal skip_files

                log.debug(f'{tool_call=}')

                tool_function_name = tool_call.get('name', None)
                if not tool_function_name:
                    visible_name = tool_call.get('tool') or tool_call.get('function')
                    if isinstance(visible_name, str):
                        tool_function_name = visible_name
                if tool_function_name not in tools:
                    return body, {}

                tool_function_params = tool_call.get('parameters', {})

                tool = None
                tool_type = ''
                direct_tool = False

                try:
                    tool = tools[tool_function_name]
                    tool_type = tool.get('type', '')
                    direct_tool = tool.get('direct', False)

                    spec = tool.get('spec', {})
                    allowed_params = spec.get('parameters', {}).get('properties', {}).keys()
                    tool_function_params = {k: v for k, v in tool_function_params.items() if k in allowed_params}
                    tool_function_params = _normalize_file_params(
                        tool_function_name,
                        tool_function_params,
                        attached_file_names,
                        attached_exact_paths,
                        name_to_exact,
                    )

                    document_comparison_validation_error = (
                        _document_comparison_file_tool_validation_error(tool_function_name)
                    )
                    calendar_validation_error = _calendar_create_validation_error(
                        tool_function_name, tool_function_params
                    )
                    if document_comparison_validation_error:
                        tool_result = document_comparison_validation_error
                    elif calendar_validation_error:
                        tool_result = calendar_validation_error
                    elif tool.get('direct', False):
                        if _is_file_tool_call(tool_function_name, tool_function_params):
                            skip_files = True
                        tool_result = await event_caller(
                            {
                                'type': 'execute:tool',
                                'data': {
                                    'id': str(uuid4()),
                                    'name': tool_function_name,
                                    'params': tool_function_params,
                                    'server': tool.get('server', {}),
                                    'session_id': metadata.get('session_id', None),
                                },
                            }
                        )
                    else:
                        if _is_file_tool_call(tool_function_name, tool_function_params):
                            skip_files = True
                        tool_function = tool['callable']
                        tool_result = await tool_function(**tool_function_params)

                except Exception as e:
                    tool_result = str(e)

                file_saved_payload = _extract_file_saved_payload(tool_result)
                if file_saved_payload:
                    skip_files = True
                    metadata['kahle_direct_final_content'] = (
                        f"Download-Link: [Datei herunterladen]({file_saved_payload.get('download_url', '')})\n"
                        f"Datei: {file_saved_payload.get('filename', '')}\n"
                        f"SHA256: {file_saved_payload.get('sha256', '')}\n"
                        f"Groesse: {file_saved_payload.get('size_bytes', '')} Bytes"
                    )
                    tool_result = file_saved_payload

                tool_result, tool_result_files, tool_result_embeds = await process_tool_result(
                    request,
                    tool_function_name,
                    tool_result,
                    tool_type,
                    direct_tool,
                    metadata,
                    user,
                )

                if event_emitter:
                    await terminal_event_handler(
                        tool_function_name,
                        tool_function_params,
                        tool_result,
                        event_emitter,
                    )

                    if tool_result_files:
                        await event_emitter(
                            {
                                'type': 'files',
                                'data': {
                                    'files': tool_result_files,
                                },
                            }
                        )

                    if tool_result_embeds:
                        await event_emitter(
                            {
                                'type': 'embeds',
                                'data': {
                                    'embeds': tool_result_embeds,
                                },
                            }
                        )

                if tool_result:
                    tool = tools[tool_function_name]
                    tool_id = tool.get('tool_id', '')

                    tool_name = f'{tool_id}/{tool_function_name}' if tool_id else f'{tool_function_name}'

                    # Citation is enabled for this tool
                    sources.append(
                        {
                            'source': {
                                'name': (f'{tool_name}'),
                            },
                            'document': [str(tool_result)],
                            'metadata': [
                                {
                                    'source': (f'{tool_name}'),
                                    'parameters': tool_function_params,
                                }
                            ],
                            'tool_result': True,
                        }
                    )

                    if tools[tool_function_name].get('metadata', {}).get('file_handler', False):
                        skip_files = True

            # check if "tool_calls" in result
            if result.get('tool_calls'):
                for tool_call in result.get('tool_calls'):
                    await tool_call_handler(tool_call)
            elif fallback_tool_calls:
                for tool_call in fallback_tool_calls:
                    await tool_call_handler(tool_call)
            else:
                await tool_call_handler(result)

        except Exception as e:
            log.debug(f'Error: {e}')
            try:
                fallback_tool_calls = _infer_fallback_tool_calls(
                    {},
                    get_last_user_message(body.get('messages', []) or []),
                )
                for tool_call in fallback_tool_calls:
                    tool_function_name = tool_call.get('name', None)
                    if tool_function_name not in tools:
                        continue

                    tool_function_params = tool_call.get('parameters', {})
                    tool = tools[tool_function_name]
                    tool_type = tool.get('type', '')
                    direct_tool = tool.get('direct', False)

                    spec = tool.get('spec', {})
                    allowed_params = spec.get('parameters', {}).get('properties', {}).keys()
                    tool_function_params = {k: v for k, v in tool_function_params.items() if k in allowed_params}
                    tool_function_params = _normalize_file_params(
                        tool_function_name,
                        tool_function_params,
                        attached_file_names,
                        attached_exact_paths,
                        name_to_exact,
                    )

                    document_comparison_validation_error = (
                        _document_comparison_file_tool_validation_error(tool_function_name)
                    )
                    calendar_validation_error = _calendar_create_validation_error(
                        tool_function_name, tool_function_params
                    )
                    if document_comparison_validation_error:
                        tool_result = document_comparison_validation_error
                    elif calendar_validation_error:
                        tool_result = calendar_validation_error
                    elif direct_tool:
                        if _is_file_tool_call(tool_function_name, tool_function_params):
                            skip_files = True
                        tool_result = await event_caller(
                            {
                                'type': 'execute:tool',
                                'data': {
                                    'id': str(uuid4()),
                                    'name': tool_function_name,
                                    'params': tool_function_params,
                                    'server': tool.get('server', {}),
                                    'session_id': metadata.get('session_id', None),
                                },
                            }
                        )
                    else:
                        if _is_file_tool_call(tool_function_name, tool_function_params):
                            skip_files = True
                        tool_result = await tool['callable'](**tool_function_params)

                    file_saved_payload = _extract_file_saved_payload(tool_result)
                    if file_saved_payload:
                        skip_files = True
                        metadata['kahle_direct_final_content'] = (
                            f"Download-Link: [Datei herunterladen]({file_saved_payload.get('download_url', '')})\n"
                            f"Datei: {file_saved_payload.get('filename', '')}\n"
                            f"SHA256: {file_saved_payload.get('sha256', '')}\n"
                            f"Groesse: {file_saved_payload.get('size_bytes', '')} Bytes"
                        )
                        tool_result = file_saved_payload

                    tool_result, tool_result_files, tool_result_embeds = await process_tool_result(
                        request,
                        tool_function_name,
                        tool_result,
                        tool_type,
                        direct_tool,
                        metadata,
                        user,
                    )

                    if event_emitter:
                        await terminal_event_handler(
                            tool_function_name,
                            tool_function_params,
                            tool_result,
                            event_emitter,
                        )
                        if tool_result_files:
                            await event_emitter({'type': 'files', 'data': {'files': tool_result_files}})
                        if tool_result_embeds:
                            await event_emitter({'type': 'embeds', 'data': {'embeds': tool_result_embeds}})

                    if tool_result:
                        tool_id = tool.get('tool_id', '')
                        tool_name = f'{tool_id}/{tool_function_name}' if tool_id else f'{tool_function_name}'
                        sources.append(
                            {
                                'source': {'name': f'{tool_name}'},
                                'document': [str(tool_result)],
                                'metadata': [{'source': f'{tool_name}', 'parameters': tool_function_params}],
                                'tool_result': True,
                            }
                        )
            except Exception as fallback_error:
                log.debug(f'Fallback tool execution failed: {fallback_error}')
            content = None
    except Exception as e:
        log.debug(f'Error: {e}')
        content = None

    log.debug(f'tool_contexts: {sources}')
    if sources:
        metadata['kahle_tool_sources'] = copy.deepcopy(sources)


    if skip_files and 'files' in body.get('metadata', {}):
        del body['metadata']['files']

    return body, {'sources': sources}


async def chat_web_search_handler(request: Request, form_data: dict, extra_params: dict, user):
    event_emitter = extra_params['__event_emitter__']
    await event_emitter(
        {
            'type': 'status',
            'data': {
                'action': 'web_search',
                'description': 'Searching the web',
                'done': False,
            },
        }
    )

    messages = form_data['messages']
    user_message = get_last_user_message(messages)

    queries = []
    try:
        res = await generate_queries(
            request,
            {
                'model': form_data['model'],
                'messages': messages,
                'prompt': user_message,
                'type': 'web_search',
                'chat_id': extra_params.get('__chat_id__'),
            },
            user,
        )

        response = res['choices'][0]['message']['content']

        try:
            bracket_start = response.rfind('{')
            bracket_end = response.rfind('}') + 1

            if bracket_start == -1 or bracket_end == -1:
                raise Exception('No JSON object found in the response')

            response = response[bracket_start:bracket_end]
            queries = json.loads(response)
            queries = queries.get('queries', [])
        except Exception as e:
            queries = [response]

        if ENABLE_QUERIES_CACHE:
            request.state.cached_queries = queries

    except Exception as e:
        log.exception(e)
        queries = [user_message or '']

    # Check if generated queries are empty
    if len(queries) == 1 and queries[0].strip() == '':
        queries = [user_message or '']

    # Check if queries are not found
    if len(queries) == 0:
        await event_emitter(
            {
                'type': 'status',
                'data': {
                    'action': 'web_search',
                    'description': 'No search query generated',
                    'done': True,
                },
            }
        )
        return form_data

    await event_emitter(
        {
            'type': 'status',
            'data': {
                'action': 'web_search_queries_generated',
                'queries': queries,
                'done': False,
            },
        }
    )

    try:
        results = await process_web_search(
            request,
            SearchForm(queries=queries),
            user=user,
        )

        if results:
            files = form_data.get('files', [])

            if results.get('collection_names'):
                for col_idx, collection_name in enumerate(results.get('collection_names')):
                    files.append(
                        {
                            'collection_name': collection_name,
                            'name': ', '.join(queries),
                            'type': 'web_search',
                            'urls': results['filenames'],
                            'queries': queries,
                        }
                    )
            elif results.get('docs'):
                # Invoked when bypass embedding and retrieval is set to True
                docs = results['docs']
                files.append(
                    {
                        'docs': docs,
                        'name': ', '.join(queries),
                        'type': 'web_search',
                        'urls': results['filenames'],
                        'queries': queries,
                    }
                )

            form_data['files'] = files

            await event_emitter(
                {
                    'type': 'status',
                    'data': {
                        'action': 'web_search',
                        'description': 'Searched {{count}} sites',
                        'urls': results['filenames'],
                        'items': results.get('items', []),
                        'done': True,
                    },
                }
            )
        else:
            await event_emitter(
                {
                    'type': 'status',
                    'data': {
                        'action': 'web_search',
                        'description': 'No search results found',
                        'done': True,
                        'error': True,
                    },
                }
            )

    except Exception as e:
        log.exception(e)
        await event_emitter(
            {
                'type': 'status',
                'data': {
                    'action': 'web_search',
                    'description': 'An error occurred while searching the web',
                    'queries': queries,
                    'done': True,
                    'error': True,
                },
            }
        )

    return form_data


def get_images_from_messages(message_list):
    images = []

    for message in reversed(message_list):
        message_images = []
        for file in message.get('files', []):
            if file.get('type') == 'image':
                message_images.append(file.get('url'))
            elif file.get('content_type', '').startswith('image/'):
                message_images.append(file.get('url'))

        if message_images:
            images.append(message_images)

    return images


async def get_image_urls(delta_images, request, metadata, user) -> list[str]:
    if not isinstance(delta_images, list):
        return []

    image_urls = []
    for img in delta_images:
        if not isinstance(img, dict) or img.get('type') != 'image_url':
            continue

        url = img.get('image_url', {}).get('url')
        if not url:
            continue

        if url.startswith('data:image/png;base64'):
            url = await get_image_url_from_base64(request, url, metadata, user)

        image_urls.append(url)

    return image_urls


async def add_file_context(messages: list, chat_id: str, user) -> list:
    """
    Add file URLs to messages for native function calling.
    """
    if not chat_id or chat_id.startswith('local:'):
        return messages

    chat = await Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if not chat:
        return messages

    history = chat.chat.get('history', {})
    stored_messages = get_message_list(history.get('messages', {}), history.get('currentId'))

    def format_file_tag(file):
        attrs = f'type="{file.get("type", "file")}" url="{file["url"]}"'
        if file.get('content_type'):
            attrs += f' content_type="{file["content_type"]}"'
        if file.get('name'):
            attrs += f' name="{file["name"]}"'
        return f'<file {attrs}/>'

    # Pair only user-role messages from both lists to avoid misalignment.
    # After process_messages_with_output(), assistant messages with tool calls
    # are expanded into multiple messages (assistant + tool results), making
    # the payload message list longer than the stored message list. A naive
    # positional zip() would pair user messages with wrong stored messages,
    # causing later images to lose their file context (see #21878).
    user_messages = [m for m in messages if m.get('role') == 'user']
    stored_user_messages = [m for m in stored_messages if m.get('role') == 'user']

    for message, stored_message in zip(user_messages, stored_user_messages):
        files_with_urls = [
            file
            for file in stored_message.get('files', [])
            if file.get('url') and not file.get('url').startswith('data:')
        ]
        if not files_with_urls:
            continue

        file_tags = [format_file_tag(file) for file in files_with_urls]
        file_context = '<attached_files>\n' + '\n'.join(file_tags) + '\n</attached_files>\n\n'

        content = message.get('content', '')
        if isinstance(content, list):
            message['content'] = [{'type': 'text', 'text': file_context}] + content
        else:
            message['content'] = file_context + content

    return messages


async def chat_image_generation_handler(request: Request, form_data: dict, extra_params: dict, user):
    metadata = extra_params.get('__metadata__', {})
    chat_id = metadata.get('chat_id', None)
    __event_emitter__ = extra_params.get('__event_emitter__', None)

    if not chat_id or not isinstance(chat_id, str) or not __event_emitter__:
        return form_data

    if chat_id.startswith('local:'):
        message_list = form_data.get('messages', [])
    else:
        chat = await Chats.get_chat_by_id_and_user_id(chat_id, user.id)
        await __event_emitter__(
            {
                'type': 'status',
                'data': {'description': 'Creating image', 'done': False},
            }
        )

        messages_map = chat.chat.get('history', {}).get('messages', {})
        message_id = chat.chat.get('history', {}).get('currentId')
        message_list = get_message_list(messages_map, message_id)

    user_message = get_last_user_message(message_list)

    prompt = user_message
    message_images = get_images_from_messages(message_list)

    # Limit to first 2 sets of images
    # We may want to change this in the future to allow more images
    input_images = []
    for idx, images in enumerate(message_images):
        if idx >= 2:
            break
        for image in images:
            input_images.append(image)

    system_message_content = ''

    if len(input_images) > 0 and await Config.get('images.edit.enable'):
        # Edit image(s)
        try:
            images = await image_edits(
                request=request,
                form_data=EditImageForm(**{'prompt': prompt, 'image': input_images}),
                metadata={
                    'chat_id': metadata.get('chat_id', None),
                    'message_id': metadata.get('message_id', None),
                },
                user=user,
            )

            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {'description': 'Image created', 'done': True},
                }
            )

            await __event_emitter__(
                {
                    'type': 'files',
                    'data': {
                        'files': [
                            {
                                'type': 'image',
                                'url': image['url'],
                            }
                            for image in images
                        ]
                    },
                }
            )

            system_message_content = '<context>The requested image has been edited and created and is now being shown to the user. Let them know that it has been generated.</context>'
        except Exception as e:
            log.debug(e)

            error_message = ''
            if isinstance(e, HTTPException):
                if e.detail and isinstance(e.detail, dict):
                    error_message = e.detail.get('message', str(e.detail))
                else:
                    error_message = str(e.detail)

            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {
                        'description': f'An error occurred while generating an image',
                        'done': True,
                    },
                }
            )

            system_message_content = f'<context>Image generation was attempted but failed. The system is currently unable to generate the image. Tell the user that the following error occurred: {error_message}</context>'

    else:
        # Create image(s)
        if await Config.get('image_generation.prompt.enable'):
            try:
                res = await generate_image_prompt(
                    request,
                    {
                        'model': form_data['model'],
                        'messages': form_data['messages'],
                        'chat_id': metadata.get('chat_id'),
                    },
                    user,
                )

                response = res['choices'][0]['message']['content']

                try:
                    bracket_start = response.rfind('{')
                    bracket_end = response.rfind('}') + 1

                    if bracket_start == -1 or bracket_end == -1:
                        raise Exception('No JSON object found in the response')

                    response = response[bracket_start:bracket_end]
                    response = json.loads(response)
                    prompt = response.get('prompt', [])
                except Exception as e:
                    prompt = user_message

            except Exception as e:
                log.exception(e)
                prompt = user_message

        try:
            images = await image_generations(
                request=request,
                form_data=CreateImageForm(**{'prompt': prompt}),
                metadata={
                    'chat_id': metadata.get('chat_id', None),
                    'message_id': metadata.get('message_id', None),
                },
                user=user,
            )

            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {'description': 'Image created', 'done': True},
                }
            )

            await __event_emitter__(
                {
                    'type': 'files',
                    'data': {
                        'files': [
                            {
                                'type': 'image',
                                'url': image['url'],
                            }
                            for image in images
                        ]
                    },
                }
            )

            system_message_content = '<context>The requested image has been created by the system successfully and is now being shown to the user. Let the user know that the image they requested has been generated and is now shown in the chat.</context>'
        except Exception as e:
            log.debug(e)

            error_message = ''
            if isinstance(e, HTTPException):
                if e.detail and isinstance(e.detail, dict):
                    error_message = e.detail.get('message', str(e.detail))
                else:
                    error_message = str(e.detail)

            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {
                        'description': f'An error occurred while generating an image',
                        'done': True,
                    },
                }
            )

            system_message_content = f'<context>Image generation was attempted but failed because of an error. The system is currently unable to generate the image. Tell the user that the following error occurred: {error_message}</context>'

    if system_message_content:
        form_data['messages'] = add_or_update_system_message(system_message_content, form_data['messages'])

    return form_data


async def chat_completion_files_handler(
    request: Request, body: dict, extra_params: dict, user: UserModel
) -> tuple[dict, dict[str, list]]:
    __event_emitter__ = extra_params['__event_emitter__']
    sources = []

    if files := body.get('metadata', {}).get('files', None):
        # Check if all files are in full context mode
        all_full_context = all(item.get('context') == 'full' for item in files)

        queries = []
        if not all_full_context:
            try:
                queries_response = await generate_queries(
                    request,
                    {
                        'model': body['model'],
                        'messages': body['messages'],
                        'type': 'retrieval',
                        'chat_id': body.get('metadata', {}).get('chat_id'),
                    },
                    user,
                )
                queries_response = queries_response['choices'][0]['message']['content']

                try:
                    bracket_start = queries_response.rfind('{')
                    bracket_end = queries_response.rfind('}') + 1

                    if bracket_start == -1 or bracket_end == -1:
                        raise Exception('No JSON object found in the response')

                    queries_response = queries_response[bracket_start:bracket_end]
                    queries_response = json.loads(queries_response)
                except Exception as e:
                    queries_response = {'queries': [queries_response]}

                queries = queries_response.get('queries', [])
            except Exception:
                pass

            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {
                        'action': 'queries_generated',
                        'queries': queries,
                        'done': False,
                    },
                }
            )

        if len(queries) == 0:
            queries = [get_last_user_message(body['messages']) or '']

        try:
            # Directly await async get_sources_from_items (no thread needed - fully async now)
            sources = await get_sources_from_items(
                request=request,
                items=files,
                queries=queries,
                embedding_function=lambda query, prefix: request.app.state.EMBEDDING_FUNCTION(
                    query, prefix=prefix, user=user
                ),
                k=await Config.get('rag.top_k'),
                reranking_function=(
                    (lambda query, documents: request.app.state.RERANKING_FUNCTION(query, documents, user=user))
                    if request.app.state.RERANKING_FUNCTION
                    else None
                ),
                k_reranker=await Config.get('rag.top_k_reranker'),
                r=await Config.get('rag.relevance_threshold'),
                hybrid_bm25_weight=await Config.get('rag.hybrid_bm25_weight'),
                hybrid_search=await Config.get('rag.enable_hybrid_search'),
                full_context=all_full_context or await Config.get('rag.full_context'),
                user=user,
            )
        except Exception as e:
            log.exception(e)

        log.debug(f'rag_contexts:sources: {sources}')

        unique_ids = set()
        for source in sources or []:
            if not source or len(source.keys()) == 0:
                continue

            documents = source.get('document') or []
            metadatas = source.get('metadata') or []
            src_info = source.get('source') or {}

            for index, _ in enumerate(documents):
                metadata = metadatas[index] if index < len(metadatas) else None
                _id = (metadata or {}).get('source') or (src_info or {}).get('id') or 'N/A'
                unique_ids.add(_id)

        sources_count = len(unique_ids)
        await __event_emitter__(
            {
                'type': 'status',
                'data': {
                    'action': 'sources_retrieved',
                    'count': sources_count,
                    'done': True,
                },
            }
        )

    return body, {'sources': sources}


def apply_params_to_form_data(form_data, model):
    params = form_data.pop('params', {})
    custom_params = params.pop('custom_params', {})

    open_webui_params = {
        'stream_response': bool,
        'stream_delta_chunk_size': int,
        'function_calling': str,
        'reasoning_tags': list,
        'compact_token_threshold': int,
        'system': str,
    }

    for key in list(params.keys()):
        if key in open_webui_params:
            del params[key]

    if custom_params:
        # Attempt to parse custom_params if they are strings
        for key, value in custom_params.items():
            if isinstance(value, str):
                try:
                    # Attempt to parse the string as JSON
                    custom_params[key] = json.loads(value)
                except json.JSONDecodeError:
                    # If it fails, keep the original string
                    pass

        # If custom_params are provided, merge them into params
        params = deep_update(params, custom_params)

    if model.get('owned_by') == 'ollama':
        # Ollama specific parameters
        form_data['options'] = params
    else:
        if isinstance(params, dict):
            for key, value in params.items():
                if value is not None:
                    form_data[key] = value

        if 'logit_bias' in params and params['logit_bias'] is not None:
            try:
                logit_bias = convert_logit_bias_input_to_json(params['logit_bias'])

                if logit_bias:
                    form_data['logit_bias'] = json.loads(logit_bias)
            except Exception as e:
                log.exception(f'Error parsing logit_bias: {e}')

    return form_data


async def convert_url_images_to_base64(form_data, user=None):
    messages = form_data.get('messages', [])

    for message in messages:
        content = message.get('content')
        if not isinstance(content, list):
            continue

        new_content = []

        for item in content:
            if not isinstance(item, dict) or item.get('type') != 'image_url':
                new_content.append(item)
                continue

            image_url = item.get('image_url', {}).get('url', '')
            if image_url.startswith('data:image/'):
                new_content.append(item)
                continue

            try:
                base64_data = await get_image_base64_from_url(image_url, user=user)
                if base64_data:
                    new_content.append(
                        {
                            'type': 'image_url',
                            'image_url': {'url': base64_data},
                        }
                    )
                else:
                    new_content.append(item)
            except Exception as e:
                log.debug(f'Error converting image URL to base64: {e}')
                new_content.append(item)

        message['content'] = new_content

    return form_data


async def load_messages_from_db(chat_id: str, message_id: str) -> Optional[list[dict]]:
    """
    Load the message chain from DB up to message_id,
    keeping only LLM-relevant fields (role, content, output).
    """
    messages_map = await Chats.get_messages_map_by_chat_id(chat_id)
    if not messages_map:
        return None

    db_messages = get_message_list(messages_map, message_id)
    if not db_messages:
        return None

    return [
        {k: v for k, v in msg.items() if k in ('role', 'content', 'output', 'files', 'contextSummary')}
        for msg in db_messages
    ]


def get_reasoning_format(model: dict) -> str | None:
    """
    Determine how reasoning should be included in reconstructed messages.

    Returns:
        'think_tags': Ollama expects <think> tags in content.
        'reasoning_content': llama.cpp supports reasoning_content as a top-level field.
        None: skip reasoning (safe default for strict providers).
    """
    provider = model.get('provider', '')
    if provider == 'ollama':
        return 'think_tags'
    if provider == 'llama.cpp':
        return 'reasoning_content'
    return None


def _extract_kahle_rag_sources(tool_result: Any) -> list[dict[str, Any]]:
    text = tool_result if isinstance(tool_result, str) else ''
    match = re.search(r'SOURCES_JSON:\s*(\[.*?\])\s*(?:\n|$)', text, re.DOTALL)
    if not match:
        return []
    try:
        sources = json.loads(match.group(1))
    except (TypeError, ValueError):
        return []
    return [
        source
        for source in sources
        if isinstance(source, dict)
        and str(source.get('source_url') or '').startswith('/wissen/api/portal/sources/')
    ]


def _canonical_kahle_rag_source_events(
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expose retrieved documents as native OpenWebUI citation sources.

    The tool invocation itself remains visible through its status event.  The
    citation drawer, however, should identify the documents returned by RAG
    instead of presenting the generic ``rag_chat/rag_chat`` tool as a source.
    """
    events = []
    seen = set()
    for source in sources:
        title = str(source.get('title') or 'Interne Wissensquelle').strip()
        url = str(source.get('source_url') or '').strip()
        if not url or url in seen:
            continue
        seen.add(url)
        metadata = {
            key: source.get(key)
            for key in (
                'document_id', 'version_id', 'valid_until', 'knowledgebase_ids',
            )
            if source.get(key) not in (None, '', [])
        }
        metadata.update({'source': title, 'url': url})
        evidence_text = str(source.get('evidence_text') or '').strip()
        events.append({
            'source': {'name': title, 'url': url},
            'document': [evidence_text] if evidence_text else [],
            'metadata': [metadata],
        })
    return events


def _append_canonical_rag_source_links(output: list[dict[str, Any]], sources: list[dict[str, Any]]) -> None:
    if not sources:
        return
    message = next((item for item in reversed(output) if item.get('type') == 'message'), None)
    if not message:
        return
    parts = message.get('content') or []
    text_part = next((part for part in reversed(parts) if part.get('type') == 'output_text'), None)
    if not text_part:
        return
    text = str(text_part.get('text') or '').rstrip()
    # Models must never turn an authenticated relative portal URL into an
    # invented host. Remove any model-authored source link and append the
    # canonical links from the trusted tool result below.
    text = re.sub(
        r'(?ims)\n*Quellen:\s*\n'
        r'(?:\s*-\s*\[[^\]]+\]\('
        r'(?:(?:https?://[^)\s]+/)|/)(?:wissen/)?api/portal/sources/[^)\s]+'
        r'\)\s*\n?)+',
        '\n',
        text,
    ).rstrip()
    text = re.sub(
        r'\[([^\]]+)\]\((?:(?:https?://[^)\s]+/)|/)(?:wissen/)?api/portal/sources/[^)\s]+\)',
        r'\1',
        text,
        flags=re.IGNORECASE,
    ).rstrip()
    links = []
    seen = set()
    for source in sources:
        url = str(source.get('source_url') or '')
        if url in seen:
            continue
        seen.add(url)
        title = str(source.get('title') or 'Originalquelle').replace('[', '').replace(']', '')
        links.append(f'- [{title}]({url})')
    if links:
        text_part['text'] = f"{text}\n\nQuellen:\n" + '\n'.join(links)


def _extract_kahle_rag_feedback_link(tool_result: Any) -> str:
    text = tool_result if isinstance(tool_result, str) else ''
    match = re.search(
        r'FEEDBACK_LINK:\s*\[Wissensfehler melden\]'
        r'\((/wissen/\?feedback=1&chat_id=[A-Za-z0-9_-]{1,100}'
        r'&message_id=[A-Za-z0-9_-]{1,100}'
        r'(?:&(?:document_ids|knowledgebase_ids)=[A-Za-z0-9_%,-]{0,3000})*)\)',
        text,
    )
    return match.group(1) if match else ''


def _append_canonical_rag_feedback_link(output: list[dict[str, Any]], feedback_link: str) -> None:
    if not feedback_link:
        return
    message = next((item for item in reversed(output) if item.get('type') == 'message'), None)
    if not message:
        return
    parts = message.get('content') or []
    text_part = next((part for part in reversed(parts) if part.get('type') == 'output_text'), None)
    if not text_part:
        return
    text = str(text_part.get('text') or '').rstrip()
    # The model may preserve only the label or may rewrite the trusted URL.
    # Remove either variant and append the canonical tool-provided link once.
    text = re.sub(
        r'(?im)^[ \t]*(?:\[Wissensfehler melden\]\([^)]+\)|Wissensfehler melden)[ \t]*$\n?',
        '',
        text,
    ).rstrip()
    text_part['text'] = f"{text}\n\n[Wissensfehler melden]({feedback_link})"


def _last_kahle_answer_text(output: list[dict[str, Any]]) -> str:
    for item in reversed(output or []):
        if item.get('type') != 'message':
            continue
        for part in reversed(item.get('content') or []):
            if part.get('type') == 'output_text':
                return str(part.get('text') or '').strip()
    return ''


def process_messages_with_output(
    messages: list[dict],
    reasoning_format: str | None = None,
) -> list[dict]:
    """
    Process messages with OR-aligned output items for LLM consumption.

    For assistant messages with 'output' field, produces properly formatted
    OpenAI-style messages (tool_calls + tool results). Strips 'output' before LLM.
    """
    processed = []

    for message in messages:
        if message.get('role') == 'assistant' and message.get('output'):
            # Use output items for clean OpenAI-format messages
            output_messages = convert_output_to_messages(message['output'], raw=True)
            if output_messages:
                processed.extend(output_messages)
                continue

        # Strip 'output' field before adding (LLM shouldn't see it)
        clean_message = {k: v for k, v in message.items() if k != 'output'}
        processed.append(clean_message)

    return processed


def strip_compaction_fields(messages: list[dict]) -> list[dict]:
    stripped = []
    for message in messages:
        clean = dict(message)
        clean.pop('contextSummary', None)
        clean.pop('context_summary', None)
        stripped.append(clean)
    return stripped


def sanitize_tool_pairs(messages: list[dict]) -> list[dict]:
    tool_result_ids = {
        message.get('tool_call_id')
        for message in messages
        if message.get('role') == 'tool' and message.get('tool_call_id')
    }

    tool_call_ids = {
        tool_call.get('id')
        for message in messages
        for tool_call in (message.get('tool_calls') or [])
        if message.get('role') == 'assistant' and tool_call.get('id')
    }

    sanitized = []
    for message in messages:
        if message.get('role') == 'assistant' and message.get('tool_calls'):
            kept = [
                tool_call for tool_call in message.get('tool_calls') or [] if tool_call.get('id') in tool_result_ids
            ]
            if kept:
                sanitized.append({**message, 'tool_calls': kept})
            else:
                clean = dict(message)
                clean.pop('tool_calls', None)
                clean.pop('reasoning_items', None)
                if clean.get('content'):
                    sanitized.append(clean)
        elif message.get('role') != 'tool' or message.get('tool_call_id') in tool_call_ids:
            sanitized.append(message)

    return sanitized


SKILL_MENTION_RE = re.compile(r'<\$([^|>]+)(?:\|[^>]*)?>')


def _get_text_parts(message: dict) -> list[str]:
    """Return all text segments from a message's content."""
    content = message.get('content')
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text']
    return []


def extract_skill_ids_from_messages(messages: list[dict]) -> set[str]:
    """Extract skill IDs from <$skillId|label> mention tags in messages."""
    ids: set[str] = set()
    for message in messages:
        for text in _get_text_parts(message):
            ids.update(m.group(1) for m in SKILL_MENTION_RE.finditer(text))
    return ids


def strip_skill_mentions(messages: list[dict]) -> None:
    """Replace <$skillId|label> mention tags with the label in message content in-place."""
    strip_re = re.compile(r'<\$[^|>]+(?:\|([^>]*))?>')
    for message in messages:
        content = message.get('content')
        if isinstance(content, str) and strip_re.search(content):
            message['content'] = strip_re.sub(r'\1', content).strip()
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'text':
                    text = part.get('text', '')
                    if strip_re.search(text):
                        part['text'] = strip_re.sub(r'\1', text).strip()


async def connect_mcp_server(
    request,
    server_id: str,
    user,
    metadata: dict,
    extra_params: dict,
) -> tuple[MCPClient, list[dict]] | None:
    """Resolve an MCP server connection, authenticate, and return (client, tool_specs).

    Returns None if the server is not found or access is denied.
    """
    mcp_server_connection = None
    for server_connection in await Config.get('tool_server.connections', []):
        if server_connection.get('type', '') == 'mcp' and (server_connection.get('info') or {}).get('id') == server_id:
            mcp_server_connection = server_connection
            break

    if not mcp_server_connection:
        log.error(f'MCP server with id {server_id} not found')
        return None

    if not await has_connection_access(user, mcp_server_connection):
        log.warning(f'Access denied to MCP server {server_id} for user {user.id}')
        return None

    headers, _ = await build_tool_server_headers(
        mcp_server_connection,
        request,
        user,
        server_id=server_id,
        metadata=metadata,
        extra_params=extra_params,
    )

    client = MCPClient()
    await client.connect(
        url=mcp_server_connection.get('url', ''),
        headers=headers if headers else None,
    )

    function_name_filter_list = mcp_server_connection.get('config', {}).get('function_name_filter_list', '')
    if isinstance(function_name_filter_list, str):
        function_name_filter_list = function_name_filter_list.split(',')

    tool_specs = await client.list_tool_specs()
    if function_name_filter_list:
        tool_specs = [spec for spec in tool_specs if is_string_allowed(spec['name'], function_name_filter_list)]

    return client, tool_specs


async def process_chat_payload(request, form_data, user, metadata, model):
    # Ensure chat_id is always a string — external API clients may omit it.
    if not isinstance(metadata.get('chat_id'), str):
        metadata['chat_id'] = ''

    # Pipeline Inlet -> Filter Inlet -> Chat Memory -> Chat Web Search -> Chat Image Generation
    # -> Chat Code Interpreter (Form Data Update) -> (Default) Chat Tools Function Calling
    # -> Chat Files

    # Arena model resolution — pick the sub-model now so all downstream
    # processing (knowledge, capabilities, tools, params) uses its settings
    # instead of the empty arena wrapper.
    if model.get('owned_by') == 'arena':
        arena_model_ids = model.get('info', {}).get('meta', {}).get('model_ids')
        arena_filter_mode = model.get('info', {}).get('meta', {}).get('filter_mode')
        if arena_model_ids and arena_filter_mode == 'exclude':
            arena_model_ids = [
                available_model['id']
                for available_model in request.app.state.MODELS.values()
                if available_model.get('owned_by') != 'arena' and available_model['id'] not in arena_model_ids
            ]

        if isinstance(arena_model_ids, list) and arena_model_ids:
            selected_model_id = random.choice(arena_model_ids)
        else:
            arena_model_ids = [
                available_model['id']
                for available_model in request.app.state.MODELS.values()
                if available_model.get('owned_by') != 'arena'
            ]
            selected_model_id = random.choice(arena_model_ids)

        selected_model = request.app.state.MODELS.get(selected_model_id)
        if selected_model:
            model = selected_model
            form_data['model'] = selected_model_id
            metadata['selected_model_id'] = selected_model_id

    form_data = apply_params_to_form_data(form_data, model)
    log.debug(f'form_data: {form_data}')

    # Guided regeneration: extract before it reaches the LLM provider
    regeneration_prompt = form_data.pop('regeneration_prompt', None)

    # Load messages from DB when available — DB preserves structured 'output' items
    # which the frontend strips, causing tool calls to be merged into content.
    chat_id = metadata.get('chat_id')
    user_message_id = metadata.get('user_message_id')

    if chat_id and user_message_id and not chat_id.startswith('local:') and not chat_id.startswith('channel:'):
        db_messages = await load_messages_from_db(chat_id, user_message_id)
        if db_messages:
            # Continue: frontend sends assistant_message_id when continuing
            # an existing response. Load its content so the LLM sees prior output.
            assistant_message_id = metadata.get('assistant_message_id')
            if assistant_message_id:
                assistant_message = await Chats.get_message_by_id_and_message_id(chat_id, assistant_message_id)
                if assistant_message and (assistant_message.get('content') or assistant_message.get('output')):
                    db_messages.append(
                        {
                            k: v
                            for k, v in assistant_message.items()
                            if k in ('role', 'content', 'output', 'files', 'contextSummary')
                        }
                    )

            system_message = get_system_message(form_data.get('messages', []))
            form_data['messages'] = [system_message, *db_messages] if system_message else db_messages

            # Inject image files into content as image_url parts (mirrors frontend logic)
            for message in form_data['messages']:
                image_files = [
                    f
                    for f in message.get('files', [])
                    if f.get('type') == 'image' or (f.get('content_type') or '').startswith('image/')
                ]
                if message.get('role') == 'user' and image_files:
                    text_content = message.get('content', '')
                    if isinstance(text_content, str):
                        message['content'] = [
                            {'type': 'text', 'text': text_content},
                            *[
                                {
                                    'type': 'image_url',
                                    'image_url': {'url': f['url']},
                                }
                                for f in image_files
                                if f.get('url')
                            ],
                        ]
                # Strip files field — it's been incorporated into content
                message.pop('files', None)

    if regeneration_prompt:
        form_data['messages'].append({'role': 'user', 'content': regeneration_prompt})

    mailer_questions = _mailer_initial_question_response(
        model, form_data.get('messages', []) or [],
    )
    if mailer_questions:
        metadata['kahle_direct_final_content'] = mailer_questions
    else:
        mail_redirect = _general_vinci_mail_redirect(
            model, get_last_user_message(form_data.get('messages', []) or []) or '',
        )
        if mail_redirect:
            metadata['kahle_direct_final_content'] = mail_redirect
    if _mailer_followup_uses_supplied_drafting_context(
        model,
        form_data.get('messages', []) or [],
        get_last_user_message(form_data.get('messages', []) or []) or '',
    ):
        metadata['kahle_mailer_drafting_followup'] = True

    if chat_id and user_message_id and not chat_id.startswith('local:') and not chat_id.startswith('channel:'):
        if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
            compaction_models = {
                request.state.model['id']: request.state.model,
            }
        else:
            compaction_models = request.app.state.MODELS

        system_message = get_system_message(form_data.get('messages', []))
        system_prompt = get_content_from_message(system_message) if system_message else ''

        try:
            form_data['messages'], context_summary, _ = await compact_messages_for_request(
                request,
                user,
                form_data.get('messages', []),
                metadata,
                form_data.get('model'),
                compaction_models,
                system_prompt,
            )
            if context_summary:
                form_data['messages'] = add_or_update_system_message(
                    f'[CONVERSATION SUMMARY]\n{context_summary}',
                    form_data['messages'],
                    append=True,
                )
        except Exception:
            log.exception('Context compaction failed; continuing with full chat history')

    form_data['messages'] = strip_compaction_fields(form_data.get('messages', []))

    # Process messages with OR-aligned output items for clean LLM messages
    form_data['messages'] = process_messages_with_output(
        form_data.get('messages', []),
        reasoning_format=get_reasoning_format(model),
    )
    form_data['messages'] = sanitize_tool_pairs(form_data['messages'])

    system_message = get_system_message(form_data.get('messages', []))
    if system_message:  # Chat Controls/User Settings
        try:
            form_data = await apply_system_prompt_to_body(
                system_message.get('content'), form_data, metadata, user, replace=True
            )  # Required to handle system prompt variables
        except Exception:
            pass

    form_data = await convert_url_images_to_base64(form_data, user=user)

    event_emitter = await get_event_emitter(metadata)
    event_caller = await get_event_call(metadata)

    extra_params = {
        '__event_emitter__': event_emitter,
        '__event_call__': event_caller,
        '__user__': user.model_dump() if isinstance(user, UserModel) else {},
        '__metadata__': metadata,
        '__oauth_token__': await get_system_oauth_token(request, user),
        '__request__': request,
        '__model__': model,
        '__chat_id__': metadata.get('chat_id'),
        '__message_id__': metadata.get('message_id'),
    }
    # Initialize events to store additional event to be sent to the client
    # Initialize contexts and citation
    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    task_model_id = get_task_model_id(
        form_data['model'],
        await Config.get('task.model.default'),
        await Config.get('task.model.external'),
        models,
    )

    events = []
    sources = []

    # Folder "Project" handling
    # Check if the request has chat_id and is inside of a folder
    # Uses lightweight column query — only fetches folder_id, not the full chat JSON blob
    chat_id = metadata.get('chat_id', None)
    folder_id = None
    if chat_id and user:
        folder_id = await Chats.get_chat_folder_id(chat_id, user.id)

    # Fallback: use folder_id from metadata (temporary chats have no DB record)
    if not folder_id:
        folder_id = metadata.get('folder_id', None)

    if folder_id and user:
        folder = await Folders.get_folder_by_id_and_user_id(folder_id, user.id)

        if folder and folder.data:
            if 'system_prompt' in folder.data:
                form_data = await apply_system_prompt_to_body(folder.data['system_prompt'], form_data, metadata, user)
            if 'files' in folder.data:
                # Defensive: filter to entries the caller can still read.
                allowed_files = await get_accessible_folder_files(folder.data['files'], user)
                if metadata.get('params', {}).get('function_calling') == 'legacy':
                    form_data['files'] = [
                        *allowed_files,
                        *form_data.get('files', []),
                    ]
                else:
                    # Native FC: skip RAG injection, builtin tools
                    # will read folder knowledge from metadata.
                    metadata['folder_knowledge'] = allowed_files

    # Model "Knowledge" handling
    user_message = get_last_user_message(form_data['messages'])
    model_knowledge = model.get('info', {}).get('meta', {}).get('knowledge', False)

    if model_knowledge and metadata.get('params', {}).get('function_calling') == 'legacy':
        await event_emitter(
            {
                'type': 'status',
                'data': {
                    'action': 'knowledge_search',
                    'query': user_message,
                    'done': False,
                },
            }
        )

        knowledge_files = []
        for item in model_knowledge:
            if item.get('collection_name'):
                knowledge_files.append(
                    {
                        'id': item.get('collection_name'),
                        'name': item.get('name'),
                        'legacy': True,
                    }
                )
            elif item.get('collection_names'):
                knowledge_files.append(
                    {
                        'name': item.get('name'),
                        'type': 'collection',
                        'collection_names': item.get('collection_names'),
                        'legacy': True,
                    }
                )
            else:
                knowledge_files.append(item)

        files = form_data.get('files', [])
        files.extend(knowledge_files)
        form_data['files'] = files

    variables = form_data.pop('variables', None)
    payload_tools = form_data.get('tools', None)  # snapshot before filters

    # Process the form_data through the pipeline
    try:
        form_data = await process_pipeline_inlet_filter(request, form_data, user, models)
    except Exception as e:
        raise e

    try:
        filter_ids = await get_sorted_filter_ids(request, model, metadata.get('filter_ids', []))
        filter_functions = await Functions.get_functions_by_ids(filter_ids)

        form_data, flags = await process_filter_functions(
            request=request,
            filter_context=None,
            filter_functions=filter_functions,
            filter_type='inlet',
            form_data=form_data,
            extra_params=extra_params,
        )
    except Exception as e:
        raise Exception(f'{e}')

    features = form_data.pop('features', None) or {}
    extra_params['__features__'] = features
    if features:
        if 'voice' in features and features['voice']:
            if await Config.get('task.voice.prompt.enable'):
                if await Config.get('task.voice.prompt_template'):
                    template = await Config.get('task.voice.prompt_template')
                else:
                    template = DEFAULT_VOICE_MODE_PROMPT_TEMPLATE

                form_data['messages'] = add_or_update_system_message(
                    template,
                    form_data['messages'],
                )

        if 'memory' in features and features['memory'] and await Config.get('memories.system_context.enable'):
            form_data = await add_memory_context(request, form_data, user, model)

        if 'web_search' in features and features['web_search']:
            # Skip forced RAG web search when native FC is enabled - model can use web_search tool
            if metadata.get('params', {}).get('function_calling') == 'legacy':
                form_data = await chat_web_search_handler(request, form_data, extra_params, user)

        if 'image_generation' in features and features['image_generation']:
            # Skip forced image generation when native FC is enabled - model can use generate_image tool
            if metadata.get('params', {}).get('function_calling') == 'legacy':
                form_data = await chat_image_generation_handler(request, form_data, extra_params, user)

        if 'code_interpreter' in features and features['code_interpreter']:
            engine = await Config.get('code_interpreter.engine', 'pyodide')

            # Skip XML-tag prompt injection when native FC is enabled —
            # execute_code will be injected as a builtin tool instead
            if metadata.get('params', {}).get('function_calling') == 'legacy':
                prompt = (
                    await Config.get('code_interpreter.prompt_template')
                    if await Config.get('code_interpreter.prompt_template') != ''
                    else DEFAULT_CODE_INTERPRETER_PROMPT
                )

                # Append filesystem awareness only for pyodide engine
                if engine != 'jupyter':
                    prompt += CODE_INTERPRETER_PYODIDE_PROMPT

                form_data['messages'] = add_or_update_user_message(
                    prompt,
                    form_data['messages'],
                )
            else:
                # Native FC: tool docstring can't be dynamic, so inject
                # filesystem context into the system message for pyodide
                # engine.  Appending to the system prompt (instead of the
                # user message) keeps it in the stable cached prefix so
                # providers with prefix caching don't re-bill the full
                # conversation on every turn.
                if engine != 'jupyter':
                    form_data['messages'] = add_or_update_system_message(
                        CODE_INTERPRETER_PYODIDE_PROMPT,
                        form_data['messages'],
                        append=True,
                    )

    tool_ids = form_data.pop('tool_ids', None)
    terminal_id = form_data.pop('terminal_id', None)
    files = form_data.pop('files', None)
    form_data.pop('folder_id', None)

    # If the original caller provided tools, use them as-is (skip resolution).
    # Otherwise, save any tools that filter inlets added for merging later.
    inlet_filter_tools = None if payload_tools is not None else form_data.get('tools', None)

    # Mentioned skills get full content; selected/default skills can be loaded through view_skill.
    mentioned_skill_ids = extract_skill_ids_from_messages(form_data.get('messages', []))
    skill_ids = (
        set(form_data.pop('skill_ids', None) or [])
        | set(model.get('info', {}).get('meta', {}).get('skillIds', []))
        | mentioned_skill_ids
    )
    available_skills = []
    view_skill_ids = []
    use_builtin_tools = (
        bool(metadata.get('session_id'))
        and metadata.get('params', {}).get('function_calling') != 'legacy'
        and (model.get('info', {}).get('meta', {}).get('capabilities') or {}).get('builtin_tools', True)
    )

    if skill_ids:
        from open_webui.models.skills import Skills as SkillsModel

        accessible_skill_ids = {s.id for s in await SkillsModel.get_skills_by_user_id(user.id, 'read')}
        for sid in skill_ids:
            if sid in accessible_skill_ids:
                s = await SkillsModel.get_skill_by_id(sid)
                if s and s.is_active:
                    available_skills.append(s)

        skill_manifest = ''
        for skill in available_skills:
            if skill.id in mentioned_skill_ids or not use_builtin_tools:
                form_data['messages'] = add_or_update_system_message(
                    f'<skill name="{skill.name}">\n{skill.content}\n</skill>',
                    form_data['messages'],
                    append=True,
                )
            else:
                view_skill_ids.append(skill.id)
                skill_manifest += (
                    f'<skill>\n<id>{skill.id}</id>\n<name>{skill.name}</name>\n'
                    f'<description>{skill.description or ""}</description>\n</skill>\n'
                )

        if skill_manifest:
            form_data['messages'] = add_or_update_system_message(
                f'<available_skills>\n{skill_manifest}</available_skills>',
                form_data['messages'],
                append=True,
            )

    # Strip <$skillId|label> mention tags so the model doesn't see raw markup.
    strip_skill_mentions(form_data.get('messages', []))

    prompt = get_last_user_message(form_data['messages'])
    # TODO: re-enable URL extraction from prompt
    # urls = []
    # if prompt and len(prompt or "") < 500 and (not files or len(files) == 0):
    #     urls = extract_urls(prompt)

    if files:
        if not files:
            files = []

        for file_item in files:
            if file_item.get('type', 'file') == 'folder':
                # Get folder files
                folder_id = file_item.get('id', None)
                if folder_id:
                    folder = await Folders.get_folder_by_id_and_user_id(folder_id, user.id)
                    if folder and folder.data and 'files' in folder.data:
                        files = [f for f in files if f.get('id', None) != folder_id]
                        files = [*files, *folder.data['files']]

        # files = [*files, *[{"type": "url", "url": url, "name": url} for url in urls]]
        # Remove duplicate files based on their content
        files = list({json.dumps(f, sort_keys=True): f for f in files}.values())

    metadata = {
        **metadata,
        'model_id': form_data.get('model'),
        'tool_ids': tool_ids,
        'terminal_id': terminal_id,
        'files': files,
        'features': features,
    }
    form_data['metadata'] = metadata

    # When the caller provides an explicit `tools` key in the request body,
    # skip all server-side tool resolution and pass the caller's tools through
    # unchanged.  Sending `tools: []` explicitly opts out of builtin injection.
    if payload_tools is None:
        # Server side tools
        tool_ids = metadata.get('tool_ids', None)
        # Client side tools
        direct_tool_servers = metadata.get('tool_servers', None)

        log.debug(f'{tool_ids=}')
        log.debug(f'{direct_tool_servers=}')

        tools_dict = {}

        mcp_clients = {}
        mcp_tools_dict = {}

        if tool_ids:
            for tool_id in tool_ids:
                if tool_id.startswith('server:mcp:'):
                    try:
                        server_id = tool_id[len('server:mcp:') :]

                        connection = await connect_mcp_server(
                            request,
                            server_id,
                            user,
                            metadata,
                            extra_params,
                        )
                        if not connection:
                            continue

                        client, tool_specs = connection
                        mcp_clients[server_id] = client
                        for tool_spec in tool_specs:

                            async def make_tool_function(client, function_name):
                                async def tool_function(**kwargs):
                                    return await client.call_tool(
                                        function_name,
                                        function_args=kwargs,
                                    )

                                return tool_function

                            tool_function = await make_tool_function(mcp_clients[server_id], tool_spec['name'])

                            mcp_tools_dict[f'{server_id}_{tool_spec["name"]}'] = {
                                'spec': {
                                    **tool_spec,
                                    'name': f'{server_id}_{tool_spec["name"]}',
                                },
                                'callable': tool_function,
                                'type': 'mcp',
                                'client': mcp_clients[server_id],
                                'direct': False,
                            }
                    except Exception as e:
                        log.debug(e)
                        if event_emitter:
                            await event_emitter(
                                {
                                    'type': 'chat:message:error',
                                    'data': {'error': {'content': f"Failed to connect to MCP server '{server_id}'"}},
                                }
                            )
                        continue

            await _evict_stale_local_tool_cache(request, tool_ids)
            tools_dict = await get_tools(
                request,
                tool_ids,
                user,
                {
                    **extra_params,
                    '__model__': models[task_model_id],
                    '__messages__': form_data['messages'],
                    '__files__': metadata.get('files', []),
                },
            )
            await _remember_loaded_local_tool_contents(request, tool_ids)

            if mcp_tools_dict:
                tools_dict = {**tools_dict, **mcp_tools_dict}

        # Resolve terminal tools if terminal_id is set (outside tool_ids check
        # so system terminals work even when no other tools are selected)
        terminal_capability = (model.get('info', {}).get('meta', {}).get('capabilities') or {}).get('terminal', True)
        if terminal_id and terminal_capability:
            try:
                terminal_result = await get_terminal_tools(
                    request,
                    terminal_id,
                    user,
                    extra_params,
                )
                if isinstance(terminal_result, tuple):
                    terminal_tools, system_prompt = terminal_result
                else:
                    terminal_tools = terminal_result
                    system_prompt = None
                if terminal_tools:
                    tools_dict = {**tools_dict, **terminal_tools}
                if system_prompt:
                    form_data['messages'] = add_or_update_system_message(
                        system_prompt,
                        form_data['messages'],
                        append=True,
                    )
            except Exception as e:
                log.exception(e)

        if direct_tool_servers:
            for tool_server in direct_tool_servers:
                system_prompt = tool_server.pop('system_prompt', None)
                if system_prompt:
                    form_data['messages'] = add_or_update_system_message(
                        system_prompt,
                        form_data['messages'],
                        append=True,
                    )

                tool_specs = tool_server.pop('specs', [])

                for tool in tool_specs:
                    tools_dict[tool['name']] = {
                        'spec': tool,
                        'direct': True,
                        'server': tool_server,
                    }

        if mcp_clients:
            metadata['mcp_clients'] = mcp_clients

        # Inject builtin tools for native function calling based on enabled features and model capability.
        # Only inject when the request originates from the UI (identified by session_id).
        # API callers don't expect hidden tools; they can explicitly request tools via tool_ids.
        if use_builtin_tools:
            # Add file context to user messages
            chat_id = metadata.get('chat_id')
            form_data['messages'] = await add_file_context(form_data.get('messages', []), chat_id, user)
            builtin_tools = await get_builtin_tools(
                request,
                {
                    **extra_params,
                    '__event_emitter__': event_emitter,
                    '__skill_ids__': view_skill_ids,
                },
                features,
                model,
            )
            for name, tool_dict in builtin_tools.items():
                if name not in tools_dict:
                    tools_dict[name] = tool_dict

        original_user_tool_request = get_last_user_message(
            form_data.get('messages', []) or []
        )
        user_tool_request = _expanded_internal_rag_query(
            form_data.get('messages', []), original_user_tool_request or ''
        )
        permission_scope = _knowledge_harness_permission_scope(user)
        legacy_rag_request = (
            _looks_like_internal_rag_request(user_tool_request or '')
            or _is_internal_clarification_followup(
                form_data.get('messages', []) or [], user_tool_request or ''
            )
        )
        retrieval_plan = _plan_kahle_retrieval_gate(
            query=original_user_tool_request or '',
            resolved_query=user_tool_request or original_user_tool_request or '',
            messages=form_data.get('messages', []) or [],
            model_id=str(form_data.get('model') or ''),
            permission_scope=permission_scope,
            tools_dict=tools_dict,
            legacy_rag_request=legacy_rag_request,
            harness_mode=_knowledge_harness_mode(),
        )
        if _should_prepare_knowledge_route(
            tools_dict, retrieval_plan is not None
        ):
            # Always store resolved tools in metadata so downstream consumers
            # (e.g. pipe functions) can access all tools including MCP and builtins.
            if tools_dict:
                metadata['tools'] = tools_dict

            native_function_calling = metadata.get('params', {}).get('function_calling') != 'legacy'
            force_internal_rag = (
                native_function_calling
                and not metadata.get('kahle_mailer_drafting_followup')
                and _should_execute_kahle_retrieval(retrieval_plan, tools_dict)
            )

            pre_routed_internal_rag = ''
            if force_internal_rag:
                metadata['_kahle_harness_started_monotonic'] = time.monotonic()
                # The information-needs plan is fixed before either adapter is
                # invoked. Genuine mixed questions start both independent
                # retrievals concurrently.
                try:
                    pre_route_call_id = output_id('fc')
                    emit_prerouted_rag_status = _should_emit_prerouted_rag_status(
                        retrieval_plan
                    )
                    if emit_prerouted_rag_status:
                        metadata['kahle_prerouted_rag_tool_output'] = _prerouted_rag_tool_output(
                            pre_route_call_id, user_tool_request or '', completed=False,
                        )
                        if event_emitter:
                            await event_emitter({
                                'type': 'chat:completion',
                                'data': {'output': metadata['kahle_prerouted_rag_tool_output']},
                            })

                    async def retrieve_pre_route_rag() -> dict[str, Any]:
                        if 'rag_chat' not in tools_dict:
                            return {'form_data': None, 'sources': [], 'rag_result': ''}
                        pre_route_tools = {'rag_chat': tools_dict['rag_chat']}
                        pre_route_form_data = copy.deepcopy(form_data)
                        pre_route_metadata = pre_route_form_data.setdefault('metadata', {})
                        if user_tool_request != (original_user_tool_request or ''):
                            set_last_user_message_content(
                                user_tool_request,
                                pre_route_form_data.get('messages', []),
                            )
                        previous_information_needs = pre_route_metadata.get(
                            '_kahle_information_needs'
                        )
                        pre_route_metadata['_kahle_information_needs'] = [
                            {
                                'kind': str(getattr(need, 'kind', '') or ''),
                                'domain': str(getattr(need, 'domain', '') or ''),
                                'document_types': list(getattr(need, 'document_types', ()) or ()),
                                'evidence_capabilities': list(
                                    getattr(need, 'evidence_capabilities', ()) or ()
                                ),
                            }
                            for need in getattr(retrieval_plan, 'information_needs', ()) or ()
                        ]
                        try:
                            pre_route_form_data, flags = await chat_completion_tools_handler(
                                request,
                                pre_route_form_data,
                                extra_params,
                                user,
                                models,
                                pre_route_tools,
                            )
                        finally:
                            if previous_information_needs is None:
                                pre_route_metadata.pop('_kahle_information_needs', None)
                            else:
                                pre_route_metadata['_kahle_information_needs'] = (
                                    previous_information_needs
                                )
                        if user_tool_request != (original_user_tool_request or ''):
                            set_last_user_message_content(
                                original_user_tool_request or '',
                                pre_route_form_data.get('messages', []),
                            )
                        pre_route_sources = flags.get('sources', [])
                        if emit_prerouted_rag_status:
                            metadata['kahle_prerouted_rag_tool_output'] = _prerouted_rag_tool_output(
                                pre_route_call_id, user_tool_request or '', completed=True,
                            )
                            if event_emitter:
                                await event_emitter({
                                    'type': 'chat:completion',
                                    'data': {'output': metadata['kahle_prerouted_rag_tool_output']},
                                })
                        return {
                            'form_data': pre_route_form_data,
                            'sources': pre_route_sources,
                            'rag_result': rag_result_from_sources(pre_route_sources),
                        }

                    retrieval = await _execute_kahle_retrieval_plan(
                        retrieval_plan,
                        query=user_tool_request or original_user_tool_request or '',
                        directory_intent=_personio_directory_intent(
                            user_tool_request or original_user_tool_request or ''
                        ),
                        supervisor_candidate_query=_supervisor_candidate_query(
                            form_data.get('messages', []) or [],
                            user_tool_request or original_user_tool_request or '',
                        ),
                        user_id=str(permission_scope.get('user_id') or ''),
                        user_role=str(permission_scope.get('role') or ''),
                        personio_client=PersonioDirectoryClient(),
                        rag_retriever=retrieve_pre_route_rag,
                        metadata=metadata,
                    )
                    rag_execution = retrieval['rag_result']
                    if isinstance(rag_execution, dict):
                        if rag_execution.get('form_data') is not None:
                            form_data = rag_execution['form_data']
                        pre_route_sources = list(rag_execution.get('sources') or [])
                        pre_route_rag_result = str(rag_execution.get('rag_result') or '')
                    else:
                        pre_route_sources = []
                        pre_route_rag_result = str(rag_execution or '')
                    sources.extend(pre_route_sources)
                    pre_routed_internal_rag = (
                        'forbidden'
                        if metadata.get('kahle_retrieval_access_denied')
                        else _internal_rag_source_outcome(pre_route_sources)
                        if 'rag_chat' in retrieval_plan.required_tools
                        else 'not_required'
                    )
                    canonical_pre_route_sources = _extract_kahle_rag_sources(
                        pre_route_rag_result
                    )
                    canonical_pre_route_events = _canonical_kahle_rag_source_events(
                        canonical_pre_route_sources
                    )
                    sources[:] = [
                        source
                        for source in sources
                        if 'rag_chat' not in str(
                            (source.get('source') or {}).get('name') or ''
                        ).lower()
                    ]
                    if canonical_pre_route_events:
                        sources.extend(canonical_pre_route_events)
                    metadata['kahle_canonical_rag_sources'] = canonical_pre_route_sources
                    metadata['kahle_canonical_rag_feedback_link'] = (
                        _extract_kahle_rag_feedback_link(pre_route_rag_result)
                    )
                    if pre_routed_internal_rag:
                        metadata['kahle_internal_rag_prerouted'] = pre_routed_internal_rag
                    harness_mode = _knowledge_harness_mode()
                    harness_decision = None
                    if harness_mode != 'off':
                        harness_decision = build_knowledge_harness_decision(
                            query=original_user_tool_request or '',
                            resolved_query=user_tool_request or original_user_tool_request or '',
                            messages=form_data.get('messages', []) or [],
                            model_id=str(form_data.get('model') or ''),
                            permission_scope=permission_scope,
                            rag_result=pre_route_rag_result,
                            personio_result=retrieval['personio_result'],
                        )
                        harness_payload = harness_decision.to_dict()
                        _store_ephemeral_kahle_harness_payload(
                            request, harness_payload
                        )
                        shadow_decision = _knowledge_harness_metadata_payload(
                            harness_decision
                        )
                        metadata['kahle_knowledge_harness_shadow'] = shadow_decision
                        if harness_mode == 'active':
                            metadata['kahle_knowledge_harness_active'] = True
                            metadata['kahle_answer_contract'] = harness_payload[
                                'answer_contract'
                            ]
                            form_data['messages'] = add_or_update_system_message(
                                harness_decision.answer_prompt(),
                                form_data.get('messages', []) or [],
                                append=True,
                            )
                            direct_answer = _knowledge_harness_direct_answer(
                                harness_decision, harness_payload
                            )
                            if direct_answer:
                                metadata['kahle_direct_final_content'] = direct_answer
                            metadata['kahle_answer_validation_fallback'] = (
                                harness_decision.validation_fallback()
                            )
                    if harness_mode != 'active' and pre_routed_internal_rag == 'clarification':
                        metadata['kahle_direct_final_content'] = (
                            _internal_rag_clarification(pre_route_sources)
                            or 'Bitte grenze deine Frage noch etwas genauer ein.'
                        )
                    elif harness_mode != 'active' and pre_routed_internal_rag == 'missing':
                        metadata['kahle_direct_final_content'] = 'Dazu habe ich kein internes Wissen.'
                except Exception as e:
                    # Keep native tools available as a recovery path. The
                    # streaming guard below still suppresses an unsupported
                    # direct answer until the RAG fallback has completed.
                    log.exception(e)

            if native_function_calling:
                # Native tools remain available for all other capabilities and
                # as a fallback if the deterministic pre-route failed.
                native_tools_dict = {
                    name: tool
                    for name, tool in tools_dict.items()
                    if not (
                        name == 'rag_chat'
                        and (
                            metadata.get('kahle_mailer_drafting_followup')
                            or (force_internal_rag and pre_routed_internal_rag)
                        )
                    )
                }
                if native_tools_dict:
                    form_data['tools'] = [
                        {'type': 'function', 'function': tool.get('spec', {})}
                        for tool in native_tools_dict.values()
                    ]
                else:
                    form_data.pop('tools', None)
                if inlet_filter_tools:
                    if 'tools' not in form_data:
                        form_data['tools'] = []
                    form_data['tools'].extend(inlet_filter_tools)
            elif tools_dict:
                # If the function calling is not native, then call the tools function calling handler
                try:
                    legacy_tools_dict = {
                        name: tool
                        for name, tool in tools_dict.items()
                        if not (
                            name == 'rag_chat'
                            and (
                                metadata.get('kahle_mailer_drafting_followup')
                                or (force_internal_rag and pre_routed_internal_rag)
                            )
                        )
                    }
                    if legacy_tools_dict:
                        form_data, flags = await chat_completion_tools_handler(
                            request,
                            form_data,
                            extra_params,
                            user,
                            models,
                            legacy_tools_dict,
                        )
                        sources.extend(flags.get('sources', []))
                except Exception as e:
                    log.exception(e)

    # Check if file context extraction is enabled for this model (default True).
    # KAHLE-Vinci manages knowledge via kb-sync + Qdrant and uses uploaded files
    # through the file-proxy tools. Do not auto-run OpenWebUI file RAG here,
    # because that triggers IONOS embeddings on every upload even when the user
    # only wants deterministic conversion.
    file_context_enabled = (model.get('info', {}).get('meta', {}).get('capabilities') or {}).get('file_context', True)
    if _env_flag('BYPASS_EMBEDDING_AND_RETRIEVAL', default=False):
        file_context_enabled = False

    if file_context_enabled:
        try:
            form_data, flags = await chat_completion_files_handler(request, form_data, extra_params, user)
            sources.extend(flags.get('sources', []))
        except Exception as e:
            log.exception(e)

    # Save the pre-RAG message state so the native tool call loop can
    # restore to the true original (before file-source injection) rather
    # than a snapshot that already has the RAG template baked in.
    system_message = get_system_message(form_data['messages'])
    system_content = get_content_from_message(system_message) if system_message else ''
    model_system_prompt = await resolve_system_prompt(
        (form_data.get('params') or {}).get('system'),
        metadata,
        user,
    )
    if model_system_prompt:
        system_content = f'{model_system_prompt}\n{system_content}' if system_content else model_system_prompt
    metadata['system_prompt'] = system_content or None
    metadata['user_prompt'] = get_last_user_message(form_data['messages'])
    metadata['sources'] = sources[:] if sources else []

    # If context is not empty, insert it into the messages
    if sources and prompt:
        form_data['messages'] = await apply_source_context_to_messages(
            request, form_data['messages'], sources, prompt
        )

        successful_internal_rag = any(
            'rag_chat' in str((source.get('source') or {}).get('name') or '').lower()
            and 'found: true'
            in '\n'.join(str(item) for item in source.get('document', [])).lower()
            for source in sources
            if isinstance(source, dict)
        )
        generated_file_result = any(
            'kahle_workflow' in str((source.get('source') or {}).get('name') or '').lower()
            and any(
                marker
                in '\n'.join(str(item) for item in source.get('document', [])).lower()
                for marker in ('download_url', 'download-link', 'datei herunterladen')
            )
            for source in sources
            if isinstance(source, dict)
        )

        # Tool selection and tool execution are complete at this point. Give
        # the answer model an explicit continuation instruction so it treats
        # the injected result as authoritative context instead of repeating a
        # pre-tool refusal/promise. The outlet guard remains a last-resort
        # safety net only.
        if successful_internal_rag:
            form_data['messages'] = add_or_update_system_message(
                'WICHTIG: Das interne KAHLE-Wissenswerkzeug wurde bereits erfolgreich ausgefuehrt. '
                'Das gefundene Ergebnis steht vollstaendig im obigen <source>-Kontext. '
                'Beantworte die urspruengliche Nutzerfrage JETZT direkt und ausschliesslich aus diesem Kontext. '
                'Behaupte NICHT, es gebe kein internes Wissen oder keine Informationen. '
                'Kennzeichne jede interne Tatsachenaussage mit der passenden Quellenmarke [#]. '
                'Rufe KEIN weiteres Tool auf und gib KEINE Tool-Aufruf-Syntax aus.',
                form_data['messages'],
                append=True,
            )
        elif generated_file_result:
            form_data['messages'] = add_or_update_system_message(
                'WICHTIG: Der angeforderte Datei-Workflow wurde bereits erfolgreich ausgefuehrt. '
                'Das echte Ergebnis mit Download-Link und Dateimetadaten steht im obigen <source>-Kontext. '
                'Gib dieses Ergebnis JETZT direkt aus. Uebernimm den vorhandenen Download-Link exakt und erfinde keinen neuen. '
                'Schreibe NICHT, dass du die Datei erst noch erstellen wirst, und rufe KEIN weiteres Tool auf.',
                form_data['messages'],
                append=True,
            )

        # When a web-search tool already produced results, Mistral tends to print
        # a {"tool": "safe_webcaller", ...} JSON as its visible answer (or nothing)
        # instead of synthesising — its tool-routing system prompt outweighs the
        # injected context. Append a high-salience directive so the model answers
        # directly and streams the answer (no outlet-guard round trip needed).
        if any(
            'safe_web' in str((s.get('source') or {}).get('name') or '')
            for s in sources
            if isinstance(s, dict)
        ):
            form_data['messages'] = add_or_update_system_message(
                'WICHTIG: Die Websuche wurde bereits ausgefuehrt; die Rechercheergebnisse inklusive der Quell-URLs stehen oben im Kontext. '
                'Du hast alle noetigen Informationen — frage NICHT nach Quellen und behaupte NICHT, dir lägen keine Informationen vor. '
                'Beantworte die Frage des Nutzers JETZT direkt und ausschliesslich auf Basis dieser Ergebnisse, auf Deutsch, '
                'klar strukturiert mit kurzer Zusammenfassung. Beende deine Antwort mit einem Abschnitt "Quellen" und '
                'schreibe dort jede genutzte Quelle als vollstaendigen anklickbaren Markdown-Link [Titel](URL) AUS — '
                'kopiere die echten Titel und URLs direkt aus dem obigen Kontext in deine Antwort. '
                'Verweise NICHT nur darauf, dass die Quellen im Kontext stehen, sondern gib die Links tatsaechlich aus. '
                'Rufe KEIN Tool mehr auf und gib KEINE JSON- oder Tool-Aufruf-Syntax wie {"tool": ...} oder [TOOL_CALLS] aus.',
                form_data['messages'],
                append=True,
            )

    # If there are citations, add them to the data_items
    sources = [
        source
        for source in sources
        if source.get('source', {}).get('name', '') or source.get('source', {}).get('id', '')
    ]

    if len(sources) > 0:
        events.append({'sources': sources})

    if model_knowledge:
        await event_emitter(
            {
                'type': 'status',
                'data': {
                    'action': 'knowledge_search',
                    'query': user_message,
                    'done': True,
                    'hidden': True,
                },
            }
        )

    # Strip empty text content blocks from multimodal messages
    # to prevent errors from providers like Gemini and Claude
    form_data['messages'] = strip_empty_content_blocks(form_data.get('messages', []))

    # Merge any duplicate system messages into a single message at position 0
    # to prevent template parsing errors with strict chat templates (e.g. Qwen)
    form_data['messages'] = merge_system_messages(form_data.get('messages', []))

    return form_data, metadata, events


async def get_event_emitter_and_caller(metadata):
    event_emitter = None
    event_caller = None

    # event_emitter only needs user_id + chat_id + message_id.
    # It broadcasts to user:{user_id} room AND persists to DB,
    # so it works for backend-initiated calls (automations, API).
    if metadata.get('chat_id') and metadata.get('message_id'):
        event_emitter = await get_event_emitter(metadata)

    # event_caller needs session_id — it calls back to a specific
    # websocket session (used by direct tools, pyodide code interpreter).
    if metadata.get('session_id') and metadata.get('chat_id') and metadata.get('message_id'):
        event_caller = await get_event_call(metadata)

    return event_emitter, event_caller


async def build_chat_response_context(request, form_data, user, model, metadata, tasks, events):
    event_emitter, event_caller = await get_event_emitter_and_caller(metadata)
    return {
        'request': request,
        'form_data': form_data,
        'user': user,
        'model': model,
        'metadata': metadata,
        'tasks': tasks,
        'events': events,
        'event_emitter': event_emitter,
        'event_caller': event_caller,
    }


def get_response_data(response):
    if isinstance(response, list) and len(response) == 1:
        # If the response is a single-item list, unwrap it #17213
        response = response[0]

    if isinstance(response, JSONResponse):
        if isinstance(response.body, bytes):
            try:
                response_data = json.loads(response.body.decode('utf-8', 'replace'))
            except json.JSONDecodeError:
                response_data = {'error': {'detail': 'Invalid JSON response'}}
        else:
            response_data = response
    elif isinstance(response, dict):
        response_data = response
    else:
        response_data = None

    return response, response_data


def merge_events_into_response(response_data, events):
    if events and isinstance(events, list):
        extra_response = {}
        for event in events:
            if isinstance(event, dict):
                extra_response.update(event)
            else:
                extra_response[event] = True

        return {
            **extra_response,
            **response_data,
        }
    return response_data


def build_response_object(response, response_data):
    if isinstance(response, dict):
        return response_data
    if isinstance(response, JSONResponse):
        return JSONResponse(
            content=response_data,
            headers=response.headers,
            status_code=response.status_code,
        )
    return response


def update_assistant_message_from_stream(assistant_message, raw):
    line = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw
    if not isinstance(line, str):
        return

    def append_output_text(item, text):
        parts = item.setdefault('content', [])
        if parts and parts[-1].get('type') == 'output_text':
            parts[-1]['text'] += text
        else:
            parts.append({'type': 'output_text', 'text': text})

    for raw_part in line.splitlines():
        part = raw_part.removeprefix('data:').strip()
        if not part or part == '[DONE]':
            continue

        try:
            data = json.loads(part)
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        if data.get('type', '').startswith('response.'):
            output, meta = handle_responses_streaming_event(data, assistant_message.get('output', []))
            if output:
                assistant_message['output'] = output
            if meta and meta.get('usage'):
                assistant_message['usage'] = merge_usage(assistant_message.get('usage'), meta['usage'])
            continue

        raw_usage = data.get('usage', {}) or {}
        raw_usage.update(data.get('timings', {}))
        if raw_usage:
            assistant_message['usage'] = merge_usage(assistant_message.get('usage'), raw_usage)

        for choice in data.get('choices', []):
            delta = choice.get('delta', {}) or {}
            content = delta.get('content')
            reasoning_content = delta.get('reasoning_content') or delta.get('reasoning') or delta.get('thinking')

            if reasoning_content:
                output = assistant_message.setdefault('output', [])
                if not output or output[-1].get('type') != 'reasoning':
                    output.append(
                        {
                            'type': 'reasoning',
                            'id': output_id('r'),
                            'status': 'in_progress',
                            'start_tag': '<think>',
                            'end_tag': '</think>',
                            'attributes': {'type': 'reasoning_content'},
                            'content': [],
                            'summary': None,
                            'started_at': time.time(),
                        }
                    )

                append_output_text(output[-1], reasoning_content)

            if content:
                output = assistant_message.get('output')
                if output:
                    if output[-1].get('type') == 'reasoning':
                        output[-1]['status'] = 'completed'
                        output[-1]['ended_at'] = time.time()
                        output[-1]['duration'] = int(output[-1]['ended_at'] - output[-1]['started_at'])

                    if not output or output[-1].get('type') != 'message':
                        output.append(
                            {
                                'type': 'message',
                                'id': output_id('msg'),
                                'status': 'in_progress',
                                'role': 'assistant',
                                'content': [],
                            }
                        )

                    append_output_text(output[-1], content)

                assistant_message['content'] = assistant_message.get('content', '') + content


async def get_system_oauth_token(request, user):
    """Get the system OAuth token for a user.

    Primary path: use the oauth_session_id cookie (browser requests).
    Fallback: look up the user's most recent OAuth session from the DB
    (covers automations, API calls, and other cookie-less contexts).
    """
    oauth_token = None
    try:
        oauth_session_id = request.cookies.get('oauth_session_id', None)
        if oauth_session_id:
            oauth_token = await request.app.state.oauth_manager.get_oauth_token(
                user.id,
                oauth_session_id,
            )

        # Fallback: no cookie (automation, API key, etc.) — use most recent session
        if oauth_token is None:
            from open_webui.models.oauth_sessions import OAuthSessions

            sessions = await OAuthSessions.get_sessions_by_user_id(user.id)
            if sessions:
                best = max(sessions, key=lambda s: s.updated_at)
                oauth_token = await request.app.state.oauth_manager.get_oauth_token(
                    user.id,
                    best.id,
                )
    except Exception as e:
        log.error(f'Error getting OAuth token: {e}')
    return oauth_token


async def background_tasks_handler(ctx):
    request = ctx['request']
    form_data = ctx['form_data']
    user = ctx['user']
    metadata = ctx['metadata']
    tasks = ctx['tasks']
    event_emitter = ctx['event_emitter']

    message = None
    messages = []

    if 'chat_id' in metadata and not metadata['chat_id'].startswith('local:'):
        messages_map = await Chats.get_messages_map_by_chat_id(metadata['chat_id'])
        message = messages_map.get(metadata['message_id']) if messages_map else None

        message_list = get_message_list(messages_map, metadata['message_id'])

        # Remove details tags and files from the messages.
        # as get_message_list creates a new list, it does not affect
        # the original messages outside of this handler

        messages = []
        for message in message_list:
            content = message.get('content', '')
            if isinstance(content, list):
                for item in content:
                    if item.get('type') == 'text':
                        content = item['text']
                        break

            if isinstance(content, str):
                content = re.sub(
                    r'<details\b[^>]*>.*?<\/details>|!\[.*?\]\(.*?\)',
                    '',
                    content,
                    flags=re.S | re.I,
                ).strip()

            messages.append(
                {
                    **message,
                    'role': message.get('role', 'assistant'),  # Safe fallback for missing role
                    'content': content,
                }
            )
    else:
        # Local temp chat, get the model and message from the form_data
        message = get_last_user_message_item(form_data.get('messages', []))
        messages = form_data.get('messages', [])
        if message:
            message['model'] = form_data.get('model')

    if message and 'model' in message:
        if tasks and messages:
            if TASKS.FOLLOW_UP_GENERATION in tasks and tasks[TASKS.FOLLOW_UP_GENERATION]:
                res = await generate_follow_ups(
                    request,
                    {
                        'model': message['model'],
                        'messages': messages,
                        'message_id': metadata['message_id'],
                        'chat_id': metadata['chat_id'],
                    },
                    user,
                )

                if res and isinstance(res, dict):
                    if len(res.get('choices', [])) == 1:
                        response_message = res.get('choices', [])[0].get('message', {})

                        follow_ups_string = response_message.get('content') or response_message.get(
                            'reasoning_content', ''
                        )
                    else:
                        follow_ups_string = ''

                    follow_ups_string = follow_ups_string[
                        follow_ups_string.find('{') : follow_ups_string.rfind('}') + 1
                    ]

                    try:
                        follow_ups = json.loads(follow_ups_string).get('follow_ups', [])
                        await event_emitter(
                            {
                                'type': 'chat:message:follow_ups',
                                'data': {
                                    'follow_ups': follow_ups,
                                },
                            }
                        )

                        if not metadata.get('chat_id', '').startswith('local:'):
                            await Chats.upsert_message_to_chat_by_id_and_message_id(
                                metadata['chat_id'],
                                metadata['message_id'],
                                {
                                    'followUps': follow_ups,
                                },
                            )

                    except Exception as e:
                        pass

            if not metadata.get('chat_id', '').startswith('local:'):  # Only update titles and tags for non-temp chats
                if TASKS.TITLE_GENERATION in tasks:
                    user_message = get_last_user_message(messages)
                    if user_message and len(user_message) > 100:
                        user_message = user_message[:100] + '...'

                    title = None
                    if tasks[TASKS.TITLE_GENERATION]:
                        res = await generate_title(
                            request,
                            {
                                'model': message['model'],
                                'messages': messages,
                                'chat_id': metadata['chat_id'],
                            },
                            user,
                        )

                        if res and isinstance(res, dict):
                            if len(res.get('choices', [])) == 1:
                                response_message = res.get('choices', [])[0].get('message', {})

                                title_string = (
                                    response_message.get('content')
                                    or response_message.get(
                                        'reasoning_content',
                                    )
                                    or message.get('content', user_message)
                                )
                            else:
                                title_string = ''

                            title_string = title_string[title_string.find('{') : title_string.rfind('}') + 1]

                            try:
                                title = json.loads(title_string).get('title', user_message)
                            except Exception as e:
                                title = ''

                            if not title:
                                title = messages[0].get('content', user_message)

                            await Chats.update_chat_title_by_id(metadata['chat_id'], title)

                            await event_emitter(
                                {
                                    'type': 'chat:title',
                                    'data': title,
                                }
                            )

                    if title == None and len(messages) == 2 and (not messages_map or len(messages_map) <= 2):
                        title = messages[0].get('content', user_message)

                        await Chats.update_chat_title_by_id(metadata['chat_id'], title)

                        await event_emitter(
                            {
                                'type': 'chat:title',
                                'data': message.get('content', user_message),
                            }
                        )

                if TASKS.TAGS_GENERATION in tasks and tasks[TASKS.TAGS_GENERATION]:
                    res = await generate_chat_tags(
                        request,
                        {
                            'model': message['model'],
                            'messages': messages,
                            'chat_id': metadata['chat_id'],
                        },
                        user,
                    )

                    if res and isinstance(res, dict):
                        if len(res.get('choices', [])) == 1:
                            response_message = res.get('choices', [])[0].get('message', {})

                            tags_string = response_message.get('content') or response_message.get(
                                'reasoning_content', ''
                            )
                        else:
                            tags_string = ''

                        tags_string = tags_string[tags_string.find('{') : tags_string.rfind('}') + 1]

                        try:
                            tags = json.loads(tags_string).get('tags', [])
                            await Chats.update_chat_tags_by_id(metadata['chat_id'], tags, user)

                            await event_emitter(
                                {
                                    'type': 'chat:tags',
                                    'data': tags,
                                }
                            )
                        except Exception as e:
                            pass

        if messages:
            await review_memory_after_turn(
                request=request,
                user=user,
                model=ctx['model'],
                metadata=metadata,
                form_data=form_data,
                assistant_message=ctx.get('assistant_message') or {},
                messages=messages,
            )


async def outlet_filter_handler(ctx):
    """Run outlet filters inline after chat completion.

    Replaces the separate POST /api/chat/completed round-trip.
    Persists outlet-modified content to DB and emits a chat:outlet event
    so the frontend can sync its in-memory state.

    For temp/API chats, messages are built from form_data plus ctx['assistant_message'].
    """
    request = ctx['request']
    user = ctx['user']
    model = ctx['model']
    metadata = ctx['metadata']
    event_emitter = ctx.get('event_emitter')
    event_caller = ctx.get('event_caller')

    chat_id = metadata.get('chat_id', '')
    message_id = metadata.get('message_id')

    if not chat_id and not ctx.get('assistant_message'):
        return

    if not message_id:
        message_id = output_id('msg')

    is_temp_chat = chat_id.startswith('local:') or chat_id.startswith('channel:')
    try:
        messages_map = None

        if is_temp_chat or not chat_id:
            form_messages = ctx.get('form_data', {}).get('messages', [])
            assistant_message = ctx.get('assistant_message', {})

            message_list = [
                {
                    'role': m.get('role'),
                    'content': m.get('content', ''),
                }
                for m in form_messages
            ]

            if assistant_message:
                message_list.append(
                    {
                        'id': message_id,
                        'role': 'assistant',
                        **assistant_message,
                    }
                )

            if not message_list:
                return
        else:
            messages_map = await Chats.get_messages_map_by_chat_id(chat_id)
            if not messages_map:
                return

            message_list = get_message_list(messages_map, message_id)
            if not message_list:
                return

        model_id = model.get('id') if isinstance(model, dict) else model

        outlet_data = {
            'model': model_id,
            'messages': [
                {
                    'id': m.get('id'),
                    'role': m.get('role'),
                    'content': m.get('content', ''),
                    'info': m.get('info'),
                    'timestamp': m.get('timestamp'),
                    **({'output': m['output']} if m.get('output') else {}),
                    **({'usage': m['usage']} if m.get('usage') else {}),
                    **({'sources': m['sources']} if m.get('sources') else {}),
                }
                for m in message_list
            ],
            'filter_ids': metadata.get('filter_ids', []),
            'chat_id': chat_id,
            'session_id': metadata.get('session_id'),
            'id': message_id,
        }

        # Pipeline outlet filters
        models = request.app.state.MODELS
        try:
            outlet_data = await process_pipeline_outlet_filter(request, outlet_data, user, models)
        except Exception as e:
            log.debug(f'Pipeline outlet filter error: {e}')

        # Function outlet filters
        extra_params = {
            '__event_emitter__': event_emitter,
            '__event_call__': event_caller,
            '__user__': user.model_dump() if isinstance(user, UserModel) else {},
            '__metadata__': metadata,
            '__request__': request,
            '__model__': model,
        }

        filter_ids = await get_sorted_filter_ids(request, model, metadata.get('filter_ids', []))
        filter_functions = await Functions.get_functions_by_ids(filter_ids)

        outlet_result, _ = await process_filter_functions(
            request=request,
            filter_context=None,
            filter_functions=filter_functions,
            filter_type='outlet',
            form_data=outlet_data,
            extra_params=extra_params,
        )

        if outlet_result and outlet_result.get('messages'):
            if not is_temp_chat and messages_map:
                for message in outlet_result['messages']:
                    outlet_message_id = message.get('id')
                    if outlet_message_id and outlet_message_id in messages_map:
                        original_message = messages_map[outlet_message_id]
                        content_changed = original_message.get('content') != message.get('content')
                        output_changed = message.get('output') and message.get('output') != original_message.get(
                            'output'
                        )
                        if content_changed or output_changed:
                            message_update = {
                                'originalContent': original_message.get('content'),
                                **({'output': message['output']} if output_changed else {}),
                            }
                            if content_changed:
                                message_update['content'] = message.get('content', '')
                            await Chats.upsert_message_to_chat_by_id_and_message_id(
                                chat_id,
                                outlet_message_id,
                                message_update,
                            )

            if event_emitter:
                current_outlet_message = next(
                    (
                        message
                        for message in outlet_result['messages']
                        if message.get('id') == message_id
                    ),
                    None,
                )
                await event_emitter(
                    {
                        'type': 'chat:outlet',
                        'data': {'messages': outlet_result['messages']},
                    }
                )
                # Replace the live streamed message with the canonical outlet content.
                if current_outlet_message and current_outlet_message.get('content') is not None:
                    await event_emitter(
                        {
                            'type': 'replace',
                            'data': {'content': current_outlet_message['content']},
                        }
                    )
    except Exception as e:
        log.debug(f'Error running outlet filters: {e}')


async def non_streaming_chat_response_handler(response, ctx):
    request = ctx['request']

    user = ctx['user']
    metadata = ctx['metadata']
    events = ctx['events']

    event_emitter = ctx['event_emitter']

    response, response_data = get_response_data(response)
    if response_data is None:
        return response

    direct_final_content = str(metadata.get('kahle_direct_final_content') or '').strip()
    if direct_final_content and 'error' not in response_data:
        choices = response_data.get('choices')
        if not choices:
            choices = [{'index': 0, 'message': {'role': 'assistant', 'content': ''}, 'finish_reason': 'stop'}]
            response_data['choices'] = choices
        choices[0].setdefault('message', {})['content'] = direct_final_content
        response_data['output'] = [
            {
                'type': 'message',
                'id': output_id('msg'),
                'status': 'completed',
                'role': 'assistant',
                'content': [{'type': 'output_text', 'text': direct_final_content}],
            }
        ]

    if event_emitter:
        try:
            if 'error' in response_data:
                error = response_data.get('error')

                if isinstance(error, dict):
                    error = error.get('detail', error)
                else:
                    error = str(error)

                log.error('Provider returned error (non-streaming): %s', error)

                await Chats.upsert_message_to_chat_by_id_and_message_id(
                    metadata['chat_id'],
                    metadata['message_id'],
                    {
                        'error': {'content': error},
                    },
                )
                if isinstance(error, str) or isinstance(error, dict):
                    await event_emitter(
                        {
                            'type': 'chat:message:error',
                            'data': {'error': {'content': error}},
                        }
                    )

            if 'selected_model_id' in response_data:
                await Chats.upsert_message_to_chat_by_id_and_message_id(
                    metadata['chat_id'],
                    metadata['message_id'],
                    {
                        'selectedModelId': response_data['selected_model_id'],
                    },
                )

            choices = response_data.get('choices', [])
            response_output = response_data.get('output')
            content = choices[0].get('message', {}).get('content') if choices else ''

            if choices and (content or response_output):
                if content or response_output:
                    await event_emitter(
                        {
                            'type': 'chat:completion',
                            'data': response_data,
                        }
                    )

                    title = await Chats.get_chat_title_by_id(metadata['chat_id'])

                    # Use output from backend if provided (OR-compliant backends),
                    # otherwise generate from response content
                    if not response_output:
                        choice_message = choices[0].get('message', {})
                        reasoning_content = choice_message.get('reasoning_content') or choice_message.get('reasoning')
                        reasoning_details = choice_message.get('reasoning_details')
                        response_output = []
                        if reasoning_content or reasoning_details:
                            reasoning_item = {
                                'type': 'reasoning',
                                'id': output_id('r'),
                                'status': 'completed',
                                'start_tag': '<think>',
                                'end_tag': '</think>',
                                'attributes': {'type': 'reasoning_content'},
                                'content': (
                                    [{'type': 'output_text', 'text': reasoning_content}] if reasoning_content else []
                                ),
                                'summary': None,
                            }
                            if reasoning_details:
                                reasoning_item['reasoning_details'] = (
                                    reasoning_details if isinstance(reasoning_details, list) else [reasoning_details]
                                )
                            response_output.append(reasoning_item)
                        response_output.append(
                            {
                                'type': 'message',
                                'id': output_id('msg'),
                                'status': 'completed',
                                'role': 'assistant',
                                'content': [{'type': 'output_text', 'text': content}],
                            }
                        )
                    prerouted_tool_output = list(
                        metadata.get('kahle_prerouted_rag_tool_output') or []
                    )
                    if prerouted_tool_output:
                        response_output = prerouted_tool_output + response_output

                    await event_emitter(
                        {
                            'type': 'chat:completion',
                            'data': {
                                'done': True,
                                'output': response_output,
                                'title': title,
                            },
                        }
                    )

                    # Save message in the database
                    usage = normalize_usage(response_data.get('usage', {}) or {})

                    if not metadata.get('chat_id', '').startswith('channel:'):
                        await Chats.upsert_message_to_chat_by_id_and_message_id(
                            metadata['chat_id'],
                            metadata['message_id'],
                            {
                                'done': True,
                                'role': 'assistant',
                                'output': response_output,
                                **({'usage': usage} if usage else {}),
                            },
                        )

                    # Send a webhook notification if the user is not active
                    if await Config.get('ui.enable_user_webhooks') and not await Users.is_user_active(user.id):
                        webhook_url = await Users.get_user_webhook_url_by_id(user.id)
                        if webhook_url:
                            webui_url = await Config.get('webui.url')
                            await post_webhook(
                                request.app.state.WEBUI_NAME,
                                webhook_url,
                                f'{content}\n\n{title} - {webui_url}/c/{metadata["chat_id"]}',
                                {
                                    'action': 'chat',
                                    'message': content,
                                    'title': title,
                                    'url': f'{webui_url}/c/{metadata["chat_id"]}',
                                },
                            )

                    await background_tasks_handler(ctx)
                    ctx['assistant_message'] = {
                        'content': content,
                        'output': response_output,
                        **({'usage': usage} if usage else {}),
                    }
                    await outlet_filter_handler(ctx)

            response = build_response_object(response, merge_events_into_response(response_data, events))
        except Exception as e:
            log.debug(f'Error occurred while processing request: {e}')
            pass

        return response

    choices = response_data.get('choices', [])
    output = response_data.get('output')
    content = choices[0].get('message', {}).get('content') if choices else ''
    if ENABLE_API_OUTLET_FILTERS and (content or output):
        usage = normalize_usage(response_data.get('usage', {}) or {})
        ctx['assistant_message'] = {
            **({'content': content} if content else {}),
            **({'output': output} if output else {}),
            **({'usage': usage} if usage else {}),
        }
        await outlet_filter_handler(ctx)

    if isinstance(response, dict):
        response = merge_events_into_response(response_data, events)

    return response


async def streaming_chat_response_handler(response, ctx):
    request = ctx['request']

    form_data = ctx['form_data']

    user = ctx['user']
    model = ctx['model']

    metadata = ctx['metadata']
    direct_final_content = str(metadata.get('kahle_direct_final_content') or '').strip()
    events = ctx['events']

    event_emitter = ctx['event_emitter']
    event_caller = ctx['event_caller']

    extra_params = {
        '__event_emitter__': event_emitter,
        '__event_call__': event_caller,
        '__user__': user.model_dump() if isinstance(user, UserModel) else {},
        '__metadata__': metadata,
        '__oauth_token__': await get_system_oauth_token(request, user),
        '__request__': request,
        '__model__': model,
    }

    filter_functions = [
        await Functions.get_function_by_id(filter_id)
        for filter_id in await get_sorted_filter_ids(request, model, metadata.get('filter_ids', []))
    ]

    # Standard streaming response handler
    # event_caller is optional — only needed for direct (client-side) tools
    # and pyodide code interpreter. Server-side tools work without it.
    if event_emitter:
        task_id = str(uuid4())  # Create a unique task ID.
        model_id = form_data.get('model', '')

        # Handle as a background task
        async def response_handler(response, events):
            filter_context = FilterContext()

            def tag_output_handler(content_type, tags, output):
                """
                Detect special tags (reasoning, solution, code_interpreter) in streaming
                content and create corresponding OR-aligned output items directly.
                Operates on output items instead of content_blocks.

                Uses the text from the output items themselves for tag detection,
                eliminating state divergence between accumulated content and items.
                """
                end_flag = False

                def extract_attributes(tag_content):
                    """Extract attributes from a tag if they exist."""
                    attributes = {}
                    if not tag_content:
                        return attributes
                    matches = re.findall(r'(\w+)\s*=\s*"([^"]+)"', tag_content)
                    for key, value in matches:
                        attributes[key] = value
                    return attributes

                def get_last_text(out):
                    """Get text from last message item, or empty string."""
                    if out and out[-1].get('type') == 'message':
                        parts = out[-1].get('content', [])
                        if parts and parts[-1].get('type') == 'output_text':
                            return parts[-1].get('text', '')
                    return ''

                def set_last_text(out, text):
                    """Set text on last message item's output_text."""
                    if out and out[-1].get('type') == 'message':
                        parts = out[-1].get('content', [])
                        if parts and parts[-1].get('type') == 'output_text':
                            parts[-1]['text'] = text

                # Map content_type to output item type
                output_type_map = {
                    'reasoning': 'reasoning',
                    'solution': 'message',  # solution tags just produce text
                    'code_interpreter': 'open_webui:code_interpreter',
                }
                output_item_type = output_type_map.get(content_type, content_type)

                last_type = output[-1].get('type', '') if output else ''

                if last_type == 'message':
                    # Use the output item's own text for tag detection
                    item_text = get_last_text(output)
                    for start_tag, end_tag in tags:
                        start_tag_pattern = rf'{re.escape(start_tag)}'
                        if start_tag.startswith('<') and start_tag.endswith('>'):
                            start_tag_pattern = rf'<{re.escape(start_tag[1:-1])}(\s.*?)?>'

                        match = re.search(start_tag_pattern, item_text)
                        if match:
                            try:
                                attr_content = match.group(1) if match.group(1) else ''
                            except Exception:
                                attr_content = ''

                            attributes = extract_attributes(attr_content)

                            before_tag = item_text[: match.start()]
                            after_tag = item_text[match.end() :]

                            # Keep only text before the tag in the message
                            set_last_text(output, before_tag)

                            if not before_tag.strip():
                                # Remove empty message item
                                if output and output[-1].get('type') == 'message':
                                    output.pop()

                            # Append the new output item
                            if output_item_type == 'reasoning':
                                output.append(
                                    {
                                        'type': 'reasoning',
                                        'id': output_id('r'),
                                        'status': 'in_progress',
                                        'start_tag': start_tag,
                                        'end_tag': end_tag,
                                        'attributes': attributes,
                                        'content': [],
                                        'summary': None,
                                        'started_at': time.time(),
                                    }
                                )
                            elif output_item_type == 'open_webui:code_interpreter':
                                output.append(
                                    {
                                        'type': 'open_webui:code_interpreter',
                                        'id': output_id('ci'),
                                        'status': 'in_progress',
                                        'start_tag': start_tag,
                                        'end_tag': end_tag,
                                        'attributes': attributes,
                                        'lang': attributes.get('lang', 'python'),
                                        'code': '',
                                        'output': None,
                                        'started_at': time.time(),
                                    }
                                )
                            else:
                                # solution or other text-producing tag
                                output.append(
                                    {
                                        'type': 'message',
                                        'id': output_id('msg'),
                                        'status': 'in_progress',
                                        'role': 'assistant',
                                        'content': [{'type': 'output_text', 'text': ''}],
                                        '_tag_type': content_type,
                                        'start_tag': start_tag,
                                        'end_tag': end_tag,
                                        'attributes': attributes,
                                        'started_at': time.time(),
                                    }
                                )

                            if after_tag:
                                # Set the after_tag content on the new item
                                if output_item_type == 'reasoning':
                                    output[-1]['content'] = [{'type': 'output_text', 'text': after_tag}]
                                elif output_item_type == 'open_webui:code_interpreter':
                                    output[-1]['code'] = after_tag
                                else:
                                    set_last_text(output, after_tag)

                                _, recursive_end = tag_output_handler(content_type, tags, output)
                                if recursive_end:
                                    end_flag = True

                            break

                elif (
                    (last_type == 'reasoning' and content_type == 'reasoning')
                    or (last_type == 'open_webui:code_interpreter' and content_type == 'code_interpreter')
                    or (last_type == 'message' and output[-1].get('_tag_type') == content_type)
                ):
                    item = output[-1]
                    start_tag = item.get('start_tag', '')
                    end_tag = item.get('end_tag', '')

                    end_tag_pattern = rf'{re.escape(end_tag)}'

                    # Get the block content from the item itself
                    if last_type == 'reasoning':
                        parts = item.get('content', [])
                        block_content = ''
                        if parts and parts[-1].get('type') == 'output_text':
                            block_content = parts[-1].get('text', '')
                    elif last_type == 'open_webui:code_interpreter':
                        block_content = item.get('code', '')
                    else:
                        block_content = get_last_text(output)

                    if re.search(end_tag_pattern, block_content):
                        end_flag = True

                        # Strip start and end tags from content
                        start_tag_pattern = rf'{re.escape(start_tag)}'
                        if start_tag.startswith('<') and start_tag.endswith('>'):
                            start_tag_pattern = rf'<{re.escape(start_tag[1:-1])}(\s.*?)?>'
                        block_content = re.sub(start_tag_pattern, '', block_content).strip()

                        end_tag_regex = re.compile(end_tag_pattern, re.DOTALL)
                        split_content = end_tag_regex.split(block_content, maxsplit=1)

                        block_content = split_content[0].strip() if split_content else ''
                        leftover_content = split_content[1].strip() if len(split_content) > 1 else ''

                        if block_content:
                            # Update the item with final content
                            if last_type == 'reasoning':
                                item['content'] = [{'type': 'output_text', 'text': block_content}]
                                item['ended_at'] = time.time()
                                item['duration'] = int(item['ended_at'] - item['started_at'])
                                item['status'] = 'completed'
                            elif last_type == 'open_webui:code_interpreter':
                                item['code'] = block_content
                                item['ended_at'] = time.time()
                                item['duration'] = int(item['ended_at'] - item['started_at'])
                            else:
                                set_last_text(output, block_content)
                                item['ended_at'] = time.time()

                            # Reset by appending a new message item for leftover
                            output.append(
                                {
                                    'type': 'message',
                                    'id': output_id('msg'),
                                    'status': 'in_progress',
                                    'role': 'assistant',
                                    'content': [
                                        {
                                            'type': 'output_text',
                                            'text': leftover_content,
                                        }
                                    ],
                                }
                            )
                        else:
                            # Remove the block if content is empty
                            output.pop()
                            output.append(
                                {
                                    'type': 'message',
                                    'id': output_id('msg'),
                                    'status': 'in_progress',
                                    'role': 'assistant',
                                    'content': [
                                        {
                                            'type': 'output_text',
                                            'text': leftover_content,
                                        }
                                    ],
                                }
                            )

                return output, end_flag

            message = await Chats.get_message_by_id_and_message_id(metadata['chat_id'], metadata['message_id'])

            tool_calls = []

            last_assistant_message = None
            try:
                if form_data['messages'][-1]['role'] == 'assistant':
                    last_assistant_message = get_last_assistant_message(form_data['messages'])
            except Exception as e:
                pass

            content = (
                message.get('content', '') if message else last_assistant_message if last_assistant_message else ''
            )

            # Initialize output: use existing from message if continuing, else create new
            existing_output = message.get('output') if message else None
            if existing_output:
                output = existing_output
            elif metadata.get('kahle_prerouted_rag_tool_output'):
                output = copy.deepcopy(metadata['kahle_prerouted_rag_tool_output'])
            else:
                # Only create an initial message item if there is content to initialize with
                if content:
                    output = [
                        {
                            'type': 'message',
                            'id': output_id('msg'),
                            'status': 'in_progress',
                            'role': 'assistant',
                            'content': [{'type': 'output_text', 'text': content}],
                        }
                    ]
                else:
                    output = []

            usage = None
            prior_output = []
            last_response_id = None

            initial_user_message = get_last_user_message(form_data.get('messages', []) or [])
            initial_tools = metadata.get('tools', {}) or {}
            suppress_initial_rag_response = _should_suppress_initial_rag_response(
                rag_tool_available='rag_chat' in initial_tools,
                internal_rag_required=(
                    not metadata.get('kahle_mailer_drafting_followup')
                    and (
                        _looks_like_internal_rag_request(initial_user_message or '')
                        or bool(metadata.get('kahle_internal_rag_prerouted'))
                    )
                ),
                prerouted=bool(metadata.get('kahle_internal_rag_prerouted')),
            )

            def full_output():
                combined = prior_output + output if prior_output else output
                return _stream_safe_output(
                    combined,
                    suppress_message_text=suppress_initial_rag_response,
                )

            reasoning_tags_param = metadata.get('params', {}).get('reasoning_tags')
            DETECT_REASONING_TAGS = reasoning_tags_param is not False

            # Mirror the five gates from utils/tools.py get_builtin_tools so the
            # legacy XML-tag path enforces the same authz as native FC.
            features = metadata.get('features', {}) or {}
            model_capabilities = model.get('info', {}).get('meta', {}).get('capabilities') or {}
            builtin_tools_meta = model.get('info', {}).get('meta', {}).get('builtinTools', {})
            DETECT_CODE_INTERPRETER = (
                bool(features.get('code_interpreter'))
                and builtin_tools_meta.get('code_interpreter', True)
                and await Config.get('code_interpreter.enable')
                and model_capabilities.get('code_interpreter', True)
                and (
                    getattr(user, 'role', None) == 'admin'
                    or await has_permission(
                        getattr(user, 'id', ''),
                        'features.code_interpreter',
                        await Config.get('user.permissions'),
                    )
                )
            )

            reasoning_tags = []
            if DETECT_REASONING_TAGS:
                if isinstance(reasoning_tags_param, list) and len(reasoning_tags_param) == 2:
                    reasoning_tags = [(reasoning_tags_param[0], reasoning_tags_param[1])]
                else:
                    reasoning_tags = DEFAULT_REASONING_TAGS

            try:
                for event in events:
                    await event_emitter(
                        {
                            'type': 'chat:completion',
                            'data': event,
                        }
                    )

                    # Save message in the database
                    await Chats.upsert_message_to_chat_by_id_and_message_id(
                        metadata['chat_id'],
                        metadata['message_id'],
                        {
                            **event,
                        },
                    )

                async def stream_body_handler(response, form_data):
                    nonlocal content
                    nonlocal usage
                    nonlocal output
                    nonlocal prior_output
                    nonlocal last_response_id

                    if direct_final_content:
                        if hasattr(response.body_iterator, 'aclose'):
                            try:
                                await response.body_iterator.aclose()
                            except Exception:
                                pass
                        content = direct_final_content
                        prior_output = []
                        output = [
                            {
                                'type': 'message',
                                'id': output_id('msg'),
                                'status': 'completed',
                                'role': 'assistant',
                                'content': [{'type': 'output_text', 'text': direct_final_content}],
                            }
                        ]
                        return

                    response_tool_calls = []

                    delta_count = 0
                    delta_chunk_size = max(
                        CHAT_RESPONSE_STREAM_DELTA_CHUNK_SIZE,
                        int(metadata.get('params', {}).get('stream_delta_chunk_size') or 1),
                    )
                    last_delta_data = None
                    last_delta_type = None

                    async def flush_pending_delta_data(threshold: int = 0):
                        nonlocal delta_count
                        nonlocal last_delta_data
                        nonlocal last_delta_type

                        if delta_count >= threshold and last_delta_data:
                            await event_emitter(
                                {
                                    'type': 'chat:completion',
                                    'data': last_delta_data,
                                }
                            )
                            delta_count = 0
                            last_delta_data = None
                            last_delta_type = None

                    async def queue_pending_delta_data(delta_data: dict, delta_type: str):
                        nonlocal delta_count
                        nonlocal last_delta_data
                        nonlocal last_delta_type

                        if last_delta_type and last_delta_type != delta_type:
                            await flush_pending_delta_data()

                        delta_count += 1
                        last_delta_data = delta_data
                        last_delta_type = delta_type

                        if delta_count >= delta_chunk_size:
                            await flush_pending_delta_data(delta_chunk_size)

                    async for line in response.body_iterator:
                        line = line.decode('utf-8', 'replace') if isinstance(line, bytes) else line
                        data = line

                        # Skip empty lines
                        if not data.strip():
                            continue

                        # "data:" is the prefix for each event
                        if not data.startswith('data:'):
                            # Some upstreams return plain JSON error lines in a streaming response
                            # (without SSE `data:` prefix). Try to normalize these into standard
                            # error events so frontend and DB paths still receive them.
                            try:
                                raw_obj = json.loads(data)
                                raw_error = raw_obj.get('error') if isinstance(raw_obj, dict) else None
                                if raw_error:
                                    try:
                                        Chats.upsert_message_to_chat_by_id_and_message_id(
                                            metadata['chat_id'],
                                            metadata['message_id'],
                                            {
                                                'error': {'content': raw_error},
                                            },
                                        )
                                    except Exception:
                                        pass
                                    await event_emitter({'type': 'chat:completion', 'data': {'error': raw_error}})
                            except Exception:
                                pass
                            continue

                        # Remove the prefix
                        data = data[len('data:') :].strip()

                        try:
                            data = json.loads(data)

                            data, _ = await process_filter_functions(
                                request=request,
                                filter_context=filter_context,
                                filter_functions=filter_functions,
                                filter_type='stream',
                                form_data=data,
                                extra_params={'__body__': form_data, **extra_params},
                            )

                            if data:
                                if 'event' in data and not getattr(request.state, 'direct', False):
                                    await event_emitter(data.get('event', {}))

                                if 'selected_model_id' in data:
                                    model_id = data['selected_model_id']
                                    await Chats.upsert_message_to_chat_by_id_and_message_id(
                                        metadata['chat_id'],
                                        metadata['message_id'],
                                        {
                                            'selectedModelId': model_id,
                                        },
                                    )
                                    await event_emitter(
                                        {
                                            'type': 'chat:completion',
                                            'data': data,
                                        }
                                    )
                                # Check for Responses API events (type field starts with "response.")
                                elif data.get('type', '').startswith('response.'):
                                    response_event_type = data.get('type', '')
                                    response_event_is_delta = response_event_type.endswith('.delta')
                                    output, response_metadata = handle_responses_streaming_event(data, output)

                                    if not response_event_is_delta:
                                        await flush_pending_delta_data()

                                    # Emit citation sources from finalized output items
                                    # (mirrors Chat Completions annotation handling at delta level)
                                    if response_event_type == 'response.output_item.done':
                                        item = data.get('item', {})
                                        if item.get('type') == 'message':
                                            for part in item.get('content', []):
                                                for annotation in part.get('annotations', []):
                                                    if annotation.get('type') == 'url_citation':
                                                        # Handle both flat (Responses API) and nested (Chat Completions) formats
                                                        url_citation = annotation.get('url_citation', annotation)

                                                        url = url_citation.get('url', '')
                                                        title = url_citation.get('title', url)

                                                        if url:
                                                            await event_emitter(
                                                                {
                                                                    'type': 'source',
                                                                    'data': {
                                                                        'source': {
                                                                            'name': title,
                                                                            'url': url,
                                                                        },
                                                                        'document': [title],
                                                                        'metadata': [
                                                                            {
                                                                                'source': url,
                                                                                'name': title,
                                                                            }
                                                                        ],
                                                                    },
                                                                }
                                                            )

                                    processed_data = {
                                        'output': full_output(),
                                    }

                                    # print(data)
                                    # print(processed_data)

                                    # Merge any metadata (usage, etc.)
                                    # Strip 'done' — response.completed emits
                                    # it but we may still need to execute tool
                                    # calls. The outer middleware manages the
                                    # actual completion signal.
                                    if response_metadata:
                                        if ENABLE_RESPONSES_API_STATEFUL:
                                            response_id = response_metadata.pop('response_id', None)
                                            if response_id:
                                                last_response_id = response_id

                                        # Normalize and capture usage for DB persistence
                                        if response_metadata.get('usage'):
                                            usage = merge_usage(usage, response_metadata['usage'])
                                            response_metadata['usage'] = usage

                                        processed_data.update(response_metadata)
                                        processed_data.pop('done', None)

                                    if response_event_is_delta:
                                        response_delta_type = response_event_type.split('.')[1]
                                        await queue_pending_delta_data(
                                            processed_data,
                                            'tool_call'
                                            if response_delta_type == 'function_call_arguments'
                                            else 'content',
                                        )
                                    else:
                                        await event_emitter(
                                            {
                                                'type': 'chat:completion',
                                                'data': processed_data,
                                            }
                                        )
                                    continue
                                else:
                                    choices = data.get('choices', [])

                                    # Normalize usage data to standard format
                                    raw_usage = data.get('usage', {}) or {}
                                    raw_usage.update(data.get('timings', {}))  # llama.cpp
                                    if raw_usage:
                                        usage = merge_usage(usage, raw_usage)
                                        await event_emitter(
                                            {
                                                'type': 'chat:completion',
                                                'data': {
                                                    'usage': usage,
                                                },
                                            }
                                        )

                                    if not choices:
                                        error = data.get('error', {})
                                        if error:
                                            log.error('Provider returned error (streaming): %s', error)
                                            try:
                                                await Chats.upsert_message_to_chat_by_id_and_message_id(
                                                    metadata['chat_id'],
                                                    metadata['message_id'],
                                                    {
                                                        'error': {'content': error},
                                                    },
                                                )
                                            except Exception:
                                                pass
                                            await event_emitter(
                                                {
                                                    'type': 'chat:completion',
                                                    'data': {
                                                        'error': error,
                                                    },
                                                }
                                            )
                                        continue

                                    delta = choices[0].get('delta', {})
                                    delta_type = 'content'

                                    # Handle delta annotations
                                    annotations = delta.get('annotations')
                                    if annotations:
                                        for annotation in annotations:
                                            if (
                                                annotation.get('type') == 'url_citation'
                                                and 'url_citation' in annotation
                                            ):
                                                url_citation = annotation['url_citation']

                                                url = url_citation.get('url', '')
                                                title = url_citation.get('title', url)

                                                await event_emitter(
                                                    {
                                                        'type': 'source',
                                                        'data': {
                                                            'source': {
                                                                'name': title,
                                                                'url': url,
                                                            },
                                                            'document': [title],
                                                            'metadata': [
                                                                {
                                                                    'source': url,
                                                                    'name': title,
                                                                }
                                                            ],
                                                        },
                                                    }
                                                )

                                    delta_tool_calls = delta.get('tool_calls', None)
                                    if delta_tool_calls:
                                        for delta_tool_call in delta_tool_calls:
                                            tool_call_index = delta_tool_call.get('index')

                                            if tool_call_index is not None:
                                                # Check if the tool call already exists
                                                current_response_tool_call = None
                                                for response_tool_call in response_tool_calls:
                                                    if response_tool_call.get('index') == tool_call_index:
                                                        current_response_tool_call = response_tool_call
                                                        break

                                                if current_response_tool_call is None:
                                                    # Add the new tool call
                                                    delta_tool_call.setdefault('function', {})
                                                    delta_tool_call['function'].setdefault('name', '')
                                                    delta_tool_call['function'].setdefault('arguments', '')
                                                    response_tool_calls.append(delta_tool_call)
                                                else:
                                                    # Update the existing tool call
                                                    delta_name = delta_tool_call.get('function', {}).get('name')
                                                    delta_arguments = delta_tool_call.get('function', {}).get(
                                                        'arguments'
                                                    )

                                                    if delta_name:
                                                        current_response_tool_call['function']['name'] = delta_name

                                                    if delta_arguments:
                                                        current_response_tool_call['function']['arguments'] += (
                                                            delta_arguments
                                                        )

                                        # Emit pending tool calls in real-time
                                        if response_tool_calls:
                                            # Build pending function_call output items for display
                                            pending_fc_items = []
                                            for tc in response_tool_calls:
                                                call_id = tc.get('id', '')
                                                func = tc.get('function', {})
                                                pending_fc_items.append(
                                                    {
                                                        'type': 'function_call',
                                                        'id': call_id or output_id('fc'),
                                                        'call_id': call_id,
                                                        'name': func.get('name', ''),
                                                        'arguments': func.get('arguments', '{}'),
                                                        'status': 'in_progress',
                                                    }
                                                )

                                            data = {
                                                'output': full_output() + pending_fc_items,
                                            }
                                            delta_type = 'tool_call'

                                    image_urls = await get_image_urls(delta.get('images', []), request, metadata, user)
                                    if image_urls:
                                        image_file_list = [{'type': 'image', 'url': url} for url in image_urls]
                                        message_files = await Chats.add_message_files_by_id_and_message_id(
                                            metadata['chat_id'],
                                            metadata['message_id'],
                                            image_file_list,
                                        )
                                        if message_files is None:
                                            message_files = image_file_list

                                        await event_emitter(
                                            {
                                                'type': 'files',
                                                'data': {'files': message_files},
                                            }
                                        )

                                    value = delta.get('content')

                                    reasoning_content = (
                                        delta.get('reasoning_content')
                                        or delta.get('reasoning')
                                        or delta.get('thinking')
                                    )
                                    reasoning_details = delta.get('reasoning_details')
                                    if reasoning_content or reasoning_details:
                                        reasoning_item = (
                                            next(
                                                (item for item in reversed(output) if item.get('type') == 'reasoning'),
                                                None,
                                            )
                                            if reasoning_details and not reasoning_content
                                            else None
                                        )

                                        if reasoning_item is None:
                                            if not output or output[-1].get('type') != 'reasoning':
                                                reasoning_item = {
                                                    'type': 'reasoning',
                                                    'id': output_id('r'),
                                                    'status': 'in_progress',
                                                    'start_tag': '<think>',
                                                    'end_tag': '</think>',
                                                    'attributes': {'type': 'reasoning_content'},
                                                    'content': [],
                                                    'summary': None,
                                                    'started_at': time.time(),
                                                }
                                                output.append(reasoning_item)
                                            else:
                                                reasoning_item = output[-1]

                                        if reasoning_content:
                                            # Append to reasoning content
                                            parts = reasoning_item.get('content', [])
                                            if parts and parts[-1].get('type') == 'output_text':
                                                parts[-1]['text'] += reasoning_content
                                            else:
                                                reasoning_item['content'] = [
                                                    {
                                                        'type': 'output_text',
                                                        'text': reasoning_content,
                                                    }
                                                ]

                                            data = {
                                                'output': full_output(),
                                            }
                                            delta_type = 'content'

                                        if reasoning_details:
                                            merge_streamed_reasoning_details(
                                                reasoning_item.setdefault('reasoning_details', []),
                                                reasoning_details,
                                            )
                                            data = {
                                                'output': full_output(),
                                            }
                                            delta_type = 'content'

                                    if value:
                                        if (
                                            output
                                            and output[-1].get('type') == 'reasoning'
                                            and output[-1].get('attributes', {}).get('type') == 'reasoning_content'
                                        ):
                                            reasoning_item = output[-1]
                                            reasoning_item['ended_at'] = time.time()
                                            reasoning_item['duration'] = int(
                                                reasoning_item['ended_at'] - reasoning_item['started_at']
                                            )
                                            reasoning_item['status'] = 'completed'

                                            output.append(
                                                {
                                                    'type': 'message',
                                                    'id': output_id('msg'),
                                                    'status': 'in_progress',
                                                    'role': 'assistant',
                                                    'content': [
                                                        {
                                                            'type': 'output_text',
                                                            'text': '',
                                                        }
                                                    ],
                                                }
                                            )

                                        if ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION:
                                            value = await convert_markdown_base64_images(
                                                request,
                                                value,
                                                {
                                                    'chat_id': metadata.get('chat_id', None),
                                                    'message_id': metadata.get('message_id', None),
                                                },
                                                user,
                                            )

                                        content = f'{content}{value}'

                                        # Check if we're inside a tag-based block
                                        # (reasoning, code_interpreter, or solution).
                                        # If so, append to the existing in-progress
                                        # item instead of creating a new message —
                                        # otherwise tag_output_handler re-detects the
                                        # start tag on every chunk and fragments the
                                        # output.
                                        last_item = output[-1] if output else None
                                        last_item_type = last_item.get('type', '') if last_item else ''
                                        inside_tag_block = (
                                            last_item is not None
                                            and last_item.get('status') == 'in_progress'
                                            and last_item.get('attributes', {}).get('type') != 'reasoning_content'
                                            and (
                                                last_item_type == 'reasoning'
                                                or last_item_type == 'open_webui:code_interpreter'
                                                or (
                                                    last_item_type == 'message'
                                                    and last_item.get('_tag_type') is not None
                                                )
                                            )
                                        )

                                        if inside_tag_block:
                                            # Append to the existing tag-based item
                                            if last_item_type == 'open_webui:code_interpreter':
                                                last_item['code'] = last_item.get('code', '') + value
                                            elif last_item_type == 'reasoning':
                                                parts = last_item.get('content', [])
                                                if parts and parts[-1].get('type') == 'output_text':
                                                    parts[-1]['text'] += value
                                                else:
                                                    last_item['content'] = [
                                                        {
                                                            'type': 'output_text',
                                                            'text': value,
                                                        }
                                                    ]
                                            else:
                                                # solution or other _tag_type message
                                                msg_parts = last_item.get('content', [])
                                                if msg_parts and msg_parts[-1].get('type') == 'output_text':
                                                    msg_parts[-1]['text'] += value
                                                else:
                                                    last_item['content'] = [
                                                        {
                                                            'type': 'output_text',
                                                            'text': value,
                                                        }
                                                    ]
                                        else:
                                            if not output or output[-1].get('type') != 'message':
                                                output.append(
                                                    {
                                                        'type': 'message',
                                                        'id': output_id('msg'),
                                                        'status': 'in_progress',
                                                        'role': 'assistant',
                                                        'content': [
                                                            {
                                                                'type': 'output_text',
                                                                'text': '',
                                                            }
                                                        ],
                                                    }
                                                )

                                            # Append value to last message item's text
                                            msg_parts = output[-1].get('content', [])
                                            if msg_parts and msg_parts[-1].get('type') == 'output_text':
                                                msg_parts[-1]['text'] += value
                                            else:
                                                output[-1]['content'] = [
                                                    {
                                                        'type': 'output_text',
                                                        'text': value,
                                                    }
                                                ]

                                        if DETECT_REASONING_TAGS:
                                            output, _ = tag_output_handler(
                                                'reasoning',
                                                reasoning_tags,
                                                output,
                                            )

                                            output, _ = tag_output_handler(
                                                'solution',
                                                DEFAULT_SOLUTION_TAGS,
                                                output,
                                            )

                                        if DETECT_CODE_INTERPRETER:
                                            output, end = tag_output_handler(
                                                'code_interpreter',
                                                DEFAULT_CODE_INTERPRETER_TAGS,
                                                output,
                                            )

                                            if end:
                                                break

                                        if ENABLE_REALTIME_CHAT_SAVE and not metadata.get('chat_id', '').startswith(
                                            'channel:'
                                        ):
                                            # Save message in the database
                                            await Chats.upsert_message_to_chat_by_id_and_message_id(
                                                metadata['chat_id'],
                                                metadata['message_id'],
                                                {
                                                    'output': full_output(),
                                                },
                                            )
                                            data = {
                                                'output': full_output(),
                                            }
                                            delta_type = 'content'
                                        else:
                                            data = {
                                                'output': full_output(),
                                            }
                                            delta_type = 'content'

                                if delta:
                                    await queue_pending_delta_data(data, delta_type)
                                else:
                                    await event_emitter(
                                        {
                                            'type': 'chat:completion',
                                            'data': data,
                                        }
                                    )
                        except (asyncio.CancelledError, KeyboardInterrupt):
                            raise
                        except Exception as e:
                            done = 'data: [DONE]' in line
                            if done:
                                pass
                            else:
                                log.debug(f'Error: {e}')
                                continue
                    await flush_pending_delta_data()

                    if output:
                        # Clean up the last message item
                        if output[-1].get('type') == 'message':
                            parts = output[-1].get('content', [])
                            if parts and parts[-1].get('type') == 'output_text':
                                parts[-1]['text'] = parts[-1]['text'].strip()

                                if not parts[-1]['text']:
                                    output.pop()

                                    if not output:
                                        output.append(
                                            {
                                                'type': 'message',
                                                'id': output_id('msg'),
                                                'status': 'in_progress',
                                                'role': 'assistant',
                                                'content': [{'type': 'output_text', 'text': ''}],
                                            }
                                        )

                        if output[-1].get('type') == 'reasoning':
                            reasoning_item = output[-1]
                            if reasoning_item.get('ended_at') is None:
                                reasoning_item['ended_at'] = time.time()
                                reasoning_item['duration'] = int(
                                    reasoning_item['ended_at'] - reasoning_item['started_at']
                                )
                                reasoning_item['status'] = 'completed'

                    if response_tool_calls:
                        tool_calls.append(_split_tool_calls(response_tool_calls))

                    # Responses API path: extract function_call items from output
                    if not response_tool_calls and output:
                        # Collect call_ids that already have results,
                        # including those from prior_output so we don't
                        # re-process tool calls from a previous turn.
                        handled_call_ids = {
                            item.get('call_id')
                            for item in (prior_output + output)
                            if item.get('type') == 'function_call_output'
                        }
                        responses_api_tool_calls = []
                        for item in output:
                            if item.get('type') == 'function_call' and item.get('call_id') not in handled_call_ids:
                                arguments = item.get('arguments', '{}')
                                responses_api_tool_calls.append(
                                    {
                                        'id': item.get('call_id', ''),
                                        'index': len(responses_api_tool_calls),
                                        'function': {
                                            'name': item.get('name', ''),
                                            'arguments': (
                                                arguments if isinstance(arguments, str) else json.dumps(arguments)
                                            ),
                                        },
                                    }
                                )
                        if responses_api_tool_calls:
                            tool_calls.append(_split_tool_calls(responses_api_tool_calls))

                initial_answer_stream_timed_out = False
                try:
                    if metadata.get('kahle_knowledge_harness_active'):
                        initial_answer_stream_timed_out = await _await_kahle_answer_stream(
                            stream_body_handler(response, form_data),
                            timeout_seconds=_knowledge_harness_answer_timeout_seconds(),
                        )
                    else:
                        await stream_body_handler(response, form_data)
                finally:
                    if response.background and not initial_answer_stream_timed_out:
                        await response.background()

                if initial_answer_stream_timed_out:
                    metadata['kahle_answer_stream_timed_out'] = True
                    if hasattr(response.body_iterator, 'aclose'):
                        try:
                            await response.body_iterator.aclose()
                        except Exception:
                            pass
                    content = ''
                    prior_output = []
                    output = [{
                        'type': 'message',
                        'id': output_id('msg'),
                        'status': 'in_progress',
                        'role': 'assistant',
                        'content': [{
                            'type': 'output_text',
                            'text': str(
                                metadata.get('kahle_answer_validation_fallback')
                                or 'Die Antwort konnte nicht rechtzeitig abgeschlossen werden.'
                            ),
                        }],
                    }]

                # The unsupported first model response has now been fully
                # consumed without exposing its message text. Tool-call events
                # and the answer generated from the RAG result may be shown.
                suppress_initial_rag_response = False

                tool_call_retries = 0
                tool_call_sources = []  # Track citation sources from tool results
                all_tool_call_sources = []  # Accumulated sources across all iterations
                canonical_rag_sources = list(
                    metadata.get('kahle_canonical_rag_sources') or []
                )  # Trusted original links from KAHLE_RAG_RESULT
                canonical_rag_feedback_link = str(
                    metadata.get('kahle_canonical_rag_feedback_link') or ''
                )  # Trusted feedback target from KAHLE_RAG_RESULT
                user_message = get_last_user_message(form_data['messages'])
                tools = metadata.get('tools', {})

                native_rag_fallback = (
                    []
                    if (
                        metadata.get('kahle_internal_rag_prerouted')
                        or metadata.get('kahle_mailer_drafting_followup')
                    )
                    else _build_native_rag_fallback(tools, user_message or '', tool_calls, output)
                )
                if native_rag_fallback:
                    # Discard the model's unsupported direct answer. The next
                    # response is generated from the permission-filtered tool
                    # result and becomes the only visible assistant answer.
                    output = [item for item in output if item.get('type') != 'message']
                    content = ''
                    tool_calls.extend(native_rag_fallback)

                # Check if citations are enabled for this model
                citations_enabled = (model.get('info', {}).get('meta', {}).get('capabilities') or {}).get(
                    'citations', True
                )

                # Use the pre-RAG system content captured before the
                # initial file-source injection in process_chat_payload.
                # This ensures restore truly undoes the RAG template.
                original_system_content = metadata.get('system_prompt')
                if original_system_content is None:
                    original_system_message = get_system_message(form_data['messages'])
                    original_system_content = (
                        get_content_from_message(original_system_message) if original_system_message else None
                    )

                while len(tool_calls) > 0 and tool_call_retries < CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS:
                    tool_call_retries += 1

                    response_tool_calls = tool_calls.pop(0)

                    # Append function_call items for each tool call
                    # (Responses API already has them from streaming, so skip duplicates)
                    existing_call_ids = {item.get('call_id') for item in output if item.get('type') == 'function_call'}
                    for tc in response_tool_calls:
                        call_id = tc.get('id', '')
                        if call_id not in existing_call_ids:
                            func = tc.get('function', {})
                            output.append(
                                {
                                    'type': 'function_call',
                                    'id': call_id or output_id('fc'),
                                    'call_id': call_id,
                                    'name': func.get('name', ''),
                                    'arguments': func.get('arguments', '{}'),
                                    'status': 'in_progress',
                                }
                            )

                    await event_emitter(
                        {
                            'type': 'chat:completion',
                            'data': {
                                'output': full_output(),
                            },
                        }
                    )

                    results = []
                    final_notice = ''

                    for tool_call in response_tool_calls:
                        tool_call_id = tool_call.get('id', '')
                        tool_function_name = tool_call.get('function', {}).get('name', '')
                        tool_args = tool_call.get('function', {}).get('arguments', '{}')

                        tool_function_params = {}
                        if tool_args and tool_args.strip():
                            try:
                                # json.loads cannot be used because some models do not produce valid JSON
                                tool_function_params = ast.literal_eval(tool_args)
                            except Exception as e:
                                log.debug(e)
                                # Fallback to JSON parsing
                                try:
                                    tool_function_params = json.loads(tool_args)
                                except Exception as e:
                                    log.error(f'Error parsing tool call arguments: {tool_args}')
                                    results.append(
                                        {
                                            'tool_call_id': tool_call_id,
                                            'content': f'Error: Tool call arguments could not be parsed. The model generated malformed or incomplete JSON for `{tool_function_name}`. Please try again.',
                                        }
                                    )
                                    continue

                        # Ensure arguments are valid JSON for downstream LLM integrations
                        log.debug(f'Parsed args from {tool_args} to {tool_function_params}')
                        tool_call.setdefault('function', {})['arguments'] = json.dumps(tool_function_params)

                        tool_result = None
                        tool = None
                        tool_type = None
                        direct_tool = False

                        if tool_function_name in tools:
                            tool = tools[tool_function_name]
                            spec = tool.get('spec', {})

                            tool_type = tool.get('type', '')
                            direct_tool = tool.get('direct', False)

                            try:
                                allowed_params = spec.get('parameters', {}).get('properties', {}).keys()

                                tool_function_params = {
                                    k: v for k, v in tool_function_params.items() if k in allowed_params
                                }

                                document_comparison_block_reason = (
                                    _kahle_document_comparison_block_reason(
                                        tool_function_name, user_message or ''
                                    )
                                    or _kahle_uploaded_conversion_block_reason(
                                        tool_function_name, user_message or ''
                                    )
                                )
                                if document_comparison_block_reason:
                                    tool_result = document_comparison_block_reason
                                elif direct_tool:
                                    tool_result = await event_caller(
                                        {
                                            'type': 'execute:tool',
                                            'data': {
                                                'id': str(uuid4()),
                                                'name': tool_function_name,
                                                'params': tool_function_params,
                                                'server': tool.get('server', {}),
                                                'session_id': metadata.get('session_id', None),
                                            },
                                        }
                                    )

                                else:
                                    tool_function = await get_updated_tool_function(
                                        function=tool['callable'],
                                        extra_params={
                                            '__messages__': form_data.get('messages', []),
                                            '__files__': metadata.get('files', []),
                                        },
                                    )

                                    tool_result = await tool_function(**tool_function_params)

                            except Exception as e:
                                tool_result = str(e)

                        tool_result, tool_result_files, tool_result_embeds = await process_tool_result(
                            request,
                            tool_function_name,
                            tool_result,
                            tool_type,
                            direct_tool,
                            metadata,
                            user,
                        )
                        if tool_function_name == 'rag_chat':
                            canonical_rag_sources.extend(_extract_kahle_rag_sources(tool_result))
                            canonical_rag_feedback_link = (
                                _extract_kahle_rag_feedback_link(tool_result)
                                or canonical_rag_feedback_link
                            )
                        # Signed download URLs are opaque data. Never send a
                        # successful file result back through the model for a
                        # second, streamed response: even a one-character model
                        # rewrite invalidates the HMAC signature. Completing via
                        # final_notice also prevents any later stream delta from
                        # racing the canonical answer in the browser.
                        file_saved_payload = _extract_kahle_file_saved_payload(tool_result)
                        if file_saved_payload:
                            final_notice = _format_kahle_file_saved_content(file_saved_payload)
                            metadata['kahle_direct_final_content'] = final_notice
                            tool_result = json.dumps(file_saved_payload, ensure_ascii=False)
                        tool_final_notice = _extract_final_notice(tool_result)
                        if tool_final_notice:
                            final_notice = tool_final_notice
                            tool_result = tool_final_notice

                        await terminal_event_handler(
                            tool_function_name,
                            tool_function_params,
                            tool_result,
                            event_emitter,
                        )

                        # Extract citation sources from tool results
                        if (
                            citations_enabled
                            and tool_function_name
                            in [
                                'search_web',
                                'fetch_url',
                                'view_file',
                                'view_knowledge_file',
                                'query_knowledge_files',
                            ]
                            and tool_result
                        ):
                            try:
                                citation_sources = get_citation_source_from_tool_result(
                                    tool_name=tool_function_name,
                                    tool_params=tool_function_params,
                                    tool_result=tool_result,
                                    tool_id=tool.get('tool_id', '') if tool else '',
                                )
                                tool_call_sources.extend(citation_sources)
                            except Exception as e:
                                log.exception(f'Error extracting citation source: {e}')

                        results.append(
                            {
                                'tool_call_id': tool_call_id,
                                'content': str(tool_result) if tool_result else '',
                                **({'files': tool_result_files} if tool_result_files else {}),
                                **({'embeds': tool_result_embeds} if tool_result_embeds else {}),
                            }
                        )

                    # Update function_call statuses and append function_call_output items
                    for tc in response_tool_calls:
                        call_id = tc.get('id', '')
                        # Mark function_call as completed
                        for item in output:
                            if item.get('type') == 'function_call' and item.get('call_id') == call_id:
                                item['status'] = 'completed'
                                # Update arguments with parsed/sanitized version
                                item['arguments'] = tc.get('function', {}).get('arguments', '{}')
                                break

                    for result in results:
                        output_parts = [{'type': 'input_text', 'text': result.get('content', '')}]

                        # Separate image data URIs (for LLM via input_image) from
                        # other files (for frontend display via files attribute).
                        display_files = []
                        for file_item in result.get('files', []):
                            if file_item.get('type') == 'image' and file_item.get('url', '').startswith('data:'):
                                # LLM-only: add as input_image part, not frontend display output.
                                output_parts.append({'type': 'input_image', 'image_url': file_item['url']})
                            else:
                                # Frontend display (MCP images, audio, etc.)
                                display_files.append(file_item)

                        output.append(
                            {
                                'type': 'function_call_output',
                                'id': output_id('fco'),
                                'call_id': result.get('tool_call_id', ''),
                                'output': output_parts,
                                'status': 'completed',
                                **({'files': display_files} if display_files else {}),
                                **({'embeds': result.get('embeds')} if result.get('embeds') else {}),
                            }
                        )

                    # Append a new empty message item for the next response
                    output.append(
                        {
                            'type': 'message',
                            'id': output_id('msg'),
                            'status': 'in_progress',
                            'role': 'assistant',
                            'content': [{'type': 'output_text', 'text': ''}],
                        }
                    )

                    if final_notice:
                        output[-1]['status'] = 'completed'
                        output[-1]['content'] = [{'type': 'output_text', 'text': final_notice}]
                        await event_emitter(
                            {
                                'type': 'chat:completion',
                                'data': {
                                    'content': final_notice,
                                    'output': output,
                                },
                            }
                        )
                        tool_calls.clear()
                        break

                    # Emit citation sources to the frontend for display
                    if citations_enabled:
                        for source in tool_call_sources:
                            await event_emitter({'type': 'source', 'data': source})

                        # Apply tool source context to messages for the model.
                        # Restoring to pre-RAG original prevents duplicating
                        # the RAG template across file and tool sources.
                        all_tool_call_sources.extend(tool_call_sources)
                        if all_tool_call_sources and user_message:
                            # Restore pre-RAG message state before re-applying
                            # to prevent RAG template duplication.
                            original_user_message = metadata.get('user_prompt') or user_message
                            set_last_user_message_content(
                                original_user_message,
                                form_data['messages'],
                            )
                            if original_system_content is not None:
                                if get_system_message(form_data['messages']):
                                    replace_system_message_content(
                                        original_system_content,
                                        form_data['messages'],
                                    )
                                else:
                                    form_data['messages'] = add_or_update_system_message(
                                        original_system_content,
                                        form_data['messages'],
                                    )
                            else:
                                replace_system_message_content('', form_data['messages'])

                            # Build context: file sources with content,
                            # tool sources as citation markers only.
                            source_ids = {}
                            source_context = get_source_context(
                                metadata.get('sources', []), source_ids
                            ) + get_source_context(
                                all_tool_call_sources,
                                source_ids,
                                include_content=False,
                            )
                            source_context = source_context.strip()
                            if source_context:
                                rag_content = await rag_template(
                                    await Config.get('rag.template'),
                                    source_context,
                                    user_message,
                                )
                                if RAG_SYSTEM_CONTEXT:
                                    form_data['messages'] = add_or_update_system_message(
                                        rag_content,
                                        form_data['messages'],
                                        append=True,
                                    )
                                else:
                                    form_data['messages'] = add_or_update_user_message(
                                        rag_content,
                                        form_data['messages'],
                                        append=False,
                                    )
                        tool_call_sources.clear()

                    # Strip input_image parts (large base64 data URIs) from the
                    # output sent to the frontend — they're only for LLM consumption
                    # via convert_output_to_messages.
                    frontend_output = []
                    for item in output:
                        if item.get('type') == 'function_call_output':
                            parts = item.get('output', [])
                            if any(p.get('type') == 'input_image' for p in parts):
                                item = {**item, 'output': [p for p in parts if p.get('type') != 'input_image']}
                        frontend_output.append(item)

                    await event_emitter(
                        {
                            'type': 'chat:completion',
                            'data': {
                                'output': frontend_output,
                            },
                        }
                    )

                    try:
                        new_form_data = {
                            **form_data,
                            'model': model_id,
                            'stream': True,
                            'metadata': metadata,
                        }

                        if ENABLE_RESPONSES_API_STATEFUL and last_response_id:
                            system_message = get_system_message(form_data['messages'])
                            new_form_data['messages'] = (
                                [system_message] if system_message else []
                            ) + convert_output_to_messages(output, raw=True)
                            new_form_data['previous_response_id'] = last_response_id
                        else:
                            tool_messages = convert_output_to_messages(output, raw=True)

                            # Chat Completions providers don't support multimodal
                            # tool messages.  Extract images into a user message.
                            image_urls = []
                            for message in tool_messages:
                                if message.get('role') == 'tool' and isinstance(message.get('content'), list):
                                    text_parts = []
                                    for part in message['content']:
                                        if part.get('type') == 'input_text':
                                            text_parts.append(part.get('text', ''))
                                        elif part.get('type') == 'input_image':
                                            image_urls.append(part.get('image_url', ''))
                                    message['content'] = ''.join(text_parts)

                            new_form_data['messages'] = [
                                *form_data['messages'],
                                *tool_messages,
                            ]

                            if image_urls:
                                new_form_data['messages'].append(
                                    {
                                        'role': 'user',
                                        'content': [
                                            {
                                                'type': 'text',
                                                'text': 'Here are the images from the tool results above. Please analyze them.',
                                            },
                                            *[{'type': 'image_url', 'image_url': {'url': url}} for url in image_urls],
                                        ],
                                    }
                                )

                        res = await generate_chat_completion(
                            request,
                            new_form_data,
                            user,
                            bypass_system_prompt=True,
                        )

                        if isinstance(res, StreamingResponse):
                            # Save accumulated output and start fresh.
                            # Responses API output_index values are relative
                            # to the current response — a clean output list
                            # keeps indices aligned. The display prefix
                            # ensures the UI shows tool history during
                            # streaming.
                            prior_output = list(output)
                            # Trim the trailing empty placeholder message
                            # so it doesn't persist as a ghost item once
                            # the new stream produces real content.
                            if (
                                prior_output
                                and prior_output[-1].get('type') == 'message'
                                and prior_output[-1].get('status') == 'in_progress'
                            ):
                                msg_parts = prior_output[-1].get('content', [])
                                if not msg_parts or (len(msg_parts) == 1 and not msg_parts[0].get('text', '').strip()):
                                    prior_output.pop()
                            output = []
                            await stream_body_handler(res, new_form_data)
                            output[:0] = prior_output
                            prior_output = []
                        else:
                            break
                    except Exception as e:
                        log.debug(e)
                        break

                if DETECT_CODE_INTERPRETER:
                    MAX_RETRIES = 5
                    retries = 0

                    while output and output[-1].get('type') == 'open_webui:code_interpreter' and retries < MAX_RETRIES:
                        await event_emitter(
                            {
                                'type': 'chat:completion',
                                'data': {
                                    'output': output,
                                },
                            }
                        )

                        retries += 1
                        log.debug(f'Attempt count: {retries}')

                        ci_item = output[-1]
                        ci_output = ''
                        try:
                            if ci_item.get('attributes', {}).get('type') == 'code':
                                code = ci_item.get('code', '')
                                # Sanitize code (strips ANSI codes and markdown fences)
                                code = sanitize_code(code)

                                if CODE_INTERPRETER_BLOCKED_MODULES:
                                    blocking_code = textwrap.dedent(
                                        f"""
                                        import builtins
    
                                        BLOCKED_MODULES = {CODE_INTERPRETER_BLOCKED_MODULES}
    
                                        _real_import = builtins.__import__
                                        async def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
                                            if name.split('.')[0] in BLOCKED_MODULES:
                                                importer_name = globals.get('__name__') if globals else None
                                                if importer_name == '__main__':
                                                    raise ImportError(
                                                        f"Direct import of module {{name}} is restricted."
                                                    )
                                            return _real_import(name, globals, locals, fromlist, level)
    
                                        builtins.__import__ = restricted_import
                                    """)
                                    code = blocking_code + '\n' + code

                                if await Config.get('code_interpreter.engine') == 'pyodide':
                                    ci_output = await event_caller(
                                        {
                                            'type': 'execute:python',
                                            'data': {
                                                'id': str(uuid4()),
                                                'code': code,
                                                'session_id': metadata.get('session_id', None),
                                                'files': metadata.get('files', []),
                                            },
                                        }
                                    )
                                elif await Config.get('code_interpreter.engine') == 'jupyter':
                                    ci_output = await execute_code_jupyter(
                                        await Config.get('code_interpreter.jupyter.url'),
                                        code,
                                        (
                                            await Config.get('code_interpreter.jupyter.auth_token')
                                            if await Config.get('code_interpreter.jupyter.auth') == 'token'
                                            else None
                                        ),
                                        (
                                            await Config.get('code_interpreter.jupyter.auth_password')
                                            if await Config.get('code_interpreter.jupyter.auth') == 'password'
                                            else None
                                        ),
                                        await Config.get('code_interpreter.jupyter.timeout'),
                                    )
                                else:
                                    ci_output = {'stdout': 'Code interpreter engine not configured.'}

                                log.debug(f'Code interpreter output: {ci_output}')

                                if isinstance(ci_output, dict):
                                    stdout = ci_output.get('stdout', '')

                                    if isinstance(stdout, str):
                                        stdoutLines = stdout.split('\n')
                                        for idx, line in enumerate(stdoutLines):
                                            if re.match(r'data:image/\w+;base64', line):
                                                image_url = await get_image_url_from_base64(
                                                    request,
                                                    line,
                                                    metadata,
                                                    user,
                                                )
                                                if image_url:
                                                    stdoutLines[idx] = f'![Output Image]({image_url})'

                                        ci_output['stdout'] = '\n'.join(stdoutLines)

                                    result = ci_output.get('result', '')

                                    if isinstance(result, str):
                                        resultLines = result.split('\n')
                                        for idx, line in enumerate(resultLines):
                                            if re.match(r'data:image/\w+;base64', line):
                                                image_url = await get_image_url_from_base64(
                                                    request,
                                                    line,
                                                    metadata,
                                                    user,
                                                )
                                                resultLines[idx] = f'![Output Image]({image_url})'
                                        ci_output['result'] = '\n'.join(resultLines)
                        except Exception as e:
                            ci_output = str(e)

                        ci_item['output'] = ci_output
                        ci_item['status'] = 'completed'

                        output.append(
                            {
                                'type': 'message',
                                'id': output_id('msg'),
                                'status': 'in_progress',
                                'role': 'assistant',
                                'content': [{'type': 'output_text', 'text': ''}],
                            }
                        )

                        await event_emitter(
                            {
                                'type': 'chat:completion',
                                'data': {
                                    'output': output,
                                },
                            }
                        )

                        try:
                            new_form_data = {
                                **form_data,
                                'model': model_id,
                                'stream': True,
                                'metadata': metadata,
                                'messages': [
                                    *form_data['messages'],
                                    *convert_output_to_messages(output, raw=True),
                                ],
                            }

                            res = await generate_chat_completion(
                                request,
                                new_form_data,
                                user,
                                bypass_system_prompt=True,
                            )

                            if isinstance(res, StreamingResponse):
                                await stream_body_handler(res, new_form_data)
                            else:
                                break
                        except Exception as e:
                            log.debug(e)
                            break

                validation_attempts = []
                validation_fallback_used = False
                harness_payload = _ephemeral_kahle_harness_payload(request)
                if (
                    metadata.get('kahle_knowledge_harness_active')
                    and harness_payload
                    and metadata.get('kahle_answer_stream_timed_out')
                ):
                    validation_fallback_used = True
                    validation_attempts.append({
                        'schema_version': 'kahle.answer-validation.v1',
                        'status': 'timeout',
                        'violations': [{
                            'code': 'answer_stream_timeout',
                            'message': 'Der Antwortstream wurde nicht rechtzeitig abgeschlossen.',
                        }],
                    })
                    metadata['kahle_answer_validation'] = {
                        'schema_version': 'kahle.answer-validation-run.v1',
                        'attempts': validation_attempts,
                    }
                elif metadata.get('kahle_knowledge_harness_active') and harness_payload:
                    validation = validate_knowledge_harness_answer(
                        _last_kahle_answer_text(output), harness_payload
                    )
                    validation_attempts.append(validation.to_dict())
                    metadata['kahle_answer_validation'] = {
                        'schema_version': 'kahle.answer-validation-run.v1',
                        'attempts': validation_attempts,
                    }

                if harness_payload:
                    intent_payload = harness_payload.get('user_intent') or {}
                    retrieval_payload = harness_payload.get('retrieval_plan') or {}
                    evidence_payload = harness_payload.get('evidence_bundle') or {}
                    permission_payload = retrieval_payload.get('permission_scope') or {}
                    started_at = metadata.get('_kahle_harness_started_monotonic')
                    elapsed_ms = (
                        max(0, round((time.monotonic() - started_at) * 1000))
                        if isinstance(started_at, (int, float))
                        else None
                    )
                    metadata['kahle_harness_metrics'] = {
                        'schema_version': 'kahle.harness-metrics.v1',
                        'model_id': str(model_id or ''),
                        'model_name': str(
                            (model.get('name') or model.get('id') or model_id)
                            if isinstance(model, dict)
                            else model_id
                        ),
                        'intent_kind': str(intent_payload.get('kind') or ''),
                        'required_tool': str(retrieval_payload.get('required_tool') or ''),
                        'tool_called': _knowledge_harness_tool_called(metadata),
                        'evidence_status': str(evidence_payload.get('status') or ''),
                        'source_count': len(evidence_payload.get('sources') or []),
                        'permission_scope_present': bool(permission_payload.get('user_id')),
                        'validation_attempts': len(validation_attempts),
                        'retry_count': max(0, len(validation_attempts) - 1),
                        'fallback_used': validation_fallback_used,
                        'final_validation_status': (
                            validation_attempts[-1].get('status')
                            if validation_attempts
                            else 'not_run'
                        ),
                        'delivery_status': (
                            'safe_timeout_fallback'
                            if metadata.get('kahle_answer_stream_timed_out')
                            else
                            'safe_fallback'
                            if validation_fallback_used
                            else (
                                validation_attempts[-1].get('status')
                                if validation_attempts
                                else 'not_run'
                            )
                        ),
                        'document_sources_present': bool(canonical_rag_sources),
                        'feedback_link_present': bool(canonical_rag_feedback_link),
                        'latency_ms': elapsed_ms,
                    }

                _append_canonical_rag_source_links(output, canonical_rag_sources)
                _append_canonical_rag_feedback_link(output, canonical_rag_feedback_link)

                # Mark all in-progress items as completed
                for item in output:
                    if item.get('status') == 'in_progress':
                        item['status'] = 'completed'

                title = (
                    await Chats.get_chat_title_by_id(metadata['chat_id'])
                    if not metadata.get('chat_id', '').startswith('channel:')
                    else ''
                )
                data = {
                    'done': True,
                    'output': output,
                    'title': title,
                    **({'usage': usage} if usage else {}),
                    **(
                        {'kahle_answer_validation': metadata['kahle_answer_validation']}
                        if metadata.get('kahle_answer_validation')
                        else {}
                    ),
                    **(
                        {'kahle_harness_metrics': metadata['kahle_harness_metrics']}
                        if metadata.get('kahle_harness_metrics')
                        else {}
                    ),
                }

                if not metadata.get('chat_id', '').startswith('channel:'):
                    if not ENABLE_REALTIME_CHAT_SAVE:
                        # Save message in the database
                        await Chats.upsert_message_to_chat_by_id_and_message_id(
                            metadata['chat_id'],
                            metadata['message_id'],
                            {
                                'done': True,
                                'output': output,
                                **({'usage': usage} if usage else {}),
                                **(
                                    {'kahle_answer_validation': metadata['kahle_answer_validation']}
                                    if metadata.get('kahle_answer_validation')
                                    else {}
                                ),
                                **(
                                    {'kahle_harness_metrics': metadata['kahle_harness_metrics']}
                                    if metadata.get('kahle_harness_metrics')
                                    else {}
                                ),
                            },
                        )
                    else:
                        realtime_metadata = {
                            **({'usage': usage} if usage else {}),
                            **(
                                {'kahle_answer_validation': metadata['kahle_answer_validation']}
                                if metadata.get('kahle_answer_validation')
                                else {}
                            ),
                            **(
                                {'kahle_harness_metrics': metadata['kahle_harness_metrics']}
                                if metadata.get('kahle_harness_metrics')
                                else {}
                            ),
                        }
                        await Chats.upsert_message_to_chat_by_id_and_message_id(
                            metadata['chat_id'],
                            metadata['message_id'],
                            {'done': True, **realtime_metadata},
                        )

                # Send a webhook notification if the user is not active
                if await Config.get('ui.enable_user_webhooks') and not await Users.is_user_active(user.id):
                    webhook_url = await Users.get_user_webhook_url_by_id(user.id)
                    if webhook_url:
                        webui_url = await Config.get('webui.url')
                        await post_webhook(
                            request.app.state.WEBUI_NAME,
                            webhook_url,
                            f'{content}\n\n{title} - {webui_url}/c/{metadata["chat_id"]}',
                            {
                                'action': 'chat',
                                'message': content,
                                'title': title,
                                'url': f'{webui_url}/c/{metadata["chat_id"]}',
                            },
                        )

                await event_emitter(
                    {
                        'type': 'chat:completion',
                        'data': data,
                    }
                )

                ctx['assistant_message'] = {
                    'output': output,
                    **({'usage': usage} if usage else {}),
                }
                await outlet_filter_handler(ctx)
                await background_tasks_handler(ctx)
            except asyncio.CancelledError:
                log.warning('Task was cancelled!')

                # Close the response body iterator to trigger cleanup
                # in stream_wrapper's finally block and release the
                # upstream connection.  Without this, the async
                # generator is orphaned and may spin in anyio internals.
                if hasattr(response, 'body_iterator') and hasattr(response.body_iterator, 'aclose'):
                    try:
                        await asyncio.shield(response.body_iterator.aclose())
                    except (asyncio.CancelledError, Exception):
                        pass

                async def save_cancelled_state():
                    await event_emitter({'type': 'chat:tasks:cancel'})
                    if not metadata.get('chat_id', '').startswith('channel:'):
                        if not ENABLE_REALTIME_CHAT_SAVE:
                            await Chats.upsert_message_to_chat_by_id_and_message_id(
                                metadata['chat_id'],
                                metadata['message_id'],
                                {
                                    'done': True,
                                    'output': output,
                                },
                            )
                        else:
                            await Chats.upsert_message_to_chat_by_id_and_message_id(
                                metadata['chat_id'],
                                metadata['message_id'],
                                {'done': True},
                            )

                try:
                    await asyncio.shield(save_cancelled_state())
                except (asyncio.CancelledError, Exception):
                    pass
                raise  # re-raise CancelledError for proper propagation

            if response.background is not None:
                await response.background()

        return await response_handler(response, events)

    else:
        # Fallback to the original response
        async def stream_wrapper(original_generator, events):
            def wrap_item(item):
                return f'data: {item}\n\n'

            assistant_message = {}
            filter_context = FilterContext()

            for event in events:
                event, _ = await process_filter_functions(
                    request=request,
                    filter_context=filter_context,
                    filter_functions=filter_functions,
                    filter_type='stream',
                    form_data=event,
                    extra_params=extra_params,
                )

                if event:
                    yield wrap_item(json.dumps(event))

            async for data in original_generator:
                data, _ = await process_filter_functions(
                    request=request,
                    filter_context=filter_context,
                    filter_functions=filter_functions,
                    filter_type='stream',
                    form_data=data,
                    extra_params=extra_params,
                )

                if data:
                    if ENABLE_API_OUTLET_FILTERS:
                        update_assistant_message_from_stream(assistant_message, data)
                    yield data

            if ENABLE_API_OUTLET_FILTERS and assistant_message:
                ctx['assistant_message'] = assistant_message
                await outlet_filter_handler(ctx)

        return StreamingResponse(
            stream_wrapper(response.body_iterator, events),
            headers=dict(response.headers),
            background=response.background,
        )


async def process_chat_response(response, ctx):
    # Non-streaming response
    if not isinstance(response, StreamingResponse):
        return await non_streaming_chat_response_handler(response, ctx)

    # Non standard response
    if not any(
        content_type in response.headers['Content-Type']
        for content_type in ['text/event-stream', 'application/x-ndjson']
    ):
        return response

    # Streaming response
    return await streaming_chat_response_handler(response, ctx)
