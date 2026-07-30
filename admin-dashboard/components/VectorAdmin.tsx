"use client";

import {
  ArchiveRestore,
  Check,
  ChevronRight,
  CircleAlert,
  Database,
  File,
  FileCode2,
  FileText,
  FolderInput,
  History,
  LoaderCircle,
  Menu,
  MoveRight,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  ChangeEvent,
  DragEvent,
  FormEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type Collection = {
  id: string;
  label: string;
  files: number;
  last_indexed_at: string;
  deletable?: boolean;
};

type TrashedCollection = {
  archive_id: string;
  collection: string;
  label: string;
  files: number;
  archived_at: string;
  purge_at: string;
  retention_days: number;
};

type DocumentSummary = {
  collection: string;
  path: string;
  name: string;
  extension: string;
  size: number;
  modified_at: string;
  chunks: number;
  indexed_at: string;
  index_status: "current" | "pending" | "excluded" | "error";
  title: string;
  document_id: string;
  owner: string;
  valid_until: string;
  days_remaining: number | null;
  notify_before_days?: number;
  expiry_status: "none" | "expired" | "critical" | "warning" | "valid";
  locations: string[];
  tags: string[];
  rag_index: boolean;
};

type DocumentDetail = DocumentSummary & {
  editable: boolean;
  content: string;
  preview: string;
};

type Chunk = { id: string; index: number; content: string };
type Version = {
  id: string;
  action: string;
  actor: string;
  created_at: string;
  size: number;
  sha256: string;
};
type Tab = "markdown" | "preview" | "chunks" | "versions";

type UnlockStatus = {
  enabled: boolean;
  unlocked: boolean;
  ttl_seconds: number;
};

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const API_BASE = "/admin/vector/api";

const demoCollections: Collection[] = [
  {
    id: "kahleallgemein",
    label: "Allgemeines Wissen",
    files: 42,
    last_indexed_at: "2026-07-28T06:14:00Z",
  },
  {
    id: "kahlekontext",
    label: "Standorte & Unternehmen",
    files: 61,
    last_indexed_at: "2026-07-28T06:14:00Z",
  },
  {
    id: "kahlerichtlinien",
    label: "Richtlinien & Prozesse",
    files: 34,
    last_indexed_at: "2026-07-28T06:14:00Z",
  },
];

const demoDocuments: DocumentSummary[] = [
  {
    collection: "kahleallgemein",
    path: "service/garantie-anschlussgarantie-2026.md",
    name: "garantie-anschlussgarantie-2026.md",
    extension: "md",
    size: 6412,
    modified_at: "2026-07-24T09:42:00+02:00",
    chunks: 18,
    indexed_at: "2026-07-24T09:43:00Z",
    index_status: "current",
    title: "Anschlussgarantie 2026",
    document_id: "KB-SERVICE-GARANTIE-2026",
    owner: "Serviceleitung",
    valid_until: "2026-08-14",
    days_remaining: 17,
    expiry_status: "warning",
    locations: ["Hannover", "Langenhagen"],
    tags: ["garantie", "preise"],
    rag_index: true,
  },
  {
    collection: "kahleallgemein",
    path: "service/inspektionspreise-hannover.pdf",
    name: "inspektionspreise-hannover.pdf",
    extension: "pdf",
    size: 246800,
    modified_at: "2026-07-22T11:20:00+02:00",
    chunks: 34,
    indexed_at: "2026-07-22T11:22:00Z",
    index_status: "current",
    title: "Inspektionspreise Hannover",
    document_id: "KB-SERVICE-PREISE-HAN",
    owner: "Serviceleitung Hannover",
    valid_until: "2026-08-20",
    days_remaining: 23,
    expiry_status: "warning",
    locations: ["Hannover"],
    tags: ["inspektion", "preise"],
    rag_index: true,
  },
  {
    collection: "kahleallgemein",
    path: "service/raederwechsel-aktion-herbst.docx",
    name: "raederwechsel-aktion-herbst.docx",
    extension: "docx",
    size: 48200,
    modified_at: "2026-07-19T14:10:00+02:00",
    chunks: 9,
    indexed_at: "2026-07-19T14:12:00Z",
    index_status: "current",
    title: "Räderwechsel-Aktion Herbst",
    document_id: "KB-SERVICE-RAEDER-HERBST",
    owner: "Marketing",
    valid_until: "2026-09-07",
    days_remaining: 41,
    expiry_status: "warning",
    locations: ["Alle Standorte"],
    tags: ["reifen", "aktion"],
    rag_index: true,
  },
  {
    collection: "kahleallgemein",
    path: "service/hu-au-terminleitfaden.md",
    name: "hu-au-terminleitfaden.md",
    extension: "md",
    size: 3810,
    modified_at: "2026-07-15T08:30:00+02:00",
    chunks: 12,
    indexed_at: "2026-07-15T08:31:00Z",
    index_status: "current",
    title: "HU/AU-Terminleitfaden",
    document_id: "KB-SERVICE-HUAU",
    owner: "Service",
    valid_until: "2026-10-24",
    days_remaining: 88,
    expiry_status: "valid",
    locations: ["Alle Standorte"],
    tags: ["hu", "au", "termin"],
    rag_index: true,
  },
  {
    collection: "kahleallgemein",
    path: "service/serviceleistungen-uebersicht.md",
    name: "serviceleistungen-uebersicht.md",
    extension: "md",
    size: 7240,
    modified_at: "2026-07-11T10:05:00+02:00",
    chunks: 21,
    indexed_at: "2026-07-11T10:06:00Z",
    index_status: "current",
    title: "Serviceleistungen Übersicht",
    document_id: "KB-SERVICE-UEBERSICHT",
    owner: "Serviceleitung",
    valid_until: "",
    days_remaining: null,
    expiry_status: "none",
    locations: ["Alle Standorte"],
    tags: ["service"],
    rag_index: true,
  },
];

const demoMarkdown = `---
title: Anschlussgarantie 2026
document_id: KB-SERVICE-GARANTIE-2026
valid_until: 2026-08-14
owner: Serviceleitung
standorte: [Hannover, Langenhagen]
tags: [garantie, preise]
rag_index: true
---

# Anschlussgarantie 2026

Die Anschlussgarantie verlängert den Werksgarantieschutz um bis zu 24 Monate.
Der Abschluss ist bis 30 Tage vor Ablauf der Herstellergarantie möglich.

## Leistungsumfang

- Motor, Getriebe, Elektrik
- Mobilitätsgarantie inklusive
- Gültig in allen sieben KAHLE Standorten

## Preise

| Laufzeit | Bis 100.000 km | Bis 150.000 km |
| --- | --- | --- |
| 12 Monate | 449 € | 599 € |
| 24 Monate | 749 € | 949 € |
`;

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const token =
    typeof window !== "undefined"
      ? window.localStorage.getItem("token") || window.localStorage.getItem("authToken")
      : "";
  const headers = new Headers(options?.headers);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", token.toLowerCase().startsWith("bearer ") ? token : `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    if (response.status === 423 && typeof window !== "undefined") {
      window.dispatchEvent(new Event("kahle-vector-locked"));
    }
    throw new ApiError(response.status, payload.detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function formatDate(value: string, includeTime = false) {
  if (!value) return "—";
  const dateValue = new Date(value);
  if (Number.isNaN(dateValue.getTime())) return value;
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(dateValue);
}

function shortName(name: string, max = 31) {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

function collectionSlug(value: string) {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

function fileIcon(extension: string) {
  if (extension === "md") return <FileCode2 size={15} />;
  if (extension === "pdf") return <FileText size={15} />;
  return <File size={15} />;
}

function ExpiryBadge({ item }: { item: DocumentSummary }) {
  if (!item.valid_until) {
    return <span className="status-badge status-valid">Gültig</span>;
  }
  const status = item.expiry_status === "expired" ? "critical" : item.expiry_status;
  const label = formatDate(item.valid_until);
  const detail = item.expiry_status === "expired"
    ? "Abgelaufen"
    : `${item.days_remaining} Tage verbleibend`;
  return (
    <span className={`status-badge status-${status}`} title={detail}>
      {label}
    </span>
  );
}

function MarkdownPreview({ content }: { content: string }) {
  const lines = content.replace(/^---[\s\S]*?---\s*/m, "").split(/\r?\n/);
  const nodes: ReactNode[] = [];
  let code: string[] = [];
  let inCode = false;
  lines.forEach((line, index) => {
    if (line.startsWith("```")) {
      if (inCode) {
        nodes.push(<pre key={`code-${index}`}>{code.join("\n")}</pre>);
        code = [];
      }
      inCode = !inCode;
      return;
    }
    if (inCode) {
      code.push(line);
      return;
    }
    if (line.startsWith("# ")) nodes.push(<h1 key={index}>{line.slice(2)}</h1>);
    else if (line.startsWith("## ")) nodes.push(<h2 key={index}>{line.slice(3)}</h2>);
    else if (line.startsWith("### ")) nodes.push(<h3 key={index}>{line.slice(4)}</h3>);
    else if (/^[-*]\s/.test(line)) nodes.push(<li key={index}>{line.slice(2)}</li>);
    else if (line.startsWith("|")) nodes.push(<code key={index} className="table-line">{line}</code>);
    else if (line.trim()) nodes.push(<p key={index}>{line}</p>);
  });
  return <div className="markdown-preview">{nodes}</div>;
}

export default function VectorAdmin() {
  const isLocal = typeof window !== "undefined" && window.location.hostname === "localhost";
  const [collections, setCollections] = useState<Collection[]>([]);
  const [activeCollection, setActiveCollection] = useState("kahleallgemein");
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selected, setSelected] = useState<DocumentDetail | null>(null);
  const [editorValue, setEditorValue] = useState("");
  const [activeTab, setActiveTab] = useState<Tab>("markdown");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveTarget, setMoveTarget] = useState("kahlekontext");
  const [movePath, setMovePath] = useState("");
  const uploadRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createLabel, setCreateLabel] = useState("");
  const [createId, setCreateId] = useState("");
  const [creating, setCreating] = useState(false);
  const [manageCollection, setManageCollection] = useState<Collection | null>(null);
  const [manageLabel, setManageLabel] = useState("");
  const [collectionSaving, setCollectionSaving] = useState(false);
  const [collectionDeleteOpen, setCollectionDeleteOpen] = useState(false);
  const [collectionDeleteConfirm, setCollectionDeleteConfirm] = useState("");
  const [collectionDeleting, setCollectionDeleting] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);
  const [trashedCollections, setTrashedCollections] = useState<TrashedCollection[]>([]);
  const [trashLoading, setTrashLoading] = useState(false);
  const [trashBusyId, setTrashBusyId] = useState("");
  const [purgeTarget, setPurgeTarget] = useState<TrashedCollection | null>(null);
  const [purgeConfirm, setPurgeConfirm] = useState("");
  const [unlockReady, setUnlockReady] = useState(false);
  const [unlockOpen, setUnlockOpen] = useState(false);
  const [unlockCode, setUnlockCode] = useState("");
  const [unlockError, setUnlockError] = useState("");
  const [unlocking, setUnlocking] = useState(false);

  const showMessage = useCallback((text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage(""), 3500);
  }, []);

  const loadDocument = useCallback(
    async (item: DocumentSummary) => {
      setActiveTab(item.extension === "md" ? "markdown" : "preview");
      setChunks([]);
      setVersions([]);
      try {
        if (isLocal && collections === demoCollections) throw new Error("demo");
        const detail = await api<DocumentDetail>(
          `/collections/${encodeURIComponent(item.collection)}/documents/${item.path
            .split("/")
            .map(encodeURIComponent)
            .join("/")}`,
        );
        setSelected(detail);
        setEditorValue(detail.content);
      } catch {
        const detail: DocumentDetail = {
          ...item,
          editable: item.extension === "md",
          content: item.extension === "md" ? demoMarkdown : "",
          preview:
            item.extension === "md"
              ? demoMarkdown
              : "Vorschau des extrahierten Dokumentinhalts. Binärdateien werden über einen erneuten Upload ersetzt.",
        };
        setSelected(detail);
        setEditorValue(detail.content);
      }
    },
    [collections, isLocal],
  );

  const loadDocuments = useCallback(
    async (collection: string) => {
      setLoading(true);
      try {
        const payload = await api<{ documents: DocumentSummary[] }>(
          `/collections/${encodeURIComponent(collection)}/documents`,
        );
        setDocuments(payload.documents);
        if (payload.documents.length) await loadDocument(payload.documents[0]);
        else setSelected(null);
      } catch (error) {
        if (isLocal) {
          const localDocs = demoDocuments.filter((item) => item.collection === collection);
          setDocuments(localDocs);
          if (localDocs.length) await loadDocument(localDocs[0]);
        } else {
          setDocuments([]);
          setSelected(null);
          showMessage(error instanceof Error ? error.message : "Daten konnten nicht geladen werden.");
        }
      } finally {
        setLoading(false);
      }
    },
    [isLocal, loadDocument, showMessage],
  );

  const loadCollections = useCallback(async () => {
    try {
      const payload = await api<{ collections: Collection[] }>("/collections");
      setCollections(payload.collections);
      return payload.collections;
    } catch {
      if (isLocal) setCollections(demoCollections);
      return isLocal ? demoCollections : [];
    }
  }, [isLocal]);

  const checkUnlock = useCallback(async () => {
    if (isLocal) {
      setUnlockReady(true);
      setUnlockOpen(false);
      await loadCollections();
      return;
    }
    try {
      const status = await api<UnlockStatus>("/unlock/status");
      setUnlockReady(status.unlocked);
      setUnlockOpen(!status.unlocked);
      setUnlockError(status.enabled ? "" : "Die Zusatzsperre ist auf dem Server noch nicht konfiguriert.");
      if (status.unlocked) await loadCollections();
      else setLoading(false);
    } catch (error) {
      setUnlockReady(false);
      setUnlockOpen(true);
      setLoading(false);
      setUnlockError(error instanceof Error ? error.message : "Sicherheitsstatus konnte nicht geladen werden.");
    }
  }, [isLocal, loadCollections]);

  useEffect(() => {
    const onLocked = () => {
      setUnlockReady(false);
      setUnlockOpen(true);
      setUnlockCode("");
      setUnlockError("Die Sicherheitsfreigabe ist abgelaufen. Bitte Code erneut eingeben.");
    };
    window.addEventListener("kahle-vector-locked", onLocked);
    const timer = window.setTimeout(() => void checkUnlock(), 0);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("kahle-vector-locked", onLocked);
    };
  }, [checkUnlock]);

  useEffect(() => {
    if (!unlockReady) return;
    const timer = window.setTimeout(() => {
      void loadDocuments(activeCollection);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [activeCollection, loadDocuments, unlockReady]);

  const submitUnlock = async (event: FormEvent) => {
    event.preventDefault();
    if (!unlockCode.trim() || unlocking) return;
    setUnlocking(true);
    setUnlockError("");
    try {
      await api<{ ok: boolean; unlocked: boolean }>("/unlock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: unlockCode }),
      });
      setUnlockCode("");
      setUnlockOpen(false);
      setUnlockReady(true);
      await loadCollections();
    } catch (error) {
      if (error instanceof ApiError && error.status === 429) {
        setUnlockError("Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.");
      } else if (error instanceof ApiError && error.status === 401) {
        setUnlockError("Der eingegebene Sicherheitscode ist nicht korrekt.");
      } else {
        setUnlockError(error instanceof Error ? error.message : "Freigabe fehlgeschlagen.");
      }
    } finally {
      setUnlocking(false);
    }
  };

  const lockDashboard = async () => {
    try {
      await api<{ ok: boolean }>("/lock", { method: "POST" });
    } finally {
      setUnlockReady(false);
      setUnlockOpen(true);
      setUnlockCode("");
      setUnlockError("");
      setCollections([]);
      setDocuments([]);
      setSelected(null);
    }
  };

  const visibleDocuments = useMemo(() => {
    return documents.filter((item) => {
      if (filter === "expiry" && !["critical", "warning", "expired"].includes(item.expiry_status))
        return false;
      if (filter !== "all" && filter !== "expiry" && item.extension !== filter) return false;
      const text = `${item.name} ${item.title} ${item.owner} ${item.tags.join(" ")}`.toLowerCase();
      return !query || text.includes(query.toLowerCase());
    });
  }, [documents, filter, query]);

  const availableMoveTargets = useMemo(
    () => collections.filter((collection) => collection.id !== selected?.collection),
    [collections, selected?.collection],
  );

  const openMoveDialog = () => {
    if (!selected) return;
    const firstTarget = collections.find((collection) => collection.id !== selected.collection);
    if (!firstTarget) {
      showMessage("Zum Verschieben wird eine zweite Knowledge Base benötigt.");
      return;
    }
    setMoveTarget(firstTarget.id);
    setMovePath(selected.path);
    setMoveOpen(true);
  };

  const selectCollection = (id: string) => {
    setActiveCollection(id);
    setSidebarOpen(false);
    setFilter("all");
    setQuery("");
  };

  const save = async () => {
    if (!selected?.editable) return;
    setSaving(true);
    try {
      const result = await api<{ reindex?: { ok?: boolean } }>(`/collections/${selected.collection}/documents/${selected.path}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: editorValue }),
      });
      showMessage(result.reindex?.ok ? "Gespeichert und sofort neu indexiert." : "Gespeichert. Neuindexierung wartet auf den automatischen Lauf.");
      await loadDocuments(selected.collection);
    } catch (error) {
      if (isLocal) showMessage("Vorschau: Speichern & Neuindexieren simuliert.");
      else showMessage(error instanceof Error ? error.message : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    let uploaded = 0;
    try {
      for (const file of files) {
        const form = new FormData();
        form.set("collection", activeCollection);
        form.set("target_path", file.name);
        form.set("file", file);
        await api("/upload", { method: "POST", body: form });
        uploaded += 1;
      }
      showMessage(uploaded === 1 ? `${files[0].name} wurde hochgeladen.` : `${uploaded} Dateien wurden hochgeladen.`);
      await loadDocuments(activeCollection);
      await loadCollections();
    } catch (error) {
      showMessage(isLocal ? "Vorschau: Upload simuliert." : String(error));
    } finally {
      setUploading(false);
    }
  };

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    await uploadFiles(Array.from(event.target.files || []));
    event.target.value = "";
  };

  const onDragEnter = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    dragDepth.current += 1;
    setDragActive(true);
  };

  const onDragLeave = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragActive(false);
  };

  const onDrop = async (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    dragDepth.current = 0;
    setDragActive(false);
    await uploadFiles(Array.from(event.dataTransfer.files || []));
  };

  const createCollection = async () => {
    const id = collectionSlug(createId || createLabel);
    const label = createLabel.trim();
    if (id.length < 2 || label.length < 2) {
      showMessage("Bitte Name und technische ID der Knowledge Base prüfen.");
      return;
    }
    setCreating(true);
    try {
      await api("/collections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, label }),
      });
      const updated = await loadCollections();
      if (updated.some((item) => item.id === id)) setActiveCollection(id);
      setCreateOpen(false);
      setCreateLabel("");
      setCreateId("");
      showMessage(`${label} wurde angelegt und für die Indexierung registriert.`);
    } catch (error) {
      showMessage(String(error));
    } finally {
      setCreating(false);
    }
  };
  const openCollectionManager = (collection: Collection) => {
    setManageCollection(collection);
    setManageLabel(collection.label);
    setCollectionDeleteOpen(false);
    setCollectionDeleteConfirm("");
  };

  const updateCollection = async () => {
    if (!manageCollection || manageLabel.trim().length < 2) return;
    setCollectionSaving(true);
    try {
      await api(`/collections/${encodeURIComponent(manageCollection.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: manageLabel.trim() }),
      });
      await loadCollections();
      setManageCollection(null);
      showMessage("Anzeigename der Knowledge Base wurde aktualisiert.");
    } catch (error) {
      showMessage(String(error));
    } finally {
      setCollectionSaving(false);
    }
  };

  const openCollectionDelete = () => {
    if (!manageCollection?.deletable) return;
    setCollectionDeleteConfirm("");
    setCollectionDeleteOpen(true);
  };

  const deleteCollection = async () => {
    if (!manageCollection || collectionDeleteConfirm.trim() !== manageCollection.id) return;
    setCollectionDeleting(true);
    try {
      await api(`/collections/${encodeURIComponent(manageCollection.id)}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_id: collectionDeleteConfirm.trim() }),
      });
      const remaining = await loadCollections();
      const next = remaining.find((item) => item.id !== manageCollection.id);
      setCollectionDeleteOpen(false);
      setManageCollection(null);
      setCollectionDeleteConfirm("");
      setSelected(null);
      setDocuments([]);
      if (next) setActiveCollection(next.id);
      showMessage("Knowledge Base wurde für 30 Tage in den Papierkorb verschoben.");
    } catch (error) {
      showMessage(String(error));
    } finally {
      setCollectionDeleting(false);
    }
  };
  const loadTrash = async () => {
    setTrashLoading(true);
    try {
      const payload = await api<{ collections: TrashedCollection[] }>("/trash/collections");
      setTrashedCollections(payload.collections);
    } catch (error) {
      showMessage(String(error));
    } finally {
      setTrashLoading(false);
    }
  };

  const openTrash = async () => {
    setTrashOpen(true);
    await loadTrash();
  };

  const restoreCollection = async (item: TrashedCollection) => {
    setTrashBusyId(item.archive_id);
    try {
      const payload = await api<{ collection: { id: string } }>(
        `/trash/collections/${encodeURIComponent(item.archive_id)}/restore`,
        { method: "POST" },
      );
      await Promise.all([loadCollections(), loadTrash()]);
      setActiveCollection(payload.collection.id);
      showMessage(`${item.label} wurde wiederhergestellt und wird neu indexiert.`);
    } catch (error) {
      showMessage(String(error));
    } finally {
      setTrashBusyId("");
    }
  };

  const purgeCollection = async () => {
    if (!purgeTarget || purgeConfirm.trim() !== purgeTarget.collection) return;
    setTrashBusyId(purgeTarget.archive_id);
    try {
      await api(`/trash/collections/${encodeURIComponent(purgeTarget.archive_id)}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_id: purgeConfirm.trim() }),
      });
      setPurgeTarget(null);
      setPurgeConfirm("");
      await loadTrash();
      showMessage(`${purgeTarget.label} wurde endgültig gelöscht.`);
    } catch (error) {
      showMessage(String(error));
    } finally {
      setTrashBusyId("");
    }
  };
  const remove = async () => {
    if (!selected) return;
    try {
      await api(`/collections/${selected.collection}/documents/${selected.path}`, {
        method: "DELETE",
      });
      setConfirmDelete(false);
      showMessage("Datei wurde wiederherstellbar in den Papierkorb verschoben.");
      await loadDocuments(selected.collection);
    } catch (error) {
      if (isLocal) {
        setDocuments((items) => items.filter((item) => item.path !== selected.path));
        setSelected(null);
        setConfirmDelete(false);
        showMessage("Vorschau: Datei in den Papierkorb verschoben.");
      } else showMessage(String(error));
    }
  };

  const move = async () => {
    if (!selected) return;
    try {
      await api(`/collections/${selected.collection}/documents/${selected.path}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_collection: moveTarget, target_path: movePath }),
      });
      setMoveOpen(false);
      showMessage("Datei wurde verschoben; der Index wird aktualisiert.");
      await loadDocuments(activeCollection);
    } catch (error) {
      if (isLocal) {
        setMoveOpen(false);
        showMessage("Vorschau: Verschieben simuliert.");
      } else showMessage(String(error));
    }
  };

  const changeTab = async (tab: Tab) => {
    setActiveTab(tab);
    if (!selected) return;
    const encodedPath = selected.path.split("/").map(encodeURIComponent).join("/");
    if (tab === "chunks" && !chunks.length) {
      try {
        const payload = await api<{ chunks: Chunk[] }>(
          `/collections/${selected.collection}/chunks/${encodedPath}`,
        );
        setChunks(payload.chunks);
      } catch {
        if (isLocal)
          setChunks(
            demoMarkdown
              .split("\n\n")
              .filter(Boolean)
              .slice(0, 6)
              .map((content, index) => ({ id: String(index), index, content })),
          );
      }
    }
    if (tab === "versions" && !versions.length) {
      try {
        const payload = await api<{ versions: Version[] }>(
          `/collections/${selected.collection}/versions/${encodedPath}`,
        );
        setVersions(payload.versions);
      } catch {
        if (isLocal)
          setVersions([
            {
              id: "demo-1",
              action: "save",
              actor: "M. Kahle",
              created_at: "2026-07-24T09:42:00+02:00",
              size: 6412,
              sha256: "d3dcb21e",
            },
          ]);
      }
    }
  };

  const semanticSearch = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    try {
      const payload = await api<{ results: Array<{ collection: string; path: string }> }>(
        `/search?query=${encodeURIComponent(query)}&limit=20`,
      );
      const grouped = new Map(payload.results.map((result) => [`${result.collection}/${result.path}`, result]));
      const matches = documents.filter((item) => grouped.has(`${item.collection}/${item.path}`));
      if (matches.length) {
        setDocuments(matches);
        await loadDocument(matches[0]);
      } else showMessage("Keine semantischen Treffer gefunden.");
    } catch {
      if (isLocal) showMessage("Lokale Vorschau nutzt die Dateifilterung.");
    }
  };

  const activeCollectionData = collections.find((item) => item.id === activeCollection);
  const dirty = Boolean(selected?.editable && editorValue !== selected.content);

  return (
    <div className="vector-app">
      <header className="topbar">
        <button className="mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Navigation öffnen">
          <Menu size={20} />
        </button>
        <div className="brand">
          <span>KAHLE</span><i>/</i><strong>VECTOR</strong>
        </div>
        <span className="product-name">Knowledge Management</span>
        <form className="global-search" onSubmit={semanticSearch}>
          <Search size={20} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Semantische Suche über alle Bases"
            aria-label="Semantische Suche"
          />
          {query && (
            <button type="button" onClick={() => setQuery("")} aria-label="Suche löschen">
              <X size={16} />
            </button>
          )}
        </form>
        {unlockReady && !isLocal && (
          <button className="top-lock" onClick={() => void lockDashboard()} title="Dashboard jetzt sperren">
            <ShieldCheck size={18} /> Sperren
          </button>
        )}
        <input ref={uploadRef} type="file" hidden multiple onChange={upload} accept=".md,.txt,.csv,.pdf,.docx" />
        <button className="primary top-upload" disabled={uploading} onClick={() => uploadRef.current?.click()}>
          <Upload size={19} /> Datei hochladen
        </button>
      </header>

      <main className="workspace">
        <aside className={`bases-panel ${sidebarOpen ? "is-open" : ""}`}>
          <div className="mobile-panel-head">
            <span>Knowledge Bases</span>
            <button onClick={() => setSidebarOpen(false)}><X size={18} /></button>
          </div>
          <p className="eyebrow">Knowledge Bases</p>
          <nav>
            {collections.map((collection) => (
              <div className="base-row" key={collection.id}>
                <button
                  className={`base-select ${collection.id === activeCollection ? "active" : ""}`}
                  onClick={() => selectCollection(collection.id)}
                >
                  <Database size={21} />
                  <span>{collection.label}</span>
                  <small>{collection.files}</small>
                  <ChevronRight className="mobile-chevron" size={15} />
                </button>
                <button
                  className="base-manage"
                  aria-label={`${collection.label} verwalten`}
                  title="Knowledge Base bearbeiten oder löschen"
                  onClick={() => openCollectionManager(collection)}
                >
                  <Settings2 size={16} />
                </button>
              </div>
            ))}
          </nav>
          <div className="base-tools">
            <button className="new-base" onClick={() => setCreateOpen(true)}>
              <Plus size={20} /> Neue Knowledge Base
            </button>
            <button className="trash-base" onClick={() => void openTrash()}>
              <Trash2 size={18} /> Papierkorb
            </button>
          </div>
          <div className="index-foot">
            <span>Letzte Indexierung</span>
            <strong>{formatDate(activeCollectionData?.last_indexed_at || "", true)}</strong>
            <em><ShieldCheck size={14} /> Qdrant verbunden</em>
          </div>
        </aside>

        <section
          className={`documents-panel ${dragActive ? "is-dragging" : ""}`}
          onDragEnter={onDragEnter}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        >
          {dragActive && (
            <div className="drop-overlay"><Upload size={34} /><strong>Dateien hier ablegen</strong><span>Upload nach {activeCollectionData?.label}</span></div>
          )}
          <div className="panel-title">
            <div>
              <p>{activeCollectionData?.label || "Knowledge Base"}</p>
              <span>{documents.length} Dateien</span>
            </div>
            <button className="icon-button" onClick={() => loadDocuments(activeCollection)} title="Aktualisieren">
              <RefreshCw size={17} />
            </button>
          </div>
          <div className="filters">
            {[
              ["all", "Alle"],
              ["md", "MD"],
              ["pdf", "PDF"],
              ["docx", "DOCX"],
              ["expiry", "Ablauf"],
            ].map(([value, label]) => (
              <button
                key={value}
                className={filter === value ? (value === "expiry" ? "active expiry" : "active") : value === "expiry" ? "expiry" : ""}
                onClick={() => setFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="document-list">
            {loading && (
              <div className="empty-state"><LoaderCircle className="spin" /> Dateien werden geladen …</div>
            )}
            {!loading && !visibleDocuments.length && (
              <div className="empty-state"><FileText /> Keine passenden Dateien gefunden.</div>
            )}
            {!loading &&
              visibleDocuments.map((item) => (
                <button
                  className={`document-row ${selected?.path === item.path && selected.collection === item.collection ? "selected" : ""}`}
                  key={`${item.collection}/${item.path}`}
                  onClick={() => loadDocument(item)}
                >
                  <span className={`file-type type-${item.extension}`}>
                    {fileIcon(item.extension)} {item.extension.toUpperCase()}
                  </span>
                  <span className="document-copy">
                    <strong title={item.name}>{shortName(item.name)}</strong>
                    <small>{item.chunks} Chunks · {formatDate(item.modified_at)}</small>
                  </span>
                  <ExpiryBadge item={item} />
                </button>
              ))}
          </div>
        </section>

        <section className="detail-panel">
          {!selected ? (
            <div className="detail-empty">
              <Database size={34} />
              <h2>Dokument auswählen</h2>
              <p>Wähle links eine Knowledge Base und anschließend eine Datei aus.</p>
            </div>
          ) : (
            <>
              <div className="detail-head">
                <div className="detail-title">
                  <span className={`file-type type-${selected.extension}`}>
                    {selected.extension.toUpperCase()}
                  </span>
                  <div>
                    <h1>{selected.name}</h1>
                    <p>
                      {activeCollectionData?.label} · {selected.chunks} Chunks · {Math.max(1, Math.round(selected.size / 4)).toLocaleString("de-DE")} Tokens
                    </p>
                    <small>
                      geändert {formatDate(selected.modified_at)} · Index{" "}
                      <b className={`index-${selected.index_status}`}>{selected.index_status === "current" ? "aktuell" : selected.index_status}</b>
                    </small>
                  </div>
                </div>
                <div className="detail-actions">
                  <button onClick={openMoveDialog}>
                    <FolderInput size={18} /> Verschieben
                  </button>
                  <button className="danger" onClick={() => setConfirmDelete(true)}>
                    <Trash2 size={18} /> Löschen
                  </button>
                  <button className="primary" disabled={!selected.editable || saving || (!dirty && !isLocal)} onClick={save}>
                    {saving ? <LoaderCircle className="spin" size={18} /> : <Check size={19} />}
                    Speichern & neu indexieren
                  </button>
                </div>
              </div>

              <div className="metadata-strip">
                <div><span>Gültig bis</span><strong className={selected.expiry_status === "critical" || selected.expiry_status === "expired" ? "critical-text" : selected.expiry_status === "warning" ? "warning-text" : ""}>{selected.valid_until ? formatDate(selected.valid_until) : "Unbegrenzt"}</strong></div>
                <div><span>Owner</span><strong>{selected.owner || "Nicht zugewiesen"}</strong></div>
                <div><span>Standorte</span><strong>{selected.locations.length ? selected.locations.join(", ") : "Alle"}</strong></div>
                <div><span>Tags</span><strong>{selected.tags.length ? selected.tags.join(", ") : "—"}</strong></div>
              </div>

              <div className="tabs" role="tablist">
                {[
                  ["markdown", selected.editable ? "Markdown" : "Dateiinfo"],
                  ["preview", "Vorschau"],
                  ["chunks", `Chunks (${selected.chunks})`],
                  ["versions", "Versionen"],
                ].map(([value, label]) => (
                  <button key={value} className={activeTab === value ? "active" : ""} onClick={() => changeTab(value as Tab)}>
                    {label}
                  </button>
                ))}
              </div>

              <div className="tab-content">
                {activeTab === "markdown" && selected.editable && (
                  <textarea
                    className="editor"
                    value={editorValue}
                    onChange={(event) => setEditorValue(event.target.value)}
                    spellCheck={false}
                    aria-label="Dokumentinhalt"
                  />
                )}
                {activeTab === "markdown" && !selected.editable && (
                  <div className="binary-info">
                    <FileText size={30} />
                    <h3>{selected.extension.toUpperCase()}-Datei</h3>
                    <p>Binärdateien werden in der Vorschau extrahiert angezeigt. Zum Aktualisieren lade eine neue Datei mit demselben Pfad hoch.</p>
                    <button className="primary" onClick={() => uploadRef.current?.click()}><Upload size={17} /> Datei ersetzen</button>
                  </div>
                )}
                {activeTab === "preview" && <MarkdownPreview content={selected.preview || editorValue} />}
                {activeTab === "chunks" && (
                  <div className="chunks-list">
                    {!chunks.length ? <div className="empty-state">Keine indexierten Chunks vorhanden.</div> :
                      chunks.map((chunk) => (
                        <article key={chunk.id}>
                          <span>Chunk {chunk.index + 1}</span>
                          <p>{chunk.content}</p>
                        </article>
                      ))}
                  </div>
                )}
                {activeTab === "versions" && (
                  <div className="versions-list">
                    {!versions.length ? (
                      <div className="empty-state"><History /> Noch keine frühere Version vorhanden.</div>
                    ) : (
                      versions.map((version) => (
                        <article key={version.id}>
                          <History size={18} />
                          <div><strong>{formatDate(version.created_at, true)}</strong><small>{version.action} · {version.actor}</small></div>
                          <span>{Math.round(version.size / 1024)} KB</span>
                          <button title="Version wiederherstellen" onClick={() => showMessage("Wiederherstellung wird nach Bestätigung ausgeführt.")}><ArchiveRestore size={17} /></button>
                        </article>
                      ))
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      </main>

      {sidebarOpen && <button className="backdrop" onClick={() => setSidebarOpen(false)} aria-label="Navigation schließen" />}

      {confirmDelete && selected && (
        <div className="modal-backdrop">
          <div className="modal">
            <CircleAlert className="modal-warning" size={28} />
            <h2>Datei löschen?</h2>
            <p><strong>{selected.name}</strong> wird aus der Knowledge Base entfernt und wiederherstellbar in den Papierkorb verschoben.</p>
            <div><button onClick={() => setConfirmDelete(false)}>Abbrechen</button><button className="danger solid" onClick={remove}><Trash2 size={17} /> Löschen</button></div>
          </div>
        </div>
      )}

      {moveOpen && selected && (
        <div className="modal-backdrop">
          <div className="modal move-modal">
            <MoveRight className="modal-primary" size={28} />
            <h2>Datei verschieben</h2>
            <label>Knowledge Base<select value={moveTarget} onChange={(event) => setMoveTarget(event.target.value)}>{availableMoveTargets.map((collection) => <option key={collection.id} value={collection.id}>{collection.label}</option>)}</select></label>
            <label>Zielpfad<input value={movePath} onChange={(event) => setMovePath(event.target.value)} /></label>
            <div><button onClick={() => setMoveOpen(false)}>Abbrechen</button><button className="primary" disabled={!moveTarget || moveTarget === selected.collection} onClick={move}><MoveRight size={17} /> Verschieben</button></div>
          </div>
        </div>
      )}

      {manageCollection && !collectionDeleteOpen && (
        <div className="modal-backdrop">
          <div className="modal move-modal collection-modal">
            <Settings2 className="modal-primary" size={28} />
            <h2>Knowledge Base bearbeiten</h2>
            <p>Der Anzeigename kann jederzeit geändert werden. Die technische ID bleibt stabil, damit Quellen und Indexeinträge gültig bleiben.</p>
            <label>Anzeigename<input value={manageLabel} onChange={(event) => setManageLabel(event.target.value)} /></label>
            <label>Technische ID<input value={manageCollection.id} readOnly /></label>
            {!manageCollection.deletable && <p className="protected-note">Diese System-Base kann umbenannt, aber nicht gelöscht werden.</p>}
            <div className="collection-modal-actions">
              {manageCollection.deletable ? <button className="danger" onClick={openCollectionDelete}><Trash2 size={17} /> Knowledge Base löschen</button> : <span />}
              <span className="modal-action-group"><button onClick={() => setManageCollection(null)}>Abbrechen</button><button className="primary" disabled={collectionSaving || manageLabel.trim().length < 2 || manageLabel.trim() === manageCollection.label} onClick={updateCollection}>{collectionSaving ? <LoaderCircle className="spin" size={17} /> : <Check size={17} />} Speichern</button></span>
            </div>
          </div>
        </div>
      )}

      {manageCollection && collectionDeleteOpen && (
        <div className="modal-backdrop">
          <div className="modal move-modal">
            <CircleAlert className="modal-warning" size={28} />
            <h2>Knowledge Base löschen?</h2>
            <p><strong>{manageCollection.label}</strong> mit {manageCollection.files} Datei(en) wird aus der aktiven Wissensbasis entfernt. Der Quellenordner wird zur Wiederherstellung archiviert; die Qdrant-Collection wird gelöscht.</p>
            <label>Zur Bestätigung technische ID eingeben<input value={collectionDeleteConfirm} onChange={(event) => setCollectionDeleteConfirm(event.target.value)} placeholder={manageCollection.id} autoFocus /></label>
            <div><button onClick={() => setCollectionDeleteOpen(false)}>Zurück</button><button className="danger solid" disabled={collectionDeleting || collectionDeleteConfirm.trim() !== manageCollection.id} onClick={deleteCollection}>{collectionDeleting ? <LoaderCircle className="spin" size={17} /> : <Trash2 size={17} />} In Papierkorb verschieben</button></div>
          </div>
        </div>
      )}
      {trashOpen && !purgeTarget && (
        <div className="modal-backdrop">
          <div className="modal trash-modal">
            <Trash2 className="modal-primary" size={28} />
            <h2>Papierkorb</h2>
            <p>Gelöschte Knowledge Bases bleiben 30 Tage wiederherstellbar. Danach entfernt der tägliche Lauf um 10:30 Uhr die Dateien endgültig.</p>
            <div className="trash-list">
              {trashLoading ? (
                <div className="trash-empty"><LoaderCircle className="spin" size={22} /> Papierkorb wird geladen …</div>
              ) : !trashedCollections.length ? (
                <div className="trash-empty">Der Papierkorb ist leer.</div>
              ) : trashedCollections.map((item) => (
                <article className="trash-row" key={item.archive_id}>
                  <div>
                    <strong>{item.label}</strong>
                    <small>{item.files} Datei(en) · ID: {item.collection}</small>
                    <span>Endgültige Löschung: {formatDate(item.purge_at, true)}</span>
                  </div>
                  <button disabled={trashBusyId === item.archive_id} onClick={() => void restoreCollection(item)} title="Knowledge Base wiederherstellen">
                    {trashBusyId === item.archive_id ? <LoaderCircle className="spin" size={17} /> : <ArchiveRestore size={17} />} Wiederherstellen
                  </button>
                  <button className="danger icon-danger" disabled={trashBusyId === item.archive_id} onClick={() => { setPurgeTarget(item); setPurgeConfirm(""); }} title="Jetzt endgültig löschen" aria-label={`${item.label} endgültig löschen`}>
                    <Trash2 size={17} />
                  </button>
                </article>
              ))}
            </div>
            <div><button onClick={() => setTrashOpen(false)}>Schließen</button></div>
          </div>
        </div>
      )}

      {trashOpen && purgeTarget && (
        <div className="modal-backdrop">
          <div className="modal move-modal">
            <CircleAlert className="modal-warning" size={28} />
            <h2>Jetzt endgültig löschen?</h2>
            <p><strong>{purgeTarget.label}</strong> und alle {purgeTarget.files} Datei(en) werden unwiderruflich aus dem Papierkorb entfernt.</p>
            <label>Zur Bestätigung technische ID eingeben<input value={purgeConfirm} onChange={(event) => setPurgeConfirm(event.target.value)} placeholder={purgeTarget.collection} autoFocus /></label>
            <div><button onClick={() => { setPurgeTarget(null); setPurgeConfirm(""); }}>Zurück</button><button className="danger solid" disabled={trashBusyId === purgeTarget.archive_id || purgeConfirm.trim() !== purgeTarget.collection} onClick={purgeCollection}>{trashBusyId === purgeTarget.archive_id ? <LoaderCircle className="spin" size={17} /> : <Trash2 size={17} />} Endgültig löschen</button></div>
          </div>
        </div>
      )}
      {createOpen && (
        <div className="modal-backdrop">
          <div className="modal move-modal">
            <Database className="modal-primary" size={28} />
            <h2>Neue Knowledge Base</h2>
            <p>Die Base wird als eigener Quellenordner und als Qdrant-Collection angelegt. Vinci nimmt sie anschließend automatisch in die RAG-Suche auf.</p>
            <label>Anzeigename<input value={createLabel} onChange={(event) => { const value = event.target.value; setCreateLabel(value); if (!createId || createId === collectionSlug(createLabel)) setCreateId(collectionSlug(value)); }} placeholder="z. B. Service & Werkstatt" /></label>
            <label>Technische ID<input value={createId} onChange={(event) => setCreateId(collectionSlug(event.target.value))} placeholder="service-werkstatt" /></label>
            <div><button onClick={() => setCreateOpen(false)}>Abbrechen</button><button className="primary" disabled={creating || createLabel.trim().length < 2 || collectionSlug(createId).length < 2} onClick={createCollection}>{creating ? <LoaderCircle className="spin" size={17} /> : <Plus size={17} />} Knowledge Base anlegen</button></div>
          </div>
        </div>
      )}

      {unlockOpen && (
        <div className="modal-backdrop unlock-backdrop" role="presentation">
          <form className="modal unlock-modal" onSubmit={submitUnlock} aria-labelledby="unlock-title">
            <div className="unlock-symbol"><ShieldCheck size={30} /></div>
            <p className="unlock-eyebrow">Zusätzliche Sicherheitsfreigabe</p>
            <h2 id="unlock-title">KAHLE/VECTOR entsperren</h2>
            <p>Du bist als Administrator angemeldet. Gib zusätzlich den Sicherheitscode ein, um die Wissensdatenbank zu verwalten.</p>
            <label htmlFor="vector-unlock-code">Sicherheitscode</label>
            <input
              id="vector-unlock-code"
              type="password"
              value={unlockCode}
              onChange={(event) => setUnlockCode(event.target.value)}
              autoComplete="current-password"
              autoFocus
              disabled={unlocking}
            />
            {unlockError && <div className="unlock-error" role="alert">{unlockError}</div>}
            <div className="unlock-actions">
              <button className="primary" type="submit" disabled={unlocking || unlockCode.trim().length < 8}>
                {unlocking ? <LoaderCircle className="spin" size={17} /> : <ShieldCheck size={17} />}
                Dashboard entsperren
              </button>
            </div>
          </form>
        </div>
      )}

      {message && <div className="toast"><Check size={17} /> {message}</div>}
    </div>
  );
}

