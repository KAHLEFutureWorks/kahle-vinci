"""
title: RAG_Chat KAHLE (Qdrant)
author: local
version: 0.6.1
description: Durchsucht die internen KAHLE Knowledgebases direkt in Qdrant und gibt zitierbaren Kontext zurück.
"""

from pydantic import BaseModel, Field
import os
import re
import requests
import unicodedata


NUMBER_WORDS = {
    "eins": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fuenf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
}
ORDINAL_WORDS = {
    "erste": 1, "erster": 1, "erstes": 1,
    "zweite": 2, "zweiter": 2, "zweites": 2,
    "dritte": 3, "dritter": 3, "drittes": 3,
    "vierte": 4, "vierter": 4, "viertes": 4,
    "fuenfte": 5, "fuenfter": 5, "fuenftes": 5,
    "sechste": 6, "siebte": 7, "achte": 8, "neunte": 9, "zehnte": 10,
}
SINGULAR_LABELS = {
    "dimensionen": "dimension",
    "phasen": "phase",
    "schritte": "schritt",
    "kriterien": "kriterium",
    "bereiche": "bereich",
    "punkte": "punkt",
    "stufen": "stufe",
    "kategorien": "kategorie",
    "elemente": "element",
    "themen": "thema",
    "rollen": "rolle",
    "regeln": "regel",
    "massnahmen": "massnahme",
}

def _env(*names, default=""):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _ascii_fold(text):
    return (
        unicodedata.normalize("NFKC", text or "")
        .lower()
        .replace("\u00e4", "ae")
        .replace("\u00f6", "oe")
        .replace("\u00fc", "ue")
        .replace("\u00df", "ss")
    )


def _is_raw_mail_query(query):
    folded = _ascii_fold(str(query or ""))
    if not folded:
        return False

    folded = re.sub(
        r"^\s*(beantworte|beantworten|antworte auf|antwort auf|formuliere eine antwort auf)\s+(die\s+)?mail\s*:?\s*",
        "",
        folded,
    ).strip()

    lines = [line.strip() for line in folded.splitlines() if line.strip()]
    if len(lines) < 3:
        return False

    has_mail_header = any(
        token in folded
        for token in (
            "\nvon:",
            "\ngesendet:",
            "\nan:",
            "\nbetreff:",
            "-----urspruengliche nachricht-----",
            "-----weitergeleitete nachricht-----",
        )
    )
    starts_with_salutation = re.match(
        r"^(hallo|moin|servus|guten tag|sehr geehrte|sehr geehrter|liebe|lieber)\b",
        lines[0],
    ) is not None
    has_signoff = any(
        token in folded
        for token in (
            "mit freundlichen gruessen",
            "viele gruesse",
            "beste gruesse",
            "freundliche gruesse",
        )
    )
    has_mail_body_signals = any(
        token in folded
        for token in (
            "ich benoetige",
            "ich brauche",
            "ich habe",
            "bitte",
            "koennten sie",
            "kannst du",
            "anbei",
            "siehe anhang",
        )
    )
    has_system_or_file_terms = any(
        token in folded
        for token in (
            "csv",
            "catch",
            "gudat",
            "dokumenten-id",
            "datei",
            "auftrag",
            "termin",
            "center",
        )
    )

    return has_mail_header or (
        starts_with_salutation
        and len(folded) > 180
        and (has_signoff or (has_mail_body_signals and has_system_or_file_terms))
    )


def _post_json(url, payload, headers=None, timeout=60):
    response = requests.post(url, headers=headers or {}, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _embed_query(base_url, api_key, model, query, timeout):
    body = _post_json(
        f"{base_url.rstrip('/')}/embeddings",
        {"model": model, "input": query},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=timeout,
    )
    vector = ((body.get("data") or [{}])[0]).get("embedding")
    if not isinstance(vector, list):
        raise ValueError("Embedding API returned no embedding vector")
    return vector


def _discover_collections(configured):
    names = {item.strip() for item in configured.split(",") if item.strip()}
    root = _env("KB_ROOT", default="/knowledgebases")
    try:
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if name.startswith(".") or not os.path.isdir(path):
                continue
            if re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,47}", name):
                names.add(name)
    except OSError:
        pass
    return sorted(names)


def _query_identifiers(query):
    """Extract short product/document identifiers such as A1a, A1b or B2c."""
    folded = _ascii_fold(str(query or ""))
    return sorted(set(re.findall(r"(?<![a-z0-9])([a-z]\d+[a-z]?)(?![a-z0-9])", folded)))


def _expand_followup_query(query, messages):
    """Make short follow-up queries standalone by carrying forward a prior identifier."""
    query = str(query or "").strip()
    if _query_identifiers(query) or not isinstance(messages, list):
        return query
    skipped_current = False
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        if not skipped_current and content.strip() == query:
            skipped_current = True
            continue
        identifiers = _query_identifiers(content)
        if identifiers:
            return f"{query} Bezug: {' '.join(identifiers)}"
    return query


def _matching_sources(collections, query):
    """Resolve explicit identifiers against source filenames before vector search."""
    identifiers = _query_identifiers(query)
    if not identifiers:
        return {}
    root = _env("KB_ROOT", default="/knowledgebases")
    matches = {}
    for collection in collections:
        collection_root = os.path.join(root, collection)
        try:
            candidates = []
            for current_root, _dirs, files in os.walk(collection_root):
                for filename in files:
                    folded_name = _ascii_fold(filename)
                    if not all(
                        re.search(rf"(?<![a-z0-9]){re.escape(identifier)}(?![a-z0-9])", folded_name)
                        for identifier in identifiers
                    ):
                        continue
                    full_path = os.path.join(current_root, filename)
                    candidates.append(os.path.relpath(full_path, collection_root).replace(os.sep, "/"))
            if candidates:
                matches[collection] = sorted(set(candidates))
        except OSError:
            continue
    return matches

def _enumeration_hint(query):
    """Detect questions asking for a distributed list such as 5 dimensions or 3 phases."""
    folded = _ascii_fold(str(query or ""))
    number_pattern = r"\d{1,2}|" + "|".join(NUMBER_WORDS)
    match = re.search(
        rf"\b(?P<count>{number_pattern})\s+(?P<label>[a-z][a-z-]{{3,}})\b",
        folded,
    )
    if match:
        raw_count = match.group("count")
        count = int(raw_count) if raw_count.isdigit() else NUMBER_WORDS.get(raw_count)
        return {"count": count, "label": match.group("label")}

    match = re.search(
        r"\b(?:welche|was\s+sind(?:\s+die)?|nenne(?:\s+mir)?(?:\s+die)?)\s+"
        r"(?P<label>[a-z][a-z-]{3,})\b",
        folded,
    )
    if match:
        return {"count": None, "label": match.group("label")}
    return {}


def _label_stems(label):
    label = _ascii_fold(str(label or "")).strip("- ")
    stems = {label}
    mapped = SINGULAR_LABELS.get(label)
    if mapped:
        stems.add(mapped)
    for suffix in ("innen", "ern", "en", "er", "es", "e", "n", "s"):
        if label.endswith(suffix) and len(label) - len(suffix) >= 4:
            stems.add(label[: -len(suffix)])
    return sorted((stem for stem in stems if len(stem) >= 4), key=len, reverse=True)


def _normalize_point(collection, item):
    payload = item.get("payload") or {}
    text = payload.get("text") or payload.get("content") or ""
    if not text:
        return {}
    return {
        "collection": payload.get("kb") or collection,
        "doc_id": payload.get("doc_id") or "",
        "source_path": payload.get("source_path") or "",
        "chunk_index": payload.get("chunk_index"),
        "score": float(item.get("score") or 0.0),
        "text": str(text),
    }

def _search_collection(qdrant_url, collection, vector, limit, timeout, source_paths=None):
    body = _post_json(
        f"{qdrant_url.rstrip('/')}/collections/{collection}/points/search",
        {
            "vector": vector,
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
            **(
                {
                    "filter": {
                        "should": [
                            {"key": "source_path", "match": {"value": source_path}}
                            for source_path in source_paths
                        ]
                    }
                }
                if source_paths
                else {}
            ),
        },
        timeout=timeout,
    )
    results = body.get("result") or []
    normalized = []
    for item in results:
        normalized_item = _normalize_point(collection, item)
        if normalized_item:
            normalized.append(normalized_item)
    return normalized


def _scroll_source_chunks(qdrant_url, collection, source_paths, timeout, max_points=512):
    """Read chunks of an already selected source for structure-aware retrieval."""
    if not source_paths:
        return []
    chunks = []
    offset = None
    while len(chunks) < int(max_points):
        payload = {
            "limit": min(256, int(max_points) - len(chunks)),
            "with_payload": True,
            "with_vector": False,
            "filter": {
                "should": [
                    {"key": "source_path", "match": {"value": source_path}}
                    for source_path in source_paths
                ]
            },
        }
        if offset is not None:
            payload["offset"] = offset
        body = _post_json(
            f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll",
            payload,
            timeout=timeout,
        )
        result = body.get("result") or {}
        points = result.get("points") or []
        for item in points:
            normalized_item = _normalize_point(collection, item)
            if normalized_item:
                chunks.append(normalized_item)
        next_offset = result.get("next_page_offset")
        if not points or next_offset is None or next_offset == offset:
            break
        offset = next_offset
    return chunks


def _heading_lines(text):
    return [
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$", str(text or ""))
    ]


def _heading_index(heading, stems):
    folded = _ascii_fold(heading)
    for stem in stems:
        after_label = re.search(
            rf"\b{re.escape(stem)}[a-z-]*\s*[:#-]?\s*(\d{{1,2}})\b",
            folded,
        )
        if after_label:
            return int(after_label.group(1))
        before_label = re.search(
            rf"^\s*(\d{{1,2}})[.)\s:-]+(?:die\s+)?{re.escape(stem)}[a-z-]*\b",
            folded,
        )
        if before_label:
            return int(before_label.group(1))
        for word, index in ORDINAL_WORDS.items():
            if re.search(
                rf"\b(?:{re.escape(word)}\s+{re.escape(stem)}[a-z-]*|"
                rf"{re.escape(stem)}[a-z-]*\s+{re.escape(word)})\b",
                folded,
            ):
                return index
    return None


def _select_structural_chunks(chunks, query, max_chunks):
    """Select distinct numbered headings from one document for enumeration questions."""
    hint = _enumeration_hint(query)
    if not hint:
        return []
    stems = _label_stems(hint.get("label"))
    expected = hint.get("count")
    by_index = {}
    fallback_numbered = {}
    for chunk in sorted(chunks, key=lambda item: int(item.get("chunk_index") or 0)):
        for heading in _heading_lines(chunk.get("text")):
            index = _heading_index(heading, stems)
            if index is not None and index >= 1:
                candidate = dict(chunk)
                candidate["match_type"] = "structural"
                by_index.setdefault(index, candidate)
                continue
            numbered = re.match(r"^\s*(\d{1,2})[.)\s:-]+", _ascii_fold(heading))
            if numbered:
                candidate = dict(chunk)
                candidate["match_type"] = "structural"
                fallback_numbered.setdefault(int(numbered.group(1)), candidate)

    selected_map = by_index
    if expected and len(by_index) < expected:
        selected_map = {**fallback_numbered, **by_index}
    indexes = sorted(selected_map)
    if expected:
        indexes = [index for index in indexes if index <= int(expected)]
    return [selected_map[index] for index in indexes[: int(max_chunks)]]


def _merge_context_chunks(structural, semantic, max_chunks):
    merged = []
    seen = set()
    for chunk in [*structural, *semantic]:
        identity = (
            chunk.get("collection") or "",
            chunk.get("source_path") or "",
            chunk.get("chunk_index"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(chunk)
        if len(merged) >= int(max_chunks):
            break
    return merged

def _is_broad_query(query):
    folded = _ascii_fold(str(query or ""))
    return bool(
        re.search(
            r"\b(?:wie\s+(?:genau\s+)?(?:arbeite|funktioniert|geht|nutze|verwende)|"
            r"erklaer(?:e|ung)?|anleitung|ablauf|prozess|uebersicht|"
            r"was\s+weisst\s+du\s+(?:intern\s+)?ueber)\b",
            folded,
        )
    )


def _is_exhaustive_query(query):
    folded = _ascii_fold(str(query or ""))
    return bool(
        re.search(
            r"\b(?:alles|saemtliche|vollstaendig(?:e|en|er|es)?|"
            r"alle\s+(?:punkte|schritte|regeln|anforderungen|vorgaben|informationen|"
            r"faelle|themen|kriterien|massnahmen|freigaben|bestaetigungen))\b",
            folded,
        )
    )

def _chunk_number(chunk):
    try:
        return int(chunk.get("chunk_index"))
    except (TypeError, ValueError):
        return -1


def _expand_source_context(
    source_chunks,
    seeds,
    max_chunks,
    max_chars,
    neighbor_radius=1,
    broad=False,
    exhaustive=False,
):
    """Expand relevant seed chunks with coherent neighbours from one source."""
    source_by_index = {
        _chunk_number(chunk): dict(chunk)
        for chunk in source_chunks
        if _chunk_number(chunk) >= 0
    }
    if not source_by_index:
        return list(seeds)[: int(max_chunks)]

    seed_by_index = {}
    for seed in seeds:
        index = _chunk_number(seed)
        if index < 0 or index not in source_by_index:
            continue
        candidate = dict(source_by_index[index])
        candidate.update(seed)
        seed_by_index[index] = candidate

    if not seed_by_index:
        return []

    seed_indexes = list(seed_by_index)
    complete_size = sum(len(str(chunk.get("text") or "")) for chunk in source_by_index.values())
    complete_fits = len(source_by_index) <= int(max_chunks) and complete_size <= int(max_chars)
    if exhaustive and complete_fits:
        candidate_indexes = sorted(source_by_index)
    elif broad:
        candidate_indexes = sorted(
            source_by_index,
            key=lambda index: (min(abs(index - seed) for seed in seed_indexes), index),
        )
    else:
        allowed = set(seed_indexes)
        for seed in seed_indexes:
            for delta in range(1, max(0, int(neighbor_radius)) + 1):
                allowed.update((seed - delta, seed + delta))
        candidate_indexes = sorted(
            (index for index in allowed if index in source_by_index),
            key=lambda index: (
                0 if index in seed_by_index else 1,
                min(abs(index - seed) for seed in seed_indexes),
                index,
            ),
        )

    selected = []
    used_chars = 0
    for index in candidate_indexes:
        is_seed = index in seed_by_index
        chunk = dict(seed_by_index.get(index) or source_by_index[index])
        if not is_seed:
            chunk["match_type"] = "neighbor"
        size = len(str(chunk.get("text") or ""))
        if selected and used_chars + size > int(max_chars):
            continue
        selected.append(chunk)
        used_chars += size
        if len(selected) >= int(max_chunks):
            break
    return sorted(selected, key=_chunk_number)


def _trim_adjacent_overlap(previous, current, max_overlap=400, min_overlap=40):
    previous = str(previous or "")
    current = str(current or "")
    upper = min(int(max_overlap), len(previous), len(current))
    for size in range(upper, int(min_overlap) - 1, -1):
        if previous[-size:] == current[:size]:
            return current[size:].lstrip()
    return current

def _build_context(chunks):
    parts = []
    previous_text = ""
    previous_source = None
    previous_index = None
    for index, chunk in enumerate(chunks, start=1):
        match_info = (
            "structure"
            if chunk.get("match_type") == "structural"
            else "neighbor"
            if chunk.get("match_type") == "neighbor"
            else f"score {chunk['score']:.3f}"
        )
        header = (
            f"[#{index} | {chunk['collection']} | {chunk['source_path']} "
            f"| chunk {chunk['chunk_index']} | {match_info}]"
        )
        text = str(chunk.get("text") or "")
        source = (chunk.get("collection") or "", chunk.get("source_path") or "")
        chunk_index = _chunk_number(chunk)
        if source == previous_source and previous_index is not None and chunk_index == previous_index + 1:
            text = _trim_adjacent_overlap(previous_text, text)
        parts.append(f"{header}\n{text}".strip())
        previous_text = str(chunk.get("text") or "")
        previous_source = source
        previous_index = chunk_index
    return "\n\n".join(parts).strip()


def _prefer_top_source_chunks(chunks, max_chunks, score_floor):
    """Keep the model grounded in the best matching document."""
    if not chunks:
        return []

    top = chunks[0]
    top_source = (top.get("collection") or "", top.get("source_path") or "")
    if not top_source[1]:
        return chunks[: int(max_chunks)]

    filtered = [
        chunk
        for chunk in chunks
        if (chunk.get("collection") or "", chunk.get("source_path") or "") == top_source
        and float(chunk.get("score") or 0.0) >= float(score_floor)
    ]
    return (filtered or [top])[: int(max_chunks)]


class Tools:
    class Valves(BaseModel):
        QDRANT_URL: str = Field(
            default="http://qdrant:6333",
            description="Interne Qdrant URL aus dem Open-WebUI Docker-Netzwerk",
        )
        IONOS_OPENAI_BASE_URL: str = Field(
            default="",
            description="Optional. Leer nutzt RAG_OPENAI_API_BASE_URL/OPENAI_API_BASE_URL aus der Umgebung.",
        )
        IONOS_API_KEY: str = Field(
            default="",
            description="Optional. Leer nutzt RAG_OPENAI_API_KEY/OPENAI_API_KEY aus der Umgebung.",
        )
        IONOS_EMBEDDING_MODEL: str = Field(
            default="",
            description="Optional. Leer nutzt RAG_EMBEDDING_MODEL oder BAAI/bge-m3.",
        )
        COLLECTIONS_CSV: str = Field(
            default="kahleallgemein,kahlekontext,kahlerichtlinien",
            description="Kommagetrennte Qdrant Collections, die durchsucht werden.",
        )
        ANSWER_THRESHOLD: float = Field(default=0.45, description="Mindestscore für FOUND true.")
        MAX_CHUNKS: int = Field(default=6, description="Maximale Anzahl Kontext-Chunks.")
        CONTEXT_MAX_CHARS: int = Field(default=12000, description="Maximales Zeichenbudget fuer den RAG-Kontext.")
        NEIGHBOR_RADIUS: int = Field(default=1, description="Nachbar-Chunks je relevantem Treffer.")
        TIMEOUT_S: int = Field(default=60, description="HTTP Timeout in Sekunden.")

    def __init__(self):
        self.valves = self.Valves()

    async def rag_chat(self, query: str = "", __messages__: list[dict] | None = None) -> str:
        """
        Suche in den internen KAHLE Knowledgebases. Bei Folgefragen erneut aufrufen und die vorherige Produkt-ID im query beibehalten.
        Verwende dieses Tool immer, wenn die Nutzerfrage interne KAHLE-Informationen,
        Standorte, Marken, Prozesse, Richtlinien, Angebote, Personen, Kultur,
        Unternehmenswissen oder gespeicherte Knowledgebase-Inhalte betrifft.
        """
        query = str(query or "").strip()
        if not query and isinstance(__messages__, list):
            for message in reversed(__messages__):
                if not isinstance(message, dict):
                    continue
                if message.get("role") != "user":
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    query = content.strip()
                    break
        if not query:
            return (
                "KAHLE_RAG_RESULT\n"
                "FOUND: false\n"
                "ERROR: Der Toolcall enthielt keinen query-Parameter und es konnte keine letzte User-Nachricht gelesen werden.\n"
                "INSTRUCTION: Rufe rag_chat erneut auf und setze query auf die letzte Nutzerfrage."
            )
        query = _expand_followup_query(query, __messages__)
        if _is_raw_mail_query(query):
            return (
                "KAHLE_RAG_RESULT\n"
                "FOUND: false\n"
                "ERROR: Der query-Parameter sieht nach einer kompletten E-Mail oder einem Mailverlauf aus.\n"
                "INSTRUCTION: RAG_Chat nicht mit kompletten Mails aufrufen. "
                "Extrahiere zuerst eine kompakte interne Sachfrage mit maximal 12 Woertern, "
                "z. B. 'Standort Walsrode Oeffnungszeiten' oder 'Richtlinie Kundendaten E-Mail'. "
                "Wenn keine interne Sachfrage benoetigt wird, antworte ohne RAG."
            )

        base_url = self.valves.IONOS_OPENAI_BASE_URL or _env(
            "RAG_OPENAI_API_BASE_URL",
            "OPENAI_API_BASE_URL",
            default="https://openai.inference.de-txl.ionos.com/v1",
        )
        api_key = self.valves.IONOS_API_KEY or _env("RAG_OPENAI_API_KEY", "OPENAI_API_KEY")
        model = self.valves.IONOS_EMBEDDING_MODEL or _env("RAG_EMBEDDING_MODEL", default="BAAI/bge-m3")
        qdrant_url = self.valves.QDRANT_URL or _env("QDRANT_URI", default="http://qdrant:6333")
        timeout = int(self.valves.TIMEOUT_S)

        if not api_key:
            return "KAHLE_RAG_RESULT\nFOUND: false\nERROR: IONOS API Key fehlt im Tool oder in der Container-Umgebung."

        collections = _discover_collections(self.valves.COLLECTIONS_CSV)
        if not collections:
            return "KAHLE_RAG_RESULT\nFOUND: false\nERROR: Keine Qdrant Collections konfiguriert."

        try:
            vector = _embed_query(base_url, api_key, model, query, timeout)
            all_chunks = []
            exact_sources = _matching_sources(collections, query)
            search_collections = sorted(exact_sources) if exact_sources else collections
            per_collection_limit = max(int(self.valves.MAX_CHUNKS), 3)
            for collection in search_collections:
                all_chunks.extend(
                    _search_collection(
                        qdrant_url,
                        collection,
                        vector,
                        per_collection_limit,
                        timeout,
                        source_paths=exact_sources.get(collection),
                    )
                )
        except Exception as exc:
            return f"KAHLE_RAG_RESULT\nFOUND: false\nERROR: {exc}"

        all_chunks.sort(key=lambda item: item["score"], reverse=True)
        top_candidates = all_chunks[: int(self.valves.MAX_CHUNKS)]
        top_score = top_candidates[0]["score"] if top_candidates else 0.0
        threshold = float(self.valves.ANSWER_THRESHOLD)

        if not top_candidates or top_score < threshold:
            return (
                "KAHLE_RAG_RESULT\n"
                "FOUND: false\n"
                f"QUERY: {query}\n"
                "INSTRUCTION: Keine passenden internen Treffer. Antworte exakt: "
                "'Dazu habe ich keine internen Infos.'\n"
                f"META: top1_score={top_score:.3f} threshold={threshold:.2f}"
            )

        top_chunks = _prefer_top_source_chunks(top_candidates, int(self.valves.MAX_CHUNKS), threshold)
        structural_chunks = []
        source_chunks = []
        document_chunk_count = 0
        exhaustive_query = _is_exhaustive_query(query)
        retrieval_mode = "exhaustive" if exhaustive_query else "broad" if _is_broad_query(query) else "focused"
        if top_chunks and top_chunks[0].get("source_path"):
            source_map = {
                top_chunks[0]["collection"]: [top_chunks[0]["source_path"]]
            }
            try:
                for collection, source_paths in source_map.items():
                    source_chunks.extend(
                        _scroll_source_chunks(
                            qdrant_url,
                            collection,
                            source_paths,
                            timeout,
                        )
                    )
                document_chunk_count = len(source_chunks)
                if _enumeration_hint(query):
                    structural_chunks = _select_structural_chunks(
                        source_chunks,
                        query,
                        int(self.valves.MAX_CHUNKS),
                    )
                seeds = _merge_context_chunks(
                    structural_chunks,
                    top_chunks,
                    int(self.valves.MAX_CHUNKS),
                )
                expanded = _expand_source_context(
                    source_chunks,
                    seeds,
                    int(self.valves.MAX_CHUNKS),
                    int(self.valves.CONTEXT_MAX_CHARS),
                    neighbor_radius=int(self.valves.NEIGHBOR_RADIUS),
                    broad=_is_broad_query(query) or exhaustive_query,
                    exhaustive=exhaustive_query,
                )
                if expanded:
                    top_chunks = expanded
            except Exception:
                source_chunks = []
                document_chunk_count = 0
                structural_chunks = []

        selected_indexes = ",".join(
            str(_chunk_number(chunk)) for chunk in top_chunks if _chunk_number(chunk) >= 0
        ) or "n/a"
        coverage = (
            f"{len(top_chunks)}/{document_chunk_count}"
            if document_chunk_count
            else f"{len(top_chunks)}/?"
        )
        truncated = bool(document_chunk_count and len(top_chunks) < document_chunk_count)
        context = _build_context(top_chunks)
        return (
            "KAHLE_RAG_RESULT\n"
            "FOUND: true\n"
            f"QUERY: {query}\n"
            "INSTRUCTION: Nutze AUSSCHLIESSLICH den Kontext unten. "
            "Der RAG-Kontext hat Vorrang vor Chatverlauf und Modellwissen. "
            "Korrigiere fruehere Antworten, wenn sie abweichen. "
            "Keine Vermutungen oder Ergaenzungen. Jede KAHLE-Aussage muss eine Quellenmarke [#] enthalten.\n"
            f"META: top1_score={top_score:.3f} threshold={threshold:.2f} model={model} "
            f"routing={'exact_source' if exact_sources else 'semantic'} "
            f"structure_hits={len(structural_chunks)} retrieval_mode={retrieval_mode} selected_chunks={selected_indexes} "
            f"document_chunks={document_chunk_count or 'unknown'} context_coverage={coverage} "
            f"truncated={str(truncated).lower()} context_chars={len(context)}\n\n"
            "KONTEXT (zitierbar mit [#]):\n"
            f"{context}"
        )
