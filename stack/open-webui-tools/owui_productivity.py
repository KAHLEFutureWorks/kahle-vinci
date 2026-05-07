"""
title: OWUI Productivity
author: local
version: 0.1.0
description: Stabile normale Tools fuer OpenWebUI Notizen, Chat-Aufgaben und Automatisierungen ohne native Built-in-Tool-Injection.
"""

import json
from typing import Optional


def _json_error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _loads_tasks(tasks_json: str) -> list[dict]:
    try:
        data = json.loads(tasks_json)
    except Exception as exc:
        raise ValueError(f"tasks_json ist kein gueltiges JSON: {exc}")
    if not isinstance(data, list):
        raise ValueError("tasks_json muss eine JSON-Liste sein.")
    tasks = []
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        status = str(item.get("status") or "pending").strip().lower()
        if status not in {"pending", "in_progress", "completed", "cancelled"}:
            status = "pending"
        tasks.append(
            {
                "id": str(item.get("id") or idx),
                "content": content,
                "status": status,
            }
        )
    return tasks


class Tools:
    async def tasks_create(
        self,
        tasks_json: str,
        __chat_id__: str = None,
        __message_id__: str = None,
        __event_emitter__: callable = None,
        __request__=None,
        __user__: dict = None,
    ) -> str:
        """
        Erstellt oder ersetzt die Aufgabenliste im aktuellen Chat.

        :param tasks_json: JSON-Liste, z. B. [{"id":"1","content":"Recherche","status":"pending"}].
        """
        if not __chat_id__:
            return _json_error("Chat-Kontext fehlt. Aufgaben koennen nur innerhalb eines Chats erstellt werden.")
        try:
            from open_webui.tools.builtin import create_tasks

            return await create_tasks(
                _loads_tasks(tasks_json),
                __chat_id__=__chat_id__,
                __message_id__=__message_id__,
                __event_emitter__=__event_emitter__,
                __request__=__request__,
                __user__=__user__,
            )
        except Exception as exc:
            return _json_error(str(exc))

    async def tasks_update(
        self,
        id: str,
        status: str = "completed",
        __chat_id__: str = None,
        __message_id__: str = None,
        __event_emitter__: callable = None,
        __request__=None,
        __user__: dict = None,
    ) -> str:
        """
        Aktualisiert den Status einer Aufgabe im aktuellen Chat.

        :param id: Aufgaben-ID.
        :param status: pending, in_progress, completed oder cancelled.
        """
        if not __chat_id__:
            return _json_error("Chat-Kontext fehlt. Aufgaben koennen nur innerhalb eines Chats aktualisiert werden.")
        try:
            from open_webui.tools.builtin import update_task

            return await update_task(
                id=id,
                status=status,
                __chat_id__=__chat_id__,
                __message_id__=__message_id__,
                __event_emitter__=__event_emitter__,
                __request__=__request__,
                __user__=__user__,
            )
        except Exception as exc:
            return _json_error(str(exc))

    async def tasks_list(self, __chat_id__: str = None, __request__=None, __user__: dict = None) -> str:
        """
        Listet die Aufgaben im aktuellen Chat.
        """
        if not __chat_id__:
            return _json_error("Chat-Kontext fehlt.")
        try:
            from open_webui.models.chats import Chats

            tasks = await Chats.get_chat_tasks_by_id(__chat_id__)
            return json.dumps({"tasks": tasks or []}, ensure_ascii=False)
        except Exception as exc:
            return _json_error(str(exc))

    async def notes_create(self, title: str, content: str, __request__=None, __user__: dict = None) -> str:
        """
        Erstellt eine private OpenWebUI-Notiz fuer den aktuellen Nutzer.

        :param title: Titel der Notiz.
        :param content: Markdown-Inhalt der Notiz.
        """
        try:
            from open_webui.tools.builtin import write_note

            return await write_note(title=title, content=content, __request__=__request__, __user__=__user__)
        except Exception as exc:
            return _json_error(str(exc))

    async def notes_search(
        self,
        query: str,
        count: int = 5,
        __request__=None,
        __user__: dict = None,
    ) -> str:
        """
        Sucht private und freigegebene OpenWebUI-Notizen.

        :param query: Suchbegriff.
        :param count: Maximale Trefferzahl.
        """
        try:
            from open_webui.tools.builtin import search_notes

            return await search_notes(query=query, count=count, __request__=__request__, __user__=__user__)
        except Exception as exc:
            return _json_error(str(exc))

    async def notes_view(self, note_id: str, __request__=None, __user__: dict = None) -> str:
        """
        Zeigt eine OpenWebUI-Notiz vollstaendig an.

        :param note_id: ID der Notiz.
        """
        try:
            from open_webui.tools.builtin import view_note

            return await view_note(note_id=note_id, __request__=__request__, __user__=__user__)
        except Exception as exc:
            return _json_error(str(exc))

    async def notes_update(
        self,
        note_id: str,
        content: str,
        title: str = "",
        __request__=None,
        __user__: dict = None,
    ) -> str:
        """
        Ersetzt Inhalt und optional Titel einer bestehenden OpenWebUI-Notiz.

        :param note_id: ID der Notiz.
        :param content: Neuer Markdown-Inhalt.
        :param title: Optional neuer Titel.
        """
        try:
            from open_webui.tools.builtin import replace_note_content

            return await replace_note_content(
                note_id=note_id,
                content=content,
                title=title or None,
                __request__=__request__,
                __user__=__user__,
            )
        except Exception as exc:
            return _json_error(str(exc))

    async def automations_create(
        self,
        name: str,
        prompt: str,
        rrule: str,
        model_id: str = "",
        __request__=None,
        __user__: dict = None,
        __metadata__: dict = None,
    ) -> str:
        """
        Erstellt eine OpenWebUI-Automatisierung.

        :param name: Kurzer Name der Automatisierung.
        :param prompt: Prompt, der automatisch ausgefuehrt werden soll.
        :param rrule: iCalendar RRULE mit optionalem DTSTART, z. B. DTSTART:20260506T090000\\nRRULE:FREQ=DAILY.
        :param model_id: Optionales Modell. Leer nutzt das aktuelle Modell oder KAHLE-Vinci.
        """
        try:
            from open_webui.tools.builtin import create_automation

            metadata = dict(__metadata__ or {})
            if model_id and not metadata.get("model_id"):
                metadata["model_id"] = model_id
            if not metadata.get("model_id"):
                metadata["model_id"] = "vinci-2-clone-clone-clone"
            return await create_automation(
                name=name,
                prompt=prompt,
                rrule=rrule,
                __request__=__request__,
                __user__=__user__,
                __metadata__=metadata,
            )
        except Exception as exc:
            return _json_error(str(exc))

    async def automations_list(
        self,
        status: str = "",
        count: int = 10,
        __request__=None,
        __user__: dict = None,
    ) -> str:
        """
        Listet OpenWebUI-Automatisierungen des aktuellen Nutzers.

        :param status: Optional active oder paused.
        :param count: Maximale Trefferzahl.
        """
        try:
            from open_webui.tools.builtin import list_automations

            return await list_automations(
                status=status or None,
                count=count,
                __request__=__request__,
                __user__=__user__,
            )
        except Exception as exc:
            return _json_error(str(exc))

    async def automations_update(
        self,
        automation_id: str,
        name: str = "",
        prompt: str = "",
        rrule: str = "",
        model_id: str = "",
        __request__=None,
        __user__: dict = None,
    ) -> str:
        """
        Aktualisiert eine bestehende OpenWebUI-Automatisierung.

        :param automation_id: ID der Automatisierung.
        :param name: Optional neuer Name.
        :param prompt: Optional neuer Prompt.
        :param rrule: Optional neue RRULE.
        :param model_id: Optional neues Modell.
        """
        try:
            from open_webui.tools.builtin import update_automation

            return await update_automation(
                automation_id=automation_id,
                name=name or None,
                prompt=prompt or None,
                rrule=rrule or None,
                model_id=model_id or None,
                __request__=__request__,
                __user__=__user__,
            )
        except Exception as exc:
            return _json_error(str(exc))

    async def automations_toggle(self, automation_id: str, __request__=None, __user__: dict = None) -> str:
        """
        Pausiert oder reaktiviert eine OpenWebUI-Automatisierung.

        :param automation_id: ID der Automatisierung.
        """
        try:
            from open_webui.tools.builtin import toggle_automation

            return await toggle_automation(automation_id=automation_id, __request__=__request__, __user__=__user__)
        except Exception as exc:
            return _json_error(str(exc))

    async def automations_delete(self, automation_id: str, __request__=None, __user__: dict = None) -> str:
        """
        Loescht eine OpenWebUI-Automatisierung.

        :param automation_id: ID der Automatisierung.
        """
        try:
            from open_webui.tools.builtin import delete_automation

            return await delete_automation(automation_id=automation_id, __request__=__request__, __user__=__user__)
        except Exception as exc:
            return _json_error(str(exc))
