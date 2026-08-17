"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent as ReactClipboardEvent,
  type ReactNode,
} from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileSearch,
  FileUp,
  LayoutDashboard,
  LoaderCircle,
  MessageCircle,
  Send,
  ShieldCheck,
  Users,
  XCircle,
  type LucideIcon,
} from "lucide-react";

const API = "/wissen/api";
type Role = "employee" | "manager" | "admin" | "portal_admin";

const roleLabel = (role: Role) =>
  ({
    employee: "Mitarbeiter",
    manager: "Führungskraft",
    admin: "Admin",
    portal_admin: "Portal-Admin",
  })[role];
type Session = {
  user_id: string;
  email: string;
  display_name: string;
  role: Role;
};
type KB = {
  knowledgebase_id: string;
  slug?: string;
  label: string;
  purpose?: string;
};
type Match = {
  document_id: string;
  title: string;
  level: string;
  knowledgebase_ids: string[];
  version_candidate: boolean;
  has_conflict: boolean;
  match_percent?: number;
  conflict_count?: number;
};
type UploadResult = {
  case_id: string;
  document_id: string;
  status: string;
  requires_admin: boolean;
  owner_confirmation_required?: boolean;
  exact_duplicate_document_id?: string;
  matches: Match[];
  confidentiality: string;
  confidentiality_reason: string;
  conversion_quality?: string;
  conversion_issues?: string[];
  restricted_terms?: string[];
};
type Task = {
  case_id: string;
  title: string;
  original_filename: string;
  status: string;
  target_knowledgebase_id: string;
  target_knowledgebase_label?: string;
  target_knowledgebase_ids?: string[];
  target_knowledgebase_labels?: string[];
  requested_action?: string;
  requires_admin: boolean;
  restricted_terms?: string[];
  contact_name?: string;
  publication_error?: string;
  security_review_finding?: string;
  sanitized_for_review?: boolean;
  duplicate_matches?: {
    document_id: string;
    title: string;
    active_version_id: string;
    relation: "exact_duplicate" | "version_candidate";
    has_conflict: boolean;
    original_url: string;
  }[];
  target_knowledgebase_history?: {
    knowledgebase_ids: string[];
    knowledgebase_labels: string[];
    selected_by_user_id: string;
    selected_by_name: string;
    selected_by_role: string;
    selected_at: string;
  }[];
};
type InquiryParticipant = {
  user_id: string;
  display_name: string;
  email: string;
};
type RestrictedTerm = {
  rule_id: string;
  term: string;
  active: boolean;
  created_by: string;
  created_at: string;
};
type PortalNotification = {
  notification_id: string;
  case_id?: string | null;
  status: string;
  message: string;
  reason?: string;
  created_at: string;
  read_at?: string;
  document_title: string;
};
type PortalUser = {
  user_id: string;
  email: string;
  display_name: string;
  role: Role;
  active: boolean;
  manager_user_id?: string;
};
type UserAccess = {
  knowledgebase_id: string;
  label: string;
  can_read: number | boolean;
  can_upload: number | boolean;
};
type AuditEntry = {
  occurred_at: string;
  actor_user_id: string;
  event_type: string;
  subject_type: string;
  subject_id: string;
  actor_name: string;
  event_label: string;
  subject_label: string;
  details_label: string;
};
type KBOverviewDocument = {
  document_id: string;
  title: string;
  owner_name: string;
  status: string;
  valid_until?: string;
};
type KBOverview = {
  knowledgebase_id: string;
  slug: string;
  label: string;
  purpose: string;
  status: string;
  document_count: number;
  status_counts: Record<string, number>;
  documents: KBOverviewDocument[];
};
type KBChange = {
  request_id: string;
  kind: string;
  knowledgebase_id?: string;
  requested_by: string;
  status: string;
  payload: { label?: string; slug?: string; purpose?: string };
};
type PortalDocument = {
  document_id: string;
  title: string;
  owner_user_id: string;
  active_version_id?: string;
  status?: string;
  valid_until?: string;
  original_url?: string;
  primary_knowledgebase?: { knowledgebase_id: string; label: string } | null;
  additional_knowledgebases: { knowledgebase_id: string; label: string }[];
};
type OwnershipTask = {
  task_id: string;
  document_id: string;
  previous_owner_user_id: string;
  manager_user_id?: string;
  proposed_owner_user_id?: string;
  status: string;
  reason: string;
};
type UploadJob = {
  job_id: string;
  status: string;
  step: string;
  progress: number;
  result?: UploadResult;
  error_code?: string;
};
type DecisionJob = {
  job_id: string;
  case_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  position: number;
  result?: { case?: Task };
  error_code?: string;
};
type DocumentChange = {
  request_id: string;
  document_id: string;
  kind: string;
  reason: string;
  status: string;
};
type Review = {
  case: { case_id: string; title: string };
  markdown: string;
  original_url: string;
  knowledgebases: { knowledgebase_id: string; label: string }[];
};
type Absence = {
  manager_user_id: string;
  delegate_user_id?: string;
  absent_from: string;
  absent_until: string;
  reason: string;
  source?: "manual" | "outlook";
};
type Delegation = {
  manager_user_id: string;
  delegate_user_id: string;
  valid_from?: string | null;
  valid_until?: string | null;
};
type FeedbackContext = {
  question: string;
  answer: string;
  sources: unknown[];
  passages: unknown[];
  runtime: Record<string, unknown>;
  request_id: string;
  document_ids: string[];
  knowledgebase_ids: string[];
  documents: FeedbackDocumentOption[];
  knowledgebases: Knowledgebase[];
};
type FeedbackDocumentOption = {
  document_id: string;
  title: string;
  knowledgebase_ids: string[];
};
type FeedbackOptions = {
  documents: FeedbackDocumentOption[];
  knowledgebases: Knowledgebase[];
};
type QualityDashboard = {
  active_documents?: number;
  expired_documents?: number;
  expiring_within_15_workdays?: number;
  open_feedback?: number;
  open_incidents?: number;
  workflow_quality?: {
    open_approvals?: number;
    average_processing_minutes?: number | null;
    escalations?: number;
    overdue_cases?: number;
    duplicates?: number;
    version_candidates?: number;
    conflicts?: number;
    failed_conversions?: number;
    security_findings?: number;
  };
  mail?: { pending?: number; failed?: number };
  governance?: {
    managers_without_delegate?: number;
    documents_without_active_owner_or_manager?: number;
  };
  retrieval?: {
    requests?: number;
    document_hit_rate_percent?: number | null;
    source_coverage_percent?: number | null;
    unanswered_questions?: number;
    average_latency_ms?: number | null;
    p95_latency_ms?: number | null;
    error_rate_percent?: number | null;
  };
  index?: { ok?: boolean };
  backup?: { last_backup?: string; last_restore_test?: string };
  workflow_cases?: Record<string, number>;
  migration?: Record<string, number>;
};
type QualityIncident = {
  incident_id: string;
  step: string;
  severity?: string;
  created_at: string;
  comment?: string;
  diagnostic_json?: string;
};
type QualityFeedback = {
  feedback_id: string;
  reason: string;
  severity?: string;
  created_at: string;
  comment?: string;
  documents?: { document_id: string; title: string }[];
  knowledgebases?: { knowledgebase_id: string; label: string }[];
  reported_by_name?: string;
  reported_by_user_id?: string;
  question?: string;
  answer?: string;
  screenshot_filename?: string;
  attachments?: { attachment_id: string; original_filename: string; media_type: string; size_bytes: number }[];
};
type QualityCases = {
  incidents: QualityIncident[];
  feedback: QualityFeedback[];
};
type QualityRow = {
  id: string;
  type: string;
  summary: string;
  severity?: string;
  created_at: string;
  comment?: string;
  documents?: { document_id: string; title: string }[];
  knowledgebases?: { knowledgebase_id: string; label: string }[];
  reported_by_name?: string;
  reported_by_user_id?: string;
  question?: string;
  answer?: string;
  screenshot_filename?: string;
  attachments?: { attachment_id: string; original_filename: string; media_type: string; size_bytes: number }[];
  diagnostic_json?: string;
};
type RemovalRequest = {
  request_id: string;
  document_id: string;
  kind: string;
  title?: string;
  reason: string;
  status: string;
};
type TrashItem = {
  document_id: string;
  title?: string;
  reason: string;
  trashed_at: string;
  legal_hold: boolean | number;
  can_delete: boolean;
  delete_eligible_on: string;
};
type Removals = { requests: RemovalRequest[]; trash: TrashItem[]; unread_count?: number };
type MigrationItem = {
  path: string;
  original_path: string;
  markdown_path?: string;
  knowledgebase_slug: string;
  document_id: string;
  version_id: string;
  status: string;
  missing: string[];
  prompt_injection_risk: string;
  conversion_quality: string;
  conversion_issues: string[];
  transition_deadline: string;
  exclusion_reason?: string | null;
  excluded_by?: string | null;
  excluded_at?: string | null;
};
type MigrationTask = {
  task_id: string;
  path: string;
  kind: string;
  status: string;
  details: Record<string, unknown>;
};
type AdminAction = {
  path: string;
  method: string;
  body: Record<string, unknown>;
  returnTab?: string;
};
type NavigationTab = [string, string, LucideIcon];
type ConfirmationRequest = {
  title: string;
  description: string;
  confirmLabel?: string;
  danger?: boolean;
};

const ConfirmationContext = createContext<
  (request: ConfirmationRequest) => Promise<boolean>
>(async () => false);

function useConfirmation() {
  return useContext(ConfirmationContext);
}

function ConfirmationProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<ConfirmationRequest | null>(null);
  const [resolveRequest, setResolveRequest] = useState<
    ((confirmed: boolean) => void) | null
  >(null);
  const confirm = useCallback(
    (next: ConfirmationRequest) =>
      new Promise<boolean>((resolve) => {
        setRequest(next);
        setResolveRequest(() => resolve);
      }),
    [],
  );
  const close = (confirmed: boolean) => {
    resolveRequest?.(confirmed);
    setRequest(null);
    setResolveRequest(null);
  };
  return (
    <ConfirmationContext.Provider value={confirm}>
      {children}
      {request && (
        <div className="wp-confirm-backdrop" role="presentation">
          <section
            className="wp-confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="wp-confirm-title"
            aria-describedby="wp-confirm-description"
          >
            <div className={`wp-confirm-icon ${request.danger ? "danger" : ""}`}>
              <AlertTriangle size={24} />
            </div>
            <div>
              <h2 id="wp-confirm-title">{request.title}</h2>
              <p id="wp-confirm-description">{request.description}</p>
            </div>
            <div className="wp-confirm-actions">
              <button type="button" onClick={() => close(false)}>Abbrechen</button>
              <button
                type="button"
                className={request.danger ? "wp-danger" : "wp-primary"}
                autoFocus
                onClick={() => close(true)}
              >
                {request.confirmLabel || "Bestätigen"}
              </button>
            </div>
          </section>
        </div>
      )}
    </ConfirmationContext.Provider>
  );
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    credentials: "include",
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(body.detail || `request_${response.status}`);
  return body;
}

const statusText: Record<string, string> = {
  pending_employee_decision: "Deine Entscheidung fehlt",
  duplicate_blocked: "Identisches Dokument gefunden",
  pending_manager_approval: "Prüfung durch Führungskraft",
  pending_admin_approval: "Prüfung durch Admin",
  needs_correction: "Aufbereitung prüfen",
  security_blocked: "Sicherheitsprüfung erforderlich",
  ready_to_activate: "Bereit zur Veröffentlichung",
  active: "Aktiv",
  rejected: "Abgelehnt",
  withdrawn: "Verworfen",
  metadata_required: "Angaben fehlen",
  ready_to_stage: "Bereit zur Übernahme",
  quarantine: "Prüfung durch Admin erforderlich",
  staged: "Im Freigabeprozess",
  transition_expired: "Übergangsfrist abgelaufen",
  excluded: "Nicht übernehmen",
  removed: "Nicht mehr abrufbar",
  knowledgebase_archive: "Wissensbereich archiviert",
  knowledgebase_delete: "Wissensbereich gelöscht",
  clarification_requested: "Rückfrage zum Dokument",
};

const RUNNING_UPLOAD_JOB = "running-upload-job";

// PRD 12.3: die fuenf verstaendlichen Verarbeitungsstufen des Backends.
const stepText: Record<string, string> = {
  uploaded: "Datei wird sicher gespeichert",
  security: "Sicherheitsprüfung läuft",
  conversion: "Inhalt wird aufbereitet",
  comparison: "Ähnliche Dokumente werden gesucht",
  completed: "Ergebnis kann geprüft werden",
};

// PRD 15.2 benennt die Risikostufen; "medium" sagt einem Mitarbeiter nichts.
const matchLevelText: Record<string, string> = {
  identical: "Identisch",
  very_high: "Sehr hohe Ähnlichkeit",
  medium: "Mittlere Ähnlichkeit",
  low: "Geringe Ähnlichkeit",
};

const changeKindText: Record<string, string> = {
  create: "Neu anlegen",
  rename: "Umbenennen",
  archive: "Archivieren",
  delete: "Endgültig entfernen",
};

const confidentialityText: Record<string, string> = {
  internal: "Unternehmensweit intern",
  restricted: "Nur freigegebene Bereiche",
  confidential: "Nur ausdrücklich berechtigte Personen",
};

const confidentialityOptions = [
  { value: "internal", label: "Unternehmensweit intern" },
  { value: "restricted", label: "Nur freigegebene Bereiche" },
  { value: "confidential", label: "Nur ausdrücklich berechtigte Personen" },
];

const migrationGapText: Record<string, string> = {
  owner: "Owner",
  rights: "Leserechte",
  confidentiality: "Einstufung",
  authority_type: "Dokumentart",
  authority_level: "Verbindlichkeit",
  scope: "Geltungsbereich",
  knowledgebase: "Ziel-Wissensbereich",
  source_readable: "Dateiberechtigung",
};

const migrationCheckText: Record<string, string> = {
  good: "in Ordnung",
  low: "bitte prüfen",
  failed: "nicht verwendbar",
  pending: "wird bei der Übernahme geprüft",
  none: "kein Hinweis",
  medium: "Adminprüfung erforderlich",
  high: "hohes Risiko",
  critical: "kritisches Risiko",
};

const authorityOptions = [
  {
    level: 1,
    type: "law_or_regulation",
    label: "Gesetz oder regulatorische Vorgabe",
  },
  {
    level: 2,
    type: "manufacturer_or_importer",
    label: "Hersteller- oder Importeursvorgabe",
  },
  {
    level: 3,
    type: "executive_policy",
    label: "Richtlinie der Geschäftsführung",
  },
  { level: 4, type: "department_policy", label: "Bereichsrichtlinie" },
  {
    level: 5,
    type: "process_or_work_instruction",
    label: "Prozess- oder Arbeitsanweisung",
  },
  {
    level: 6,
    type: "information_or_training",
    label: "Informations- oder Schulungsunterlage",
  },
];

// PRD 16.1: Mitarbeitende sehen eine dreistufige Bewertung, keine technischen Details.
const qualityRating: Record<
  string,
  { tone: string; title: string; text: string }
> = {
  good: {
    tone: "ok",
    title: "Alles in Ordnung",
    text: "Der Inhalt wurde vollständig und lesbar übernommen.",
  },
  low: {
    tone: "check",
    title: "Bitte prüfen",
    text: "Einzelne Stellen solltest du dir vor der Freigabe ansehen.",
  },
  failed: {
    tone: "blocked",
    title: "Upload kann so nicht verarbeitet werden",
    text: "Bitte lade das Dokument in einer besser lesbaren Fassung erneut hoch.",
  },
};

// PRD 21.1: Nutzer sehen eine verständliche Meldung, niemals den technischen Fehlercode.
const errorText: Record<string, string> = {
  kahle_microsoft_tenant_required:
    "Dieses Konto gehört nicht zum KAHLE-Verzeichnis. Bitte melde dich mit deinem KAHLE-Konto an.",
  openwebui_login_required:
    "Bitte melde dich zuerst mit deinem Microsoft-Konto an.",
  openwebui_identity_incomplete:
    "Deinem Konto fehlen Angaben. Bitte wende dich an einen Admin.",
  portal_user_inactive:
    "Dein Zugang ist derzeit nicht aktiv. Bitte wende dich an einen Admin.",
  admin_required: "Diese Aktion darf nur ein Admin ausführen.",
  portal_admin_required: "Diese Aktion darf nur ein Portal-Admin ausführen.",
  trash_recovery_period_active:
    "Das Dokument bleibt 30 Tage geschützt und kann bis dahin nur wiederhergestellt werden.",
  confirmation_required:
    "Bitte bestätige diese Aktion im Bestätigungsfenster.",
  no_readable_knowledgebases:
    "Dir ist noch kein Wissensbereich zum Lesen zugeordnet.",
  unsupported_file_type:
    "Dieser Dateityp wird nicht unterstützt. Erlaubt sind PDF, DOCX, XLSX, PPTX, TXT und Markdown.",
  file_too_large: "Die Datei ist zu groß. Erlaubt sind maximal 50 MB.",
  upload_too_large: "Die Datei ist zu groß. Erlaubt sind maximal 50 MB.",
  original_not_available: "Die Originaldatei ist derzeit nicht verfügbar.",
  source_not_available: "Die Quelle ist derzeit nicht verfügbar.",
  document_not_found: "Das Dokument wurde nicht gefunden.",
  qdrant_unavailable:
    "Die Wissenssuche ist gerade nicht erreichbar. Bitte versuche es später erneut.",
  valid_workdays_or_valid_until_required:
    "Bitte gib entweder eine Anzahl Arbeitstage oder ein Datum an.",
  invalid_valid_until: "Das gewählte Datum ist ungültig.",
  valid_until_not_in_future: "Das Datum muss nach dem heutigen Tag liegen.",
  valid_until_has_no_workday: "Bis zu diesem Datum liegt kein Arbeitstag.",
  valid_workdays_out_of_range:
    "Die Gültigkeit darf höchstens 60 Arbeitstage betragen.",
  knowledgebase_must_be_archived_first:
    "Ein Wissensbereich muss zuerst archiviert werden, bevor er endgültig entfernt werden kann.",
  knowledgebase_not_active: "Dieser Wissensbereich ist nicht aktiv.",
  only_active_documents_can_be_published:
    "Weitere Wissensbereiche können erst nach der Freigabe zugeordnet werden.",
  knowledgebase_slug_exists: "Diesen Kurznamen gibt es bereits.",
  knowledgebase_id_required: "Bitte wähle einen Wissensbereich aus.",
  migration_owner_manager_required:
    "Dieser Owner hat noch keine Führungskraft. Bitte ordne ihm zuerst unter Benutzer eine Führungskraft zu.",
  restricted_term_exists: "Dieses Sperrwort ist bereits hinterlegt.",
  restricted_term_length_invalid:
    "Das Sperrwort muss zwischen 2 und 120 Zeichen lang sein.",
  legal_hold_blocks_deletion: "Ein Legal Hold setzt die Löschung aus.",
};

function friendlyError(cause: unknown, fallback: string) {
  const raw = cause instanceof Error ? cause.message : "";
  if (raw === "embedded_executable_content_not_allowed")
    return "Die Datei enthält eingebettete ausführbare Inhalte oder aktive Anhänge und wurde aus Sicherheitsgründen blockiert. Bitte entferne diese Inhalte und lade eine bereinigte Datei erneut hoch.";
  if (raw === "pdf_page_limit_exceeded")
    return "Die PDF-Datei umfasst mehr als 1.000 Seiten. Bitte teile sie in mehrere fachlich sinnvolle Dokumente auf.";
  if (raw === "office_page_limit_exceeded")
    return "Die Office-Datei überschreitet die zulässige Aufbereitungsgröße. Bitte teile sie in mehrere fachlich sinnvolle Dokumente auf.";
  if (/^required_check_unavailable:/.test(raw))
    return "Die Datei wurde aufbereitet, aber die erforderliche Ähnlichkeitsanalyse war nicht erreichbar. Ein technischer Fall wurde automatisch angelegt. Bitte versuche es später erneut.";
  if (raw === "embedding_service_unavailable")
    return "Der Dienst für die automatische Ähnlichkeitsanalyse war nicht erreichbar.";
  if (errorText[raw]) return errorText[raw];
  if (/^request_(401|403)$/.test(raw))
    return "Dafür fehlt dir die Berechtigung.";
  if (raw === "request_404") return "Der Vorgang wurde nicht gefunden.";
  if (/^request_5\d\d$/.test(raw))
    return "Das Portal ist vorübergehend nicht erreichbar. Bitte versuche es in einigen Minuten erneut.";
  return fallback;
}

// Der Dateiname ist fast immer der gewuenschte Titel. Endung entfernen, damit
// niemand ".pdf.docx" abtippen muss.
function titleFromFilename(filename: string) {
  return filename
    .replace(/(\.[a-z0-9]{2,5})+$/i, "")
    .replace(/[_-]+/g, " ")
    .trim();
}

// Warum ein Vorgang bei Admin oder Fuehrungskraft liegt. Ohne diese Angabe
// sieht die entscheidende Person nur, dass etwas wartet, nicht weshalb.
const subjectText: Record<string, string> = {
  user: "Benutzer",
  document: "Dokument",
  document_case: "Vorgang",
  knowledgebase: "Wissensbereich",
  rag_feedback: "Wissensfehler",
};

const reviewReason: Record<string, string> = {
  pending_admin_approval: "Der Fall verlangt eine Adminentscheidung.",
  pending_manager_approval: "Reguläre Freigabe durch die Führungskraft.",
  security_blocked: "Eine Sicherheitsprüfung hat angeschlagen.",
  needs_correction: "Die Aufbereitung muss überprüft werden.",
  duplicate_blocked: "Ein identisches Dokument ist bereits vorhanden.",
  error: "Bei der Verarbeitung ist ein technischer Fehler aufgetreten.",
};

function conversionIssueText(issue: string) {
  const table =
    /table_column_structure_inconsistent:line=(\d+):expected=(\d+):actual=(\d+)/.exec(
      issue,
    );
  if (table)
    return `Tabellenzeile ${table[1]}: ${table[2]} Spalten erwartet, ${table[3]} erkannt.`;
  if (issue === "character_encoding_corrupted")
    return "Zeichenkodierung ist beschädigt.";
  if (issue === "conversion_output_too_short")
    return "Die Konvertierung hat zu wenig verwertbaren Inhalt erzeugt.";
  return issue;
}

function Badge({ status }: { status: string }) {
  const warning = [
    "duplicate_blocked",
    "security_blocked",
    "needs_correction",
  ].includes(status);
  return (
    <span className={`wp-badge ${warning ? "warn" : ""}`}>
      {statusText[status] || status}
    </span>
  );
}

export default function KnowledgePortal() {
  useEffect(() => {
    function closeOpenDropdowns(event: PointerEvent) {
      if (!(event.target instanceof Node)) return;
      document.querySelectorAll<HTMLDetailsElement>("details[open]").forEach((details) => {
        if (details.dataset.persistent !== "true" && !details.contains(event.target as Node))
          details.open = false;
      });
    }
    document.addEventListener("pointerdown", closeOpenDropdowns);
    return () => document.removeEventListener("pointerdown", closeOpenDropdowns);
  }, []);
  return (
    <ConfirmationProvider>
      <KnowledgePortalContent />
    </ConfirmationProvider>
  );
}

function KnowledgePortalContent() {
  const [session, setSession] = useState<Session | null>(null),
    [kbs, setKbs] = useState<KB[]>([]),
    [reviewKbs, setReviewKbs] = useState<KB[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]),
    [decisionJobs, setDecisionJobs] = useState<DecisionJob[]>([]),
    [users, setUsers] = useState<PortalUser[]>([]),
    [audit, setAudit] = useState<AuditEntry[]>([]),
    [changes, setChanges] = useState<KBChange[]>([]),
    [quality, setQuality] = useState<QualityDashboard | null>(null),
    [qualityCases, setQualityCases] = useState<QualityCases>({
      incidents: [],
      feedback: [],
    }),
    [documents, setDocuments] = useState<PortalDocument[]>([]),
    [removals, setRemovals] = useState<Removals>({ requests: [], trash: [] }),
    [documentChanges, setDocumentChanges] = useState<DocumentChange[]>([]),
    [ownershipTasks, setOwnershipTasks] = useState<OwnershipTask[]>([]),
    [restrictedTerms, setRestrictedTerms] = useState<RestrictedTerm[]>([]),
    [notifications, setNotifications] = useState<PortalNotification[]>([]),
    [autoActivation, setAutoActivation] = useState(false);
  const [tab, setTab] = useState(() =>
      typeof window !== "undefined" &&
      new URLSearchParams(window.location.search).get("feedback")
        ? "feedback"
        : "overview",
    ),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try {
      setError("");
      const current = await api<Session>("/portal/session");
      setSession(current);
      const [
        kbPayload,
        taskPayload,
        decisionJobPayload,
        documentPayload,
        documentChangePayload,
        ownershipPayload,
        notificationPayload,
      ] = await Promise.all([
        api<{ knowledgebases: KB[] }>("/portal/knowledgebases?access=upload"),
        api<{ tasks: Task[]; knowledgebases: KB[] }>("/portal/tasks"),
        api<{ jobs: DecisionJob[] }>("/portal/decision-jobs?active=true"),
        api<{ documents: PortalDocument[] }>("/portal/documents"),
        api<{ changes: DocumentChange[] }>("/portal/document-changes"),
        api<{ tasks: OwnershipTask[] }>("/portal/ownership-tasks"),
        api<{ notifications: PortalNotification[] }>("/portal/notifications"),
      ]);
      setKbs(kbPayload.knowledgebases);
      setTasks(taskPayload.tasks);
      setReviewKbs(taskPayload.knowledgebases);
      setDecisionJobs(decisionJobPayload.jobs);
      setDocuments(documentPayload.documents);
      setDocumentChanges(documentChangePayload.changes);
      setOwnershipTasks(ownershipPayload.tasks);
      setNotifications(notificationPayload.notifications);
      if (["admin", "portal_admin"].includes(current.role)) {
        const [
          userPayload,
          auditPayload,
          changePayload,
          qualityPayload,
          qualityCasePayload,
          removalPayload,
          restrictedPayload,
          autoActivationPayload,
        ] = await Promise.all([
          api<{ users: PortalUser[] }>("/portal/admin/users"),
          api<{ entries: AuditEntry[] }>("/portal/admin/audit?limit=1000"),
          api<{ changes: KBChange[] }>("/portal/admin/knowledgebase-changes"),
          api<QualityDashboard>("/portal/admin/dashboard"),
          api<QualityCases>("/portal/admin/quality-cases"),
          api<Removals>("/portal/admin/removals"),
          api<{ terms: RestrictedTerm[] }>("/portal/admin/restricted-terms"),
          api<{ enabled: boolean }>("/portal/admin/settings/auto-activation"),
        ]);
        setUsers(userPayload.users);
        setAudit(auditPayload.entries);
        setChanges(changePayload.changes);
        setQuality(qualityPayload);
        setQualityCases(qualityCasePayload);
        setRemovals(removalPayload);
        setRestrictedTerms(restrictedPayload.terms);
        setAutoActivation(autoActivationPayload.enabled);
      }
    } catch (cause) {
      setError(friendlyError(cause, "Portal konnte nicht geladen werden"));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);
  useEffect(() => {
    if (decisionJobs.length === 0) return;
    const timer = window.setTimeout(() => void refresh(), 1500);
    return () => window.clearTimeout(timer);
  }, [decisionJobs, refresh]);
  const isAdmin = session
    ? ["admin", "portal_admin"].includes(session.role)
    : false;
  useEffect(() => {
    if (!isAdmin) return;
    const timer = window.setInterval(() => {
      void api<QualityCases>("/portal/admin/quality-cases").then(setQualityCases).catch(() => undefined);
    }, 20000);
    return () => window.clearInterval(timer);
  }, [isAdmin]);
  const unreadNotifications = notifications.filter((item) => !item.read_at);
  const openQualityCases = qualityCases.feedback.length + qualityCases.incidents.length;
  async function markNotificationRead(notificationId: string) {
    const notification = notifications.find((item) => item.notification_id === notificationId);
    if (!notification || notification.read_at) return;
    const readAt = new Date().toISOString();
    setNotifications((current) =>
      current.map((item) => item.notification_id === notificationId ? { ...item, read_at: readAt } : item),
    );
    try {
      await api(`/portal/notifications/${notificationId}/read`, { method: "POST" });
    } catch (cause) {
      setError(friendlyError(cause, "Mitteilungen konnten nicht als gelesen markiert werden"));
      await refresh();
    }
  }
  async function openTab(id: string) {
    setTab(id);
    if (id !== "trash" || !isAdmin || !removals.unread_count) return;
    setRemovals((current) => ({ ...current, unread_count: 0 }));
    try {
      await api("/portal/admin/trash/read", { method: "POST" });
    } catch (cause) {
      setError(friendlyError(cause, "Papierkorbvorgänge konnten nicht als gelesen markiert werden"));
      await refresh();
    }
  }
  const tabs = useMemo<NavigationTab[]>(
    () => [
      ["overview", "Übersicht", LayoutDashboard],
      ["upload", "Dokument hochladen", FileUp],
      ["tasks", isAdmin ? "Admin-Aufgaben" : "Meine Vorgänge", FileSearch],
      ["notifications", "Mitteilungen", Clock3],
      ["documents", "Dokumente", FileSearch],
      ["feedback", "Wissensfehler melden", AlertTriangle],
      ...(isAdmin
        ? ([
            ["quality", "Qualitätsdashboard", FileSearch],
            ["quality-cases", "Qualitätsfälle", AlertTriangle],
            ["migration", "Altbestände", FileUp],
            ["restricted-terms", "Sperrwörter", ShieldCheck],
            ["settings", "Portal-Einstellungen", ShieldCheck],
            ["users", "Benutzer & Rechte", Users],
            ["knowledgebases", "Knowledge Bases", LayoutDashboard],
            ["trash", "Papierkorb", XCircle],
            ["audit", "Audit", ShieldCheck],
          ] as NavigationTab[])
        : []),
    ],
    [isAdmin],
  );
  if (loading)
    return (
      <main className="wp-loading">
        <LoaderCircle className="spin" /> Wissensportal wird geladen …
      </main>
    );
  if (!session)
    return (
      <main className="wp-loading error">
        <AlertTriangle /> {error || "Microsoft-Anmeldung erforderlich"}
      </main>
    );
  return (
    <div className="wp-shell">
      <header className="wp-header">
        <div>
          <strong>
            KAHLE-<span>Vinci</span>
          </strong>
          <small>Wissensportal</small>
        </div>
        <div className="wp-header-actions">
          <a className="wp-back-link" href="/" aria-label="Zurück zu KAHLE-Vinci">
            <ArrowLeft size={17} />
            <span>Zurück zu KAHLE-Vinci</span>
          </a>
          <div className="wp-user">
            <span>{session.display_name}</span>
            <small>
              {session.email} · {session.role.replace("_", "-")}
            </small>
          </div>
        </div>
      </header>
      <aside className="wp-nav">
        <p>Wissen verwalten</p>
        {tabs.map(([id, label, Icon]) => (
          <button
            key={id}
            className={tab === id ? "active" : ""}
            onClick={() => void openTab(id)}
          >
            <Icon size={19} />
            <span>{label}</span>
            {id === "tasks" && tasks.length > 0 && <b>{tasks.length}</b>}
            {id === "notifications" && unreadNotifications.length > 0 && <b>{unreadNotifications.length}</b>}
            {id === "quality-cases" && openQualityCases > 0 && <b>{openQualityCases}</b>}
            {id === "trash" && Boolean(removals.unread_count) && <b>{removals.unread_count}</b>}
            <ChevronRight size={15} />
          </button>
        ))}
        <div className="wp-security">
          <ShieldCheck />
          <div>
            <strong>Sicher verarbeitet</strong>
            <small>
              Rechte, Gültigkeit und Quellen werden automatisch geprüft.
            </small>
          </div>
        </div>
      </aside>
      <main className="wp-main">
        {error && (
          <div className="wp-alert">
            <AlertTriangle />
            {error}
            <button onClick={() => setError("")}>Schließen</button>
          </div>
        )}
        {tab === "overview" && (
          <Overview session={session} tasks={tasks} kbs={kbs} go={setTab} />
        )}
        {tab === "upload" && (
          <Upload session={session} kbs={kbs} done={refresh} />
        )}
        {tab === "tasks" && (
          <Tasks tasks={tasks} jobs={decisionJobs} kbs={reviewKbs} session={session} done={refresh} />
        )}
        {tab === "notifications" && (
          <Notifications items={notifications} onRead={markNotificationRead} />
        )}
        {tab === "documents" && (
          <DocumentList
            documents={documents}
            changes={documentChanges}
            ownershipTasks={ownershipTasks}
            users={users}
            session={session}
            done={refresh}
          />
        )}
        {tab === "feedback" && <FeedbackForm />}
        {tab === "quality" && isAdmin && (
          <QualityDashboardView data={quality} />
        )}
        {tab === "quality-cases" && isAdmin && (
          <QualityCasesView data={qualityCases} done={refresh} />
        )}
        {tab === "migration" && isAdmin && (
          <MigrationView users={users} kbs={kbs} session={session} />
        )}
        {tab === "restricted-terms" && isAdmin && (
          <RestrictedTermsView terms={restrictedTerms} done={refresh} />
        )}
        {tab === "settings" && isAdmin && (
          <PortalSettings
            enabled={autoActivation}
            session={session}
            done={refresh}
          />
        )}
        {tab === "users" && isAdmin && (
          <UserAdmin users={users} session={session} done={refresh} />
        )}
        {tab === "knowledgebases" && isAdmin && (
          <KnowledgebaseAdmin
            changes={changes}
            users={users}
            session={session}
            done={refresh}
          />
        )}
        {tab === "trash" && isAdmin && (
          <TrashView data={removals} done={refresh} session={session} />
        )}
        {tab === "audit" && isAdmin && (
          <AuditView entries={audit} users={users} />
        )}
      </main>
    </div>
  );
}

function Notifications({
  items,
  onRead,
}: {
  items: PortalNotification[];
  onRead: (notificationId: string) => Promise<void>;
}) {
  return (
    <section className="wp-page">
      <Title
        eyebrow="Änderungen am Wissensbestand"
        title="Mitteilungen"
        text="Hier siehst du Freigaben sowie Änderungen an Dokumenten und Wissensbereichen, die dich betreffen."
      />
      {items.length ? (
        <div className="wp-doc-list">
          {items.map((item) => (
            <button
              type="button"
              key={item.notification_id}
              className={`wp-notification-card ${item.read_at ? "read" : "unread"}`}
              onClick={() => void onRead(item.notification_id)}
            >
              <div className="wp-doc-panel">
                <Badge status={item.status} />
                <h2 className="wp-notification-title">{item.document_title}</h2>
                <p>{item.message}</p>
                {item.reason && (
                  <p>
                    <strong>{item.status === "clarification_requested" ? "Rückfrage:" : "Begründung:"}</strong>{" "}
                    {item.reason}
                  </p>
                )}
                <small>{new Date(item.created_at).toLocaleString("de-DE")}</small>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="wp-empty"><CheckCircle2 /><h2>Keine neuen Mitteilungen</h2></div>
      )}
    </section>
  );
}

function PortalSettings({
  enabled,
  session,
  done,
}: {
  enabled: boolean;
  session: Session;
  done: () => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const canChange = session.role === "portal_admin";
  async function change() {
    if (!canChange || reason.trim().length < 3) return;
    setBusy(true);
    try {
      await api("/portal/admin/settings/auto-activation", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !enabled, reason: reason.trim() }),
      });
      setReason("");
      await done();
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="wp-page narrow">
      <Title eyebrow="Sicherer Betrieb" title="Portal-Einstellungen" />
      <div className={`wp-upload-outcome ${enabled ? "success" : "waiting"}`}>
        <ShieldCheck />
        <div>
          <span>Automatische Veröffentlichung</span>
          <h2>{enabled ? "Für saubere Bereichsdokumente aktiv" : "Deaktiviert"}</h2>
          <p>
            {enabled
              ? "Dokumente ohne Treffer werden in Bereichs-Wissensbasen direkt veröffentlicht. KAHLE-Allgemein und auffällige Dokumente bleiben im Freigabeprozess."
              : "Auch unauffällige Dokumente warten auf eine Führungskraft. Für den Produktivstart bleibt diese Einstellung bis zur Abnahme deaktiviert."}
          </p>
          {canChange ? (
            <>
              <label>
                Schriftliche Begründung
                <textarea value={reason} onChange={(event) => setReason(event.target.value)} />
              </label>
              <button
                className="wp-primary"
                disabled={busy || reason.trim().length < 3}
                onClick={() => void change()}
              >
                {enabled ? "Automatische Veröffentlichung ausschalten" : "Automatische Veröffentlichung einschalten"}
              </button>
            </>
          ) : (
            <strong>Nur ein Portal-Admin darf diese Einstellung ändern.</strong>
          )}
        </div>
      </div>
    </section>
  );
}

function Overview({
  session,
  tasks,
  kbs,
  go,
}: {
  session: Session;
  tasks: Task[];
  kbs: KB[];
  go: (value: string) => void;
}) {
  return (
    <section className="wp-page">
      <Title
        eyebrow={`Guten Tag, ${session.display_name.split(" ")[0]}`}
        title="Was möchtest du heute erledigen?"
      />
      <div className="wp-cards">
        <button onClick={() => go("upload")}>
          <FileUp />
          <div>
            <strong>Dokument bereitstellen</strong>
            <span>
              Datei ablegen, Ziel wählen – Vinci übernimmt die Prüfung.
            </span>
          </div>
          <ChevronRight />
        </button>
        <button onClick={() => go("tasks")}>
          <Clock3 />
          <div>
            <strong>
              {tasks.length
                ? `${tasks.length} offene Vorgänge`
                : "Keine offenen Vorgänge"}
            </strong>
            <span>
              {tasks.length
                ? "Entscheidungen und Freigaben warten auf dich."
                : "Im Moment ist alles erledigt."}
            </span>
          </div>
          <ChevronRight />
        </button>
      </div>
      <h2>Deine Wissensbereiche</h2>
      <div className="wp-kbs">
        {kbs.length ? (
          kbs.map((kb) => (
            <article key={kb.knowledgebase_id}>
              <ShieldCheck />
              <div>
                <strong>{kb.label}</strong>
                <span>{kb.purpose || "Für Upload freigegeben"}</span>
              </div>
            </article>
          ))
        ) : (
          <p>Dir ist aktuell noch kein Uploadbereich zugeordnet.</p>
        )}
      </div>
    </section>
  );
}

function Title({
  eyebrow,
  title,
  text,
}: {
  eyebrow: string;
  title: string;
  text?: string;
}) {
  return (
    <div className="wp-title">
      <div>
        <p>{eyebrow}</p>
        <h1>{title}</h1>
        {text && <span>{text}</span>}
      </div>
    </div>
  );
}

function Upload({
  session,
  kbs,
  done,
}: {
  session: Session;
  kbs: KB[];
  done: () => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null),
    [selectedKnowledgebaseIds, setSelectedKnowledgebaseIds] = useState<string[]>([]),
    [title, setTitle] = useState("");
  const [days, setDays] = useState(60),
    [busy, setBusy] = useState(false);
  const [validityMode, setValidityMode] = useState("workdays"),
    [validUntil, setValidUntil] = useState("");
  const dateIso = (offset: number) => {
    const value = new Date();
    value.setHours(12, 0, 0, 0);
    value.setDate(value.getDate() + offset);
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  };
  const minimumValidUntil = dateIso(1);
  const maximumValidUntil = dateIso(60);
  const validUntilError = validityMode === "date" && validUntil
    ? validUntil < minimumValidUntil
      ? "Bitte wähle ein zukünftiges Datum."
      : validUntil > maximumValidUntil
        ? "Maximal 60 Tage sind möglich."
        : ""
    : "";
  const [result, setResult] = useState<UploadResult | null>(null),
    [message, setMessage] = useState("");
  const [securityReviewAvailable, setSecurityReviewAvailable] = useState(false);
  const [job, setJob] = useState<UploadJob | null>(null);
  const [ownerCandidates, setOwnerCandidates] = useState<PortalUser[]>([]),
    [canProposeOwner, setCanProposeOwner] = useState(false),
    [ownerUserId, setOwnerUserId] = useState(session.user_id),
    [ownerSearch, setOwnerSearch] = useState("");
  useEffect(() => {
    void api<{ can_propose_other: boolean; users: PortalUser[] }>(
      "/portal/owner-candidates",
    ).then((payload) => {
      setCanProposeOwner(payload.can_propose_other);
      setOwnerCandidates(payload.users);
    });
  }, []);
  // PRD 12.3: Die Verarbeitung laeuft serverseitig weiter. Die laufende Job-ID wird
  // deshalb gemerkt, damit der Vorgang nach Reload oder Tabwechsel wieder erscheint.
  const follow = useCallback(
    async (jobId: string, known?: UploadJob) => {
      setBusy(true);
      setMessage("");
      try {
        sessionStorage.setItem(RUNNING_UPLOAD_JOB, jobId);
        let current =
          known ?? (await api<UploadJob>(`/portal/upload-jobs/${jobId}`));
        setJob(current);
        while (!["completed", "failed"].includes(current.status)) {
          await new Promise((resolve) => window.setTimeout(resolve, 700));
          current = await api<UploadJob>(`/portal/upload-jobs/${jobId}`);
          setJob(current);
        }
        if (current.status === "failed")
          throw new Error(current.error_code || "Verarbeitung fehlgeschlagen");
        if (!current.result) throw new Error("Verarbeitungsergebnis fehlt");
        setResult(current.result);
        await done();
      } catch (cause) {
        const raw = cause instanceof Error ? cause.message : "";
        setSecurityReviewAvailable(raw === "embedded_executable_content_not_allowed");
        setMessage(friendlyError(cause, "Upload fehlgeschlagen"));
      } finally {
        sessionStorage.removeItem(RUNNING_UPLOAD_JOB);
        setBusy(false);
      }
    },
    [done],
  );
  useEffect(() => {
    const running = sessionStorage.getItem(RUNNING_UPLOAD_JOB);
    if (!running) return;
    const timer = window.setTimeout(() => void follow(running), 0);
    return () => window.clearTimeout(timer);
  }, [follow]);
  function chooseFile(next: File | null) {
    const allowedExtensions = ["pdf", "docx", "xlsx", "pptx", "txt", "md"];
    const extension = next?.name.split(".").pop()?.toLowerCase();
    if (next && !allowedExtensions.includes(extension || "")) {
      setFile(null);
      setMessage(
        "Dieses Dateiformat wird nicht unterstützt. Erlaubt sind PDF, Word, Excel, PowerPoint, TXT und Markdown.",
      );
      return;
    }
    setMessage("");
    setFile(next);
    // Nur vorbelegen, solange nichts Eigenes eingetragen ist.
    if (next && !title.trim()) setTitle(titleFromFilename(next.name));
  }
  async function submit(securityReviewRequested = false) {
    if (!file || selectedKnowledgebaseIds.length === 0 || !title.trim())
      return setMessage("Bitte Datei, Titel und mindestens einen Wissensbereich auswählen.");
    if (validityMode === "date" && !validUntil)
      return setMessage("Bitte ein Datum für die Gültigkeit wählen.");
    if (validUntilError) return setMessage(validUntilError);
    setBusy(true);
    setMessage("");
    if (!securityReviewRequested) setSecurityReviewAvailable(false);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("knowledgebase_id", selectedKnowledgebaseIds[0]);
      form.append("knowledgebase_ids_json", JSON.stringify(selectedKnowledgebaseIds));
      form.append("title", title.trim());
      // PRD 17.1: Arbeitstage oder ein geprüftes Datum, niemals beides. Die
      // Umrechnung bleibt serverseitig, damit Feiertage verbindlich zählen.
      if (validityMode === "date") form.append("valid_until", validUntil);
      else form.append("valid_workdays", String(days));
      // Sichtbarkeit folgt ausschließlich den Leserechten des gewählten
      // Wissensbereichs. Die interne Grundstufe kann durch die automatische
      // Inhaltsprüfung weiterhin sicherheitsseitig angehoben werden.
      form.append("confidentiality", "internal");
      form.append("owner_user_id", ownerUserId);
      if (securityReviewRequested) form.append("security_review_requested", "true");
      const response = await fetch(`${API}/portal/upload-jobs`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      const created = await response.json();
      if (!response.ok)
        throw new Error(created.detail || "Upload fehlgeschlagen");
      await follow(created.job_id, created);
    } catch (cause) {
      setMessage(friendlyError(cause, "Upload fehlgeschlagen"));
      setBusy(false);
    }
  }
  async function action(value: string, targetDocumentId?: string) {
    if (!result) return;
    setBusy(true);
    try {
      await api(`/portal/cases/${result.case_id}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: value,
          target_document_id: targetDocumentId,
        }),
      });
      setResult(null);
      setFile(null);
      setSelectedKnowledgebaseIds([]);
      setTitle("");
      setMessage(
        "Weitergeleitet. Das Dokument wird erst nach der Freigabe in Vinci auffindbar; du wirst benachrichtigt.",
      );
      await done();
    } catch (cause) {
      setMessage(friendlyError(cause, "Aktion fehlgeschlagen"));
    } finally {
      setBusy(false);
    }
  }
  function startAnotherUpload() {
    setResult(null);
    setFile(null);
    setSelectedKnowledgebaseIds([]);
    setTitle("");
    setValidUntil("");
    setJob(null);
    setMessage("");
    setOwnerUserId(session.user_id);
  }
  const outcome = result
    ? result.status === "active"
      ? {
          tone: "success",
          title: "Dokument wurde veröffentlicht",
          text: "Das Dokument ist jetzt für berechtigte Nutzer in Vinci abrufbar.",
          next: "Du musst nichts weiter tun. Über die Dokumentenübersicht kannst du den aktuellen Status jederzeit prüfen.",
        }
      : ["security_blocked", "needs_correction"].includes(result.status)
        ? {
            tone: "blocked",
            title: "Dokument wurde blockiert",
            text: "Das Dokument wurde nicht veröffentlicht und ist nicht in Vinci abrufbar.",
            next:
              result.status === "needs_correction"
                ? "Bitte prüfe die Aufbereitung und reiche eine korrigierte Fassung ein."
                : "Die Datei bleibt aus Sicherheitsgründen gesperrt. Wende dich bei Rückfragen an einen Admin.",
          }
        : {
            tone: "waiting",
            title: "Dokument wurde noch nicht veröffentlicht",
            text: "Das Dokument ist aktuell nicht in Vinci abrufbar.",
            next: result.owner_confirmation_required
              ? "Zuerst muss der vorgeschlagene Owner die Verantwortung bestätigen."
              : ["pending_employee_decision", "duplicate_blocked"].includes(
                    result.status,
                  )
                ? result.requires_admin
                  ? "Wähle jetzt die gewünschte Aktion. Danach prüfen zuerst die Führungskraft und anschließend ein Admin den Vorgang."
                  : "Wähle jetzt die gewünschte Aktion. Danach entscheidet die zuständige Führungskraft."
                : result.status === "pending_manager_approval"
                  ? result.requires_admin
                    ? "Die Führungskraft prüft den Vorgang zuerst. Bei Zustimmung entscheidet anschließend zusätzlich ein Admin."
                    : "Die zuständige Führungskraft prüft den Vorgang und entscheidet über die Veröffentlichung."
                  : result.status === "pending_admin_approval"
                    ? "Die Führungskraft hat den Vorgang bearbeitet. Jetzt ist noch die Entscheidung eines Admins erforderlich."
                    : "Der Vorgang wird geprüft. Du erhältst nach der Entscheidung eine Nachricht.",
          }
    : null;
  return (
    <section className="wp-page narrow">
      <Title
        eyebrow="Neues Wissen"
        title="Dokument bereitstellen"
        text="Du legst nur die Datei ab. Das Portal prüft Sicherheit, Aufbereitung und ähnliche Inhalte."
      />
      {!result ? (
        <div className="wp-form" data-visibility-policy="knowledgebase-rights">
          <label
            className={`wp-drop ${file ? "selected" : ""}`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              chooseFile(e.dataTransfer.files[0] || null);
            }}
          >
            {file ? (
              <>
                <CheckCircle2 />
                <strong>{file.name}</strong>
                <span>
                  {(file.size / 1048576).toFixed(1)} MB · Datei ändern
                </span>
              </>
            ) : (
              <>
                <FileUp />
                <strong>Datei hier ablegen</strong>
                <span>oder klicken und auswählen · maximal 50 MB</span>
              </>
            )}
            <input
              type="file"
              accept=".pdf,.docx,.xlsx,.pptx,.txt,.md"
              onChange={(e) => chooseFile(e.target.files?.[0] || null)}
            />
          </label>
          <div className="wp-grid">
            <label>
              Titel
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Worum geht es?"
              />
            </label>
            <div className="wp-kb-field">
              <span>Ziel-Wissensbereiche</span>
              <details className="wp-kb-multiselect">
                <summary>
                  <span>
                    {selectedKnowledgebaseIds.length
                      ? kbs
                          .filter((item) => selectedKnowledgebaseIds.includes(item.knowledgebase_id))
                          .map((item) => item.label)
                          .join(", ")
                      : "Bitte wählen"}
                  </span>
                  <ChevronRight size={16} />
                </summary>
                <fieldset className="wp-kb-options">
                  <legend className="sr-only">Ziel-Wissensbereiche auswählen</legend>
                  {kbs.map((item) => (
                    <label key={item.knowledgebase_id}>
                      <input
                        type="checkbox"
                        checked={selectedKnowledgebaseIds.includes(item.knowledgebase_id)}
                        onChange={(event) =>
                          setSelectedKnowledgebaseIds((current) =>
                            event.target.checked
                              ? [...current, item.knowledgebase_id]
                              : current.filter((id) => id !== item.knowledgebase_id),
                          )
                        }
                      />
                      {item.label}
                    </label>
                  ))}
                </fieldset>
              </details>
              <small>Mehrere Bereiche können gleichzeitig ausgewählt werden.</small>
            </div>
            <label>
              Gültigkeit
              <select
                value={validityMode}
                onChange={(e) => setValidityMode(e.target.value)}
              >
                <option value="workdays">Für eine Anzahl Arbeitstage</option>
                <option value="date">Bis zu einem Datum</option>
              </select>
            </label>
            {validityMode === "workdays" ? (
              <label>
                Arbeitstage
                <select
                  value={days}
                  onChange={(e) => setDays(Number(e.target.value))}
                >
                  {[60, 45, 30, 20, 10].map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
            ) : (
              <label>
                Gültig bis
                <input
                  type="date"
                  value={validUntil}
                  min={minimumValidUntil}
                  max={maximumValidUntil}
                  onChange={(e) => setValidUntil(e.target.value)}
                />
                {validUntilError && <small className="wp-field-error" role="alert">{validUntilError}</small>}
              </label>
            )}
          </div>
          <div className="wp-owner">
            <ShieldCheck />
            <div>
              <strong>Dokument-Owner</strong>
              {canProposeOwner ? (
                <>
                  <details className="wp-kb-multiselect wp-owner-picker">
                    <summary>
                      <span>{ownerCandidates.find((user) => user.user_id === ownerUserId)?.display_name || session.display_name}</span>
                      <ChevronRight size={16} />
                    </summary>
                    <fieldset className="wp-kb-options">
                      <legend className="sr-only">Dokument-Owner auswählen</legend>
                      <input
                        className="wp-feedback-document-search"
                        type="search"
                        value={ownerSearch}
                        onChange={(event) => setOwnerSearch(event.target.value)}
                        placeholder="Name oder E-Mail suchen …"
                        aria-label="Dokument-Owner suchen"
                      />
                      {ownerCandidates.filter((user) =>
                        `${user.display_name} ${user.email}`.toLocaleLowerCase("de")
                          .includes(ownerSearch.trim().toLocaleLowerCase("de")),
                      ).map((user) => (
                        <label key={user.user_id}>
                          <input type="radio" name="document-owner" checked={ownerUserId === user.user_id}
                            onChange={() => setOwnerUserId(user.user_id)} />
                          <span>{user.display_name}<small>{user.email}</small></span>
                        </label>
                      ))}
                    </fieldset>
                  </details>
                  <span>
                    Ein anderer Owner muss die Übernahme ausdrücklich
                    bestätigen.
                  </span>
                </>
              ) : (
                <span>
                  {session.email} · Erinnerungen werden automatisch deinem Konto
                  zugeordnet.
                </span>
              )}
            </div>
          </div>
          {job && busy && (
            <div className="wp-owner" role="status">
              <LoaderCircle className="spin" />
              <div>
                <strong>{stepText[job.step] || stepText.uploaded}</strong>
                <span>
                  {job.progress}% abgeschlossen – du kannst diese Seite
                  verlassen, die Prüfung läuft weiter.
                </span>
              </div>
            </div>
          )}
          {message && <p className="wp-message">{message}</p>}
          {securityReviewAvailable && (
            <div className="wp-alert" role="note">
              <ShieldCheck />
              <div>
                <strong>Ist das ein vertrauenswürdiges PDF?</strong>
                <span>
                  Du kannst eine passive, bereinigte Fassung zur Prüfung an einen Admin senden.
                  Die eingebetteten aktiven Inhalte werden dabei nicht übernommen.
                </span>
                <button
                  type="button"
                  className="wp-secondary approve"
                  disabled={busy}
                  onClick={() => void submit(true)}
                >
                  Zur Sicherheitsprüfung einreichen
                </button>
              </div>
            </div>
          )}
          <button
            className="wp-primary"
            disabled={busy || !file || selectedKnowledgebaseIds.length === 0}
            onClick={() => void submit(false)}
          >
            {busy && <LoaderCircle className="spin" />} Sicher prüfen
          </button>
        </div>
      ) : (
        <div className="wp-result">
          {outcome && (
            <div
              className={`wp-upload-outcome ${outcome.tone}`}
              role="status"
              aria-live="polite"
            >
              {outcome.tone === "success" ? (
                <CheckCircle2 />
              ) : outcome.tone === "blocked" ? (
                <XCircle />
              ) : (
                <AlertTriangle />
              )}
              <div>
                <span>Ergebnis der Prüfung</span>
                <h2>{outcome.title}</h2>
                <p>{outcome.text}</p>
                <strong>Was passiert jetzt?</strong>
                <p>{outcome.next}</p>
              </div>
            </div>
          )}
          {result.restricted_terms && result.restricted_terms.length > 0 && (
            <div className="wp-finding-card critical">
              <AlertTriangle />
              <div>
                <span>Sicherheitsprüfung</span>
                <h3>Gesperrter Inhalt gefunden</h3>
                <p>
                  Gefundene gesperrte Begriffe: {result.restricted_terms.join(", ")}
                </p>
                <strong>Das Dokument bleibt bis zur vollständigen Freigabe gesperrt.</strong>
              </div>
            </div>
          )}
          <div className="wp-owner">
            <ShieldCheck />
            <div>
              <strong>
                Automatische Einstufung:{" "}
                {confidentialityText[result.confidentiality] ||
                  result.confidentiality}
              </strong>
              <span>{result.confidentiality_reason}</span>
            </div>
          </div>
          {result.conversion_quality &&
            qualityRating[result.conversion_quality] && (
              <div
                className={`wp-quality ${qualityRating[result.conversion_quality].tone}`}
                role="status"
              >
                {result.conversion_quality === "good" ? (
                  <CheckCircle2 />
                ) : result.conversion_quality === "low" ? (
                  <AlertTriangle />
                ) : (
                  <XCircle />
                )}
                <div>
                  <strong>
                    Aufbereitung:{" "}
                    {qualityRating[result.conversion_quality].title}
                  </strong>
                  <span>{qualityRating[result.conversion_quality].text}</span>
                </div>
              </div>
            )}
          {result.conversion_issues && result.conversion_issues.length > 0 && (
            <div className="wp-alert">
              <AlertTriangle />
              <div>
                <strong>Aufbereitung muss geprüft werden</strong>
                {result.conversion_issues.map((issue) => (
                  <span key={issue}>{conversionIssueText(issue)}</span>
                ))}
              </div>
            </div>
          )}
          {result.matches.map((match) => (
            <article key={match.document_id} className="wp-match">
              <div>
                <strong>{match.title}</strong>
                <span>
                  {match.has_conflict
                    ? `Möglicher Widerspruch${match.conflict_count ? ` in ${match.conflict_count} Textstelle${match.conflict_count === 1 ? "" : "n"}` : ""}`
                    : match.version_candidate
                      ? "Mögliche neue Version"
                      : "Ähnlicher Inhalt"}
                </span>
                {match.knowledgebase_ids?.length ? (
                  <small>
                    Bereits in: {match.knowledgebase_ids.join(", ")}
                  </small>
                ) : null}
              </div>
              <span className="wp-match-level">
                <strong>{matchLevelText[match.level] || match.level}</strong>
                {typeof match.match_percent === "number" ? (
                  <small>{match.match_percent} % Übereinstimmung</small>
                ) : null}
              </span>
              {match.version_candidate && (
                <button
                  className="wp-version-action"
                  onClick={() => void action("replace", match.document_id)}
                >
                  Als neue Version von „{match.title}“ vorschlagen
                </button>
              )}
            </article>
          ))}
          {!result.owner_confirmation_required &&
            ["pending_employee_decision", "duplicate_blocked"].includes(
              result.status,
            ) && (
              <div className="wp-actions">
                {!result.exact_duplicate_document_id && (
                  <button onClick={() => void action("create")}>
                    Als neues Dokument vorschlagen
                  </button>
                )}
                {result.exact_duplicate_document_id && (
                  <button onClick={() => void action("publish_existing")}>
                    Vorhandenes zusätzlich veröffentlichen
                  </button>
                )}
                <button
                  className="secondary"
                  onClick={() => void action("discard")}
                >
                  Verwerfen
                </button>
              </div>
            )}
          <button className="wp-primary" type="button" onClick={startAnotherUpload}>
            <FileUp size={16} /> Weiteres Dokument hochladen
          </button>
        </div>
      )}
    </section>
  );
}

function Tasks({
  tasks,
  jobs,
  kbs,
  session,
  done,
}: {
  tasks: Task[];
  jobs: DecisionJob[];
  kbs: KB[];
  session: Session;
  done: () => Promise<void>;
}) {
  const confirm = useConfirmation();
  const [reason, setReason] = useState<Record<string, string>>({}),
    [busy, setBusy] = useState(""),
    [decisionFeedback, setDecisionFeedback] = useState<Record<string, string>>({});
  const [review, setReview] = useState<Review | null>(null),
    [revision, setRevision] = useState("");
  const [inquiryCase, setInquiryCase] = useState<Task | null>(null),
    [inquiryParticipants, setInquiryParticipants] = useState<InquiryParticipant[]>([]),
    [inquiryRecipient, setInquiryRecipient] = useState(""),
    [inquiryQuestion, setInquiryQuestion] = useState(""),
    [inquiryBusy, setInquiryBusy] = useState(false),
    [inquiryMessage, setInquiryMessage] = useState("");
  const [targetSelections, setTargetSelections] = useState<Record<string, string[]>>({}),
    [targetBusy, setTargetBusy] = useState<Record<string, boolean>>({});
  const targetSaveLocks = useRef(new Set<string>());
  const canDecide = session.role !== "employee",
    isAdmin = ["admin", "portal_admin"].includes(session.role);
  const ownDecision = (status: string) =>
    ["pending_employee_decision", "duplicate_blocked"].includes(status);
  async function chooseAction(caseId: string, action: string, targetDocumentId?: string) {
    setBusy(caseId);
    try {
      await api(`/portal/cases/${caseId}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, target_document_id: targetDocumentId }),
      });
      await done();
    } finally {
      setBusy("");
    }
  }
  async function chooseNewDocument(task: Task) {
    const hasSimilarDocument = Boolean(task.duplicate_matches?.length);
    if (hasSimilarDocument) {
      const approved = await confirm({
        title: "Wirklich als eigenständiges Dokument anlegen?",
        description: `Zu „${task.title}“ wurde bereits mindestens ein sehr ähnliches Dokument gefunden. Wähle diese Option nur, wenn beide Dokumente unabhängig voneinander gültig bleiben sollen.`,
        confirmLabel: "Eigenständiges Dokument vorschlagen",
      });
      if (!approved) return;
    }
    await chooseAction(task.case_id, "create");
  }
  async function decide(caseId: string, decision: string) {
    if (busy) return;
    const writtenReason = (reason[caseId] || "").trim();
    const needsReason = decision !== "approve";
    if (needsReason && writtenReason.length < 3) return;
    setBusy(caseId);
    setDecisionFeedback({
      ...decisionFeedback,
      [caseId]:
        decision === "approve"
          ? "Freigabe läuft … Bitte warte einen Moment."
          : "Entscheidung wird verarbeitet … Bitte warte einen Moment.",
    });
    try {
      const job = await api<DecisionJob>(`/portal/cases/${caseId}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          decision,
          reason: decision === "approve" ? "" : writtenReason,
        }),
      });
      setDecisionFeedback({
        ...decisionFeedback,
        [caseId]: "Entscheidung wurde sicher angenommen.",
      });
      await done();
      void watchDecisionUntilFinished(job.job_id, caseId);
    } catch (cause) {
      setDecisionFeedback({
        ...decisionFeedback,
        [caseId]: friendlyError(
          cause,
          "Die Entscheidung konnte nicht gespeichert werden. Bitte versuche es erneut.",
        ),
      });
    } finally {
      setBusy("");
    }
  }
  async function watchDecisionUntilFinished(jobId: string, caseId: string) {
    // Aktualisiert nur den Hintergrundstatus; die Oberfläche bleibt frei bedienbar.
    for (let attempt = 0; attempt < 240; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      try {
        const job = await api<DecisionJob>(`/portal/decision-jobs/${jobId}`);
        if (job.status === "completed") {
          await done();
          return;
        }
        if (job.status === "failed") {
          setDecisionFeedback((current) => ({
            ...current,
            [caseId]: "Die Veröffentlichung konnte nicht abgeschlossen werden. Ein Admin wurde informiert.",
          }));
          await done();
          return;
        }
      } catch {
        // Ein kurzer Verbindungsabbruch darf den serverseitigen Job nicht beeinflussen.
      }
    }
    await done();
  }
  async function openReview(caseId: string) {
    const payload = await api<Review>(`/portal/cases/${caseId}/review`);
    setReview(payload);
    setRevision(isAdmin ? payload.markdown : "");
  }
  async function openInquiry(task: Task) {
    setInquiryBusy(true);
    setInquiryMessage("");
    try {
      const payload = await api<{ participants: InquiryParticipant[] }>(
        `/portal/cases/${task.case_id}/inquiry-participants`,
      );
      setInquiryCase(task);
      setInquiryParticipants(payload.participants);
      setInquiryRecipient(payload.participants[0]?.user_id || "");
      setInquiryQuestion("");
    } catch (cause) {
      setDecisionFeedback((current) => ({
        ...current,
        [task.case_id]: friendlyError(cause, "Die Ansprechpartner konnten nicht geladen werden."),
      }));
    } finally {
      setInquiryBusy(false);
    }
  }
  async function changeTargetKnowledgebases(caseId: string, knowledgebaseIds: string[]) {
    if (targetSaveLocks.current.has(caseId)) return;
    if (knowledgebaseIds.length === 0) {
      setDecisionFeedback((current) => ({
        ...current,
        [caseId]: "Mindestens ein Ziel-Wissensbereich muss ausgewählt bleiben.",
      }));
      return;
    }
    targetSaveLocks.current.add(caseId);
    setTargetSelections((current) => ({ ...current, [caseId]: knowledgebaseIds }));
    setTargetBusy((current) => ({ ...current, [caseId]: true }));
    setDecisionFeedback((current) => ({
      ...current,
        [caseId]: "Die Ziel-Wissensbereiche werden geändert …",
    }));
    try {
      await api(`/portal/cases/${caseId}/target-knowledgebases`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ knowledgebase_ids: knowledgebaseIds }),
      });
      setDecisionFeedback((current) => ({
        ...current,
        [caseId]: "Die Ziel-Wissensbereiche wurden geändert.",
      }));
      await done();
      setTargetSelections((current) => {
        const next = { ...current };
        delete next[caseId];
        return next;
      });
    } catch (cause) {
      setTargetSelections((current) => {
        const next = { ...current };
        delete next[caseId];
        return next;
      });
      setDecisionFeedback((current) => ({
        ...current,
        [caseId]: friendlyError(cause, "Die Ziel-Wissensbereiche konnten nicht geändert werden."),
      }));
    } finally {
      targetSaveLocks.current.delete(caseId);
      setTargetBusy((current) => ({ ...current, [caseId]: false }));
    }
  }
  async function sendInquiry() {
    if (!inquiryCase || !inquiryRecipient || inquiryQuestion.trim().length < 3) return;
    setInquiryBusy(true);
    setInquiryMessage("");
    try {
      await api(`/portal/cases/${inquiryCase.case_id}/inquiries`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          recipient_user_id: inquiryRecipient,
          question: inquiryQuestion.trim(),
        }),
      });
      setInquiryMessage("Die Rückfrage wurde als Mitteilung und per E-Mail versendet.");
      setInquiryQuestion("");
    } catch (cause) {
      setInquiryMessage(friendlyError(cause, "Die Rückfrage konnte nicht versendet werden."));
    } finally {
      setInquiryBusy(false);
    }
  }
  async function revise() {
    if (!review) return;
    const approved = await confirm({
      title: "Korrektur verarbeiten?",
      description: `Du möchtest für „${review.case.title}“ eine neue Entwurfsversion anlegen. Alle bisherigen Prüfergebnisse werden zurückgesetzt und die neue Fassung wird vollständig geprüft. Möchtest du fortfahren?`,
      confirmLabel: "Korrektur verarbeiten",
    });
    if (!approved) return;
    setBusy(review.case.case_id);
    try {
      await api(`/portal/cases/${review.case.case_id}/revision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction: isAdmin ? "" : revision,
          replacement_markdown: isAdmin ? revision : "",
          reason: reason[review.case.case_id] || "Freigegebene Korrektur",
          confirmed: true,
        }),
      });
      setReview(null);
      await done();
    } finally {
      setBusy("");
    }
  }
  if (review)
    return (
      <section className="wp-page">
        <Title
          eyebrow="Dokumentprüfung"
          title={review.case.title}
          text={
            isAdmin
              ? "Original und RAG-Markdown können direkt miteinander verglichen werden."
              : "Original und aufbereitete Fassung können direkt miteinander verglichen werden."
          }
        />
        <div className="wp-actions">
          <a
            className="wp-primary"
            target="_blank"
            rel="noreferrer"
            href={review.original_url}
          >
            Original ansehen (nur Vorschau)
          </a>
          <button onClick={() => setReview(null)}>Zurück</button>
        </div>
        <div className="wp-review-kbs" aria-label="Verknüpfte Knowledge Bases">
          <span>Knowledge Bases</span>
          <strong>
            {review.knowledgebases.length
              ? review.knowledgebases.map((base) => base.label).join(", ")
              : "Keine Knowledge Base verknüpft"}
          </strong>
        </div>
        <div className="wp-form">
          <label>
            {isAdmin ? "RAG-Markdown bearbeiten" : "Aufbereitete Fassung"}
            <textarea
              rows={22}
              readOnly={!isAdmin}
              value={isAdmin ? revision : review.markdown}
              onChange={(e) => isAdmin && setRevision(e.target.value)}
            />
          </label>
          {(isAdmin || session.role === "employee") && (
            <>
              <label>
                {isAdmin ? "Begründung" : "Korrektur in Alltagssprache"}
                <textarea
                  value={isAdmin ? reason[review.case.case_id] || "" : revision}
                  onChange={(e) =>
                    isAdmin
                      ? setReason({
                          ...reason,
                          [review.case.case_id]: e.target.value,
                        })
                      : setRevision(e.target.value)
                  }
                />
              </label>
              <button
                className="wp-primary"
                disabled={busy === review.case.case_id}
                onClick={() => void revise()}
              >
                Neue Entwurfsversion anlegen und vollständig prüfen
              </button>
            </>
          )}
        </div>
      </section>
    );
  // Eigene Uploads und fremde Freigaben sind zwei verschiedene Rollen im
  // selben Vorgang. Gemischt in einer Liste ist nicht erkennbar, wo man
  // selbst gefragt ist und wo man als Pruefer entscheidet.
  const publishingCaseIds = new Set(jobs.map((job) => job.case_id));
  const publishing = tasks.filter((task) => publishingCaseIds.has(task.case_id));
  const availableTasks = tasks.filter((task) => !publishingCaseIds.has(task.case_id));
  const mine = availableTasks.filter((task) => ownDecision(task.status));
  const toReview = availableTasks.filter((task) => !ownDecision(task.status));

  function card(task: Task, own: boolean) {
    const selectedTargetIds =
      targetSelections[task.case_id] ||
      task.target_knowledgebase_ids ||
      [task.target_knowledgebase_id];
    const selectedTargetLabels = kbs
      .filter((base) => selectedTargetIds.includes(base.knowledgebase_id))
      .map((base) => base.label);
    const targetIsSaving = Boolean(targetBusy[task.case_id]);
    return (
      <article key={task.case_id}>
        <div className="wp-task-icon">
          <FileSearch />
        </div>
        <div className="wp-task-copy">
          <div className="wp-task-context">
            <Badge status={task.status} />
            {task.contact_name && <span>Ansprechpartner: {task.contact_name}</span>}
          </div>
          <h2>{task.title}</h2>
          <p>
            {task.original_filename}
          </p>
          <div className="wp-target-kb">
            <span>Ziel-Wissensbereiche</span>
            {!own && task.status.includes("approval") ? (
              <details className="wp-kb-multiselect compact">
                <summary>
                  <span>
                    {(selectedTargetLabels.length
                      ? selectedTargetLabels
                      : task.target_knowledgebase_labels || [task.target_knowledgebase_label || task.target_knowledgebase_id]
                    ).join(", ")}
                  </span>
                  {targetIsSaving ? <LoaderCircle className="spin" size={16} /> : <ChevronRight size={16} />}
                </summary>
                <fieldset className="wp-kb-options">
                  <legend className="sr-only">Ziel-Wissensbereiche für {task.title}</legend>
                  {kbs.map((base) => (
                    <label key={base.knowledgebase_id}>
                      <input
                        type="checkbox"
                        checked={selectedTargetIds.includes(base.knowledgebase_id)}
                        disabled={targetIsSaving}
                        onChange={(event) => {
                          const current = selectedTargetIds;
                          const next = event.target.checked
                            ? [...current, base.knowledgebase_id]
                            : current.filter((id) => id !== base.knowledgebase_id);
                          void changeTargetKnowledgebases(task.case_id, [...new Set(next)]);
                        }}
                      />
                      {base.label}
                    </label>
                  ))}
                </fieldset>
              </details>
            ) : (
              <strong>
                {(task.target_knowledgebase_labels || [task.target_knowledgebase_label || task.target_knowledgebase_id]).join(", ")}
              </strong>
            )}
          </div>
          {task.target_knowledgebase_history?.length ? (
            <div className="wp-target-history" aria-label="Verlauf des Ziel-Wissensbereichs">
              {task.target_knowledgebase_history.map((entry, index) => (
                <div key={`${entry.selected_at}-${entry.knowledgebase_ids.join("-")}-${index}`}>
                  <span>
                    {index === 0
                      ? "Vom Nutzer ausgewählt"
                      : `Von ${roleLabel((entry.selected_by_role || "manager") as Role)} ${entry.selected_by_name} geändert`}
                  </span>
                  <strong>{entry.knowledgebase_labels.join(", ")}</strong>
                </div>
              ))}
            </div>
          ) : null}
          {!!task.duplicate_matches?.length && (
            <div className="wp-duplicate-review" role="note">
              <strong>
                {task.requested_action === "replace"
                  ? "Als neue Version ausgewählt"
                  : "Ähnliches vorhandenes Dokument erkannt"}
              </strong>
              {task.duplicate_matches.map((match) => (
                <div key={match.document_id}>
                  <span>
                    <b>{match.title}</b>
                    {match.relation === "exact_duplicate"
                      ? " · identischer Inhalt"
                      : " · möglicher Versionsvorgänger"}
                    {match.has_conflict ? " · inhaltliche Abweichungen erkannt" : ""}
                  </span>
                  <a className="wp-secondary" href={match.original_url} target="_blank" rel="noreferrer">
                    Vorhandenes Dokument prüfen
                  </a>
                </div>
              ))}
              {task.requested_action === "replace" && (
                <small>
                  Bei Freigabe wird die bisher aktive Fassung durch diese Version ersetzt. Die alte Version bleibt im Versionsverlauf erhalten.
                </small>
              )}
            </div>
          )}
          <p className="wp-reason">
            {own
              ? isAdmin
                ? "Schritt 1 von 2: Wähle zuerst die gewünschte Dokumentaktion. Danach erscheinen die eigentlichen Adminoptionen zum Freigeben oder Ablehnen."
                : "Wähle, wie es weitergehen soll. Danach geht der Vorgang zur Freigabe."
              : reviewReason[task.status] || "Wartet auf eine Entscheidung."}
          </p>
          {task.status === "ready_to_activate" && task.publication_error && (
            <div className="wp-alert wp-publication-error" role="alert">
              <AlertTriangle />
              <div>
                <strong>Technische Veröffentlichung fehlgeschlagen</strong>
                <span>
                  Die Freigabe ist gespeichert, aber Vinci konnte das Dokument noch nicht indexieren.
                  Du kannst die Veröffentlichung erneut versuchen.
                </span>
              </div>
            </div>
          )}
          {task.requires_admin && !(own && task.duplicate_matches?.some((match) => match.relation === "version_candidate")) && (
            <span className="wp-escalated">
              <AlertTriangle /> Adminentscheidung erforderlich
            </span>
          )}
          {task.restricted_terms && task.restricted_terms.length > 0 && (
            <div className="wp-alert">
              <AlertTriangle />
              <div>
                <strong>Gesperrter Begriff gefunden</strong>
                <span>Treffer: {task.restricted_terms.join(", ")}</span>
                <small>
                  Dieses Dokument bleibt bis zu deiner ausdrücklichen
                  Adminentscheidung gesperrt.
                </small>
              </div>
            </div>
          )}
          {task.sanitized_for_review && (
            <div className="wp-alert" role="alert">
              <ShieldCheck />
              <div>
                <strong>Bereinigte Fassung zur Sicherheitsprüfung</strong>
                <span>
                  Die ursprüngliche PDF-Datei enthielt aktive oder eingebettete Inhalte.
                  Diese wurden entfernt. Prüfe die sichtbare, bereinigte Fassung und das
                  erzeugte Markdown, bevor du sie freigibst.
                </span>
                <small>Die ursprünglichen aktiven Inhalte werden nicht veröffentlicht.</small>
              </div>
            </div>
          )}
          <div className="wp-task-buttons">
            <button
              className="wp-secondary"
              onClick={() => void openReview(task.case_id)}
            >
              Original und Markdown prüfen
            </button>
            {!own && task.status.includes("approval") && (
              <button
                className="wp-secondary"
                disabled={inquiryBusy}
                onClick={() => void openInquiry(task)}
              >
                <MessageCircle size={16} /> Rückfrage stellen
              </button>
            )}
            {!own && task.status === "ready_to_activate" && (
              <button
                className="wp-secondary approve"
                disabled={Boolean(busy)}
                onClick={() => void decide(task.case_id, "approve")}
              >
                {busy === task.case_id
                  ? "Veröffentlichung läuft …"
                  : "Veröffentlichung erneut versuchen"}
              </button>
            )}
            {own && (
              <>
                {task.status === "duplicate_blocked" ? (
                  <button
                    className="wp-secondary approve"
                    disabled={busy === task.case_id}
                    onClick={() =>
                      void chooseAction(task.case_id, "publish_existing")
                    }
                  >
                    Vorhandenes zusätzlich veröffentlichen
                  </button>
                ) : (
                  <>
                    {task.duplicate_matches
                      ?.filter((match) => match.relation === "version_candidate")
                      .map((match) => (
                        <button
                          key={match.document_id}
                          className="wp-secondary approve"
                          disabled={busy === task.case_id}
                          onClick={() => void chooseAction(task.case_id, "replace", match.document_id)}
                        >
                          Als neue Version von „{match.title}“ vorschlagen
                        </button>
                      ))}
                    <button
                      className="wp-secondary"
                      disabled={busy === task.case_id}
                      onClick={() => void chooseNewDocument(task)}
                    >
                      Als eigenständiges Dokument vorschlagen
                    </button>
                  </>
                )}
                <button
                  className="wp-secondary"
                  disabled={busy === task.case_id}
                  onClick={() => void chooseAction(task.case_id, "discard")}
                >
                  Verwerfen
                </button>
              </>
            )}
          </div>
          {decisionFeedback[task.case_id] && (
            <p className="wp-message" role="status" aria-live="polite">
              {decisionFeedback[task.case_id]}
            </p>
          )}
        </div>
        {!own && canDecide && task.status.includes("approval") && (
          <div className="wp-task-actions">
            <textarea
              placeholder="Begründung – nur bei Ablehnung oder Weiterleitung erforderlich"
              value={reason[task.case_id] || ""}
              onChange={(e) =>
                setReason({ ...reason, [task.case_id]: e.target.value })
              }
            />
            <div>
              <button
                disabled={Boolean(busy) || (reason[task.case_id] || "").trim().length < 3}
                onClick={() => void decide(task.case_id, "reject")}
              >
                Ablehnen
              </button>
              <button
                disabled={Boolean(busy) || (reason[task.case_id] || "").trim().length < 3}
                onClick={() => void decide(task.case_id, "escalate")}
              >
                Weiterleiten
              </button>
              <button
                className="approve"
                disabled={Boolean(busy)}
                onClick={() => void decide(task.case_id, "approve")}
              >
                {busy === task.case_id ? "Freigabe läuft …" : "Freigeben"}
              </button>
            </div>
          </div>
        )}
      </article>
    );
  }

  return (
    <section className="wp-page">
      {inquiryCase && (
        <div className="wp-confirm-backdrop" role="presentation">
          <section
            className="wp-confirm-dialog wp-inquiry-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="inquiry-title"
          >
            <div className="wp-confirm-icon"><MessageCircle /></div>
            <h2 id="inquiry-title">Rückfrage stellen</h2>
            <p>Dokument: <strong>{inquiryCase.title}</strong></p>
            {inquiryParticipants.length ? (
              <>
                <label>
                  Ansprechpartner
                  <select
                    value={inquiryRecipient}
                    onChange={(event) => setInquiryRecipient(event.target.value)}
                  >
                    {inquiryParticipants.map((participant) => (
                      <option key={participant.user_id} value={participant.user_id}>
                        {participant.display_name} ({participant.email})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Deine Rückfrage
                  <textarea
                    autoFocus
                    value={inquiryQuestion}
                    onChange={(event) => setInquiryQuestion(event.target.value)}
                    placeholder="Was möchtest du zu diesem Dokument klären?"
                  />
                </label>
                {inquiryMessage && <p className="wp-message" role="status">{inquiryMessage}</p>}
                <div className="wp-confirm-actions">
                  <button type="button" onClick={() => setInquiryCase(null)}>Schließen</button>
                  <button
                    type="button"
                    className="wp-primary"
                    disabled={inquiryBusy || !inquiryRecipient || inquiryQuestion.trim().length < 3}
                    onClick={() => void sendInquiry()}
                  >
                    <Send size={16} /> Rückfrage senden
                  </button>
                </div>
              </>
            ) : (
              <>
                <p>Für diesen Vorgang ist kein weiterer aktiver Ansprechpartner hinterlegt.</p>
                <div className="wp-confirm-actions">
                  <button type="button" onClick={() => setInquiryCase(null)}>Schließen</button>
                </div>
              </>
            )}
          </section>
        </div>
      )}
      <Title
        eyebrow="Arbeitsvorrat"
        title={
          session.role === "employee" ? "Meine Vorgänge" : "Offene Freigaben"
        }
        text="Du siehst nur Vorgänge, für die du zuständig bist."
      />
      {publishing.length > 0 && (
        <>
          <h2>Veröffentlichung läuft</h2>
          <p className="wp-subtle">
            Die Entscheidung ist sicher gespeichert. Du kannst weiterarbeiten;
            nach Abschluss erhältst du eine Mitteilung.
          </p>
          <div className="wp-task-list wp-publishing-list">
            {publishing.map((task) => (
              <article key={task.case_id} aria-busy="true">
                <div className="wp-task-icon"><LoaderCircle className="spin" /></div>
                <div className="wp-task-copy">
                  <span className="wp-badge">In Bearbeitung</span>
                  <h2>{task.title}</h2>
                  <p>{task.original_filename}</p>
                </div>
              </article>
            ))}
          </div>
        </>
      )}
      {mine.length > 0 && (
        <>
          <h2>Deine Uploads · Entscheidung offen</h2>
          <div className="wp-task-list">
            {mine.map((task) => card(task, true))}
          </div>
        </>
      )}
      {toReview.length > 0 && (
        <>
          <h2>
            {session.role === "employee"
              ? "Aufbereitung prüfen und kommentieren"
              : "Zur Freigabe durch dich"}
          </h2>
          <div className="wp-task-list">
            {toReview.map((task) => card(task, false))}
          </div>
        </>
      )}
      {availableTasks.length === 0 && publishing.length === 0 && (
        <div className="wp-empty">
          <CheckCircle2 />
          <h2>Alles erledigt</h2>
          <p>Aktuell wartet kein Vorgang auf dich.</p>
        </div>
      )}
    </section>
  );
}

function SearchableUserPicker({
  label,
  emptyLabel,
  value,
  users,
  onChange,
}: {
  label: string;
  emptyLabel: string;
  value: string;
  users: PortalUser[];
  onChange: (userId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const selectedUser = users.find((user) => user.user_id === value);
  const normalizedQuery = query.trim().toLocaleLowerCase("de");
  const matches = users.filter((user) =>
    !normalizedQuery || `${user.display_name} ${user.email}`.toLocaleLowerCase("de").includes(normalizedQuery),
  );
  function choose(userId: string, target: HTMLElement) {
    onChange(userId);
    setQuery("");
    const details = target.closest("details");
    if (details instanceof HTMLDetailsElement) details.open = false;
  }
  return (
    <div className="wp-user-assignment-field">
      <span>{label}</span>
      <details className="wp-kb-multiselect wp-owner-picker wp-user-assignment-picker">
        <summary>
          <span>{selectedUser?.display_name || emptyLabel}</span>
          <ChevronRight size={16} />
        </summary>
        <fieldset className="wp-kb-options">
          <legend className="sr-only">{label} auswählen</legend>
          <input
            className="wp-feedback-document-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Name oder E-Mail suchen …"
            aria-label={`${label} suchen`}
          />
          {!normalizedQuery && (
            <button type="button" className={!value ? "selected" : ""} onClick={(event) => choose("", event.currentTarget)}>
              {emptyLabel}
            </button>
          )}
          {matches.map((user) => (
            <button type="button" key={user.user_id} className={value === user.user_id ? "selected" : ""}
              onClick={(event) => choose(user.user_id, event.currentTarget)}>
              <span>{user.display_name}<small>{user.email}</small></span>
            </button>
          ))}
          {matches.length === 0 && <small className="wp-user-assignment-empty">Kein passender Benutzer gefunden.</small>}
        </fieldset>
      </details>
    </div>
  );
}

function UserAdmin({
  users,
  session,
  done,
}: {
  users: PortalUser[];
  session: Session;
  done: () => Promise<void>;
}) {
  const confirm = useConfirmation();
  const [selected, setSelected] = useState(users[0]?.user_id || ""),
    [access, setAccess] = useState<UserAccess[]>([]),
    [userQuery, setUserQuery] = useState("");
  const [managerId, setManagerId] = useState(""),
    [delegations, setDelegations] = useState<Delegation[]>([]),
    [delegateId, setDelegateId] = useState(""),
    [ownerPermission, setOwnerPermission] = useState(false);
  const [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [dirty, setDirty] = useState(false),
    [pendingRole, setPendingRole] = useState<Role | null>(null);
  const [absences, setAbsences] = useState<Absence[]>([]),
    [absenceManager, setAbsenceManager] = useState(""),
    [delegate, setDelegate] = useState(""),
    [absentFrom, setAbsentFrom] = useState(""),
    [absentUntil, setAbsentUntil] = useState(""),
    [absenceReason, setAbsenceReason] = useState("");
  const managers = users.filter(
    (user) =>
      ["manager", "admin", "portal_admin"].includes(user.role) && user.active,
  );
  const current = users.find((user) => user.user_id === selected);
  const visibleUsers = users.filter((user) => {
    const query = userQuery.trim().toLocaleLowerCase("de");
    return (
      !query ||
      user.display_name.toLocaleLowerCase("de").includes(query) ||
      user.email.toLocaleLowerCase("de").includes(query) ||
      roleLabel(user.role).toLocaleLowerCase("de").includes(query)
    );
  });
  const userName = (id?: string) =>
    users.find((user) => user.user_id === id)?.display_name || "Unbekannt";

  const loadAbsences = useCallback(
    async () =>
      setAbsences(
        (await api<{ absences: Absence[] }>("/portal/admin/absences")).absences,
      ),
    [],
  );
  useEffect(() => {
    let active = true;
    void api<{ absences: Absence[] }>("/portal/admin/absences").then(
      (payload) => {
        if (active) setAbsences(payload.absences);
      },
    );
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (!selected || !current) return;
    let active = true;
    void Promise.all([
      api<{ access: UserAccess[] }>(
        `/portal/admin/users/${selected}/knowledgebase-access`,
      ),
      api<{ allowed: boolean }>(
        `/portal/admin/users/${selected}/owner-proposal-permission`,
      ),
      api<{ delegations: Delegation[] }>("/portal/admin/delegations"),
    ])
      .then(([accessPayload, ownerPayload, delegationPayload]) => {
        if (!active) return;
        setManagerId(current.manager_user_id || "");
        setDirty(false);
        setMessage("");
        setAccess(accessPayload.access);
        setOwnerPermission(ownerPayload.allowed);
        setDelegations(delegationPayload.delegations);
        setDelegateId(delegationPayload.delegations.find(
          (item) => item.manager_user_id === selected && !item.valid_from && !item.valid_until,
        )?.delegate_user_id || "");
      })
      .catch((cause) => {
        if (active)
          setMessage(
            friendlyError(cause, "Benutzerdaten konnten nicht geladen werden."),
          );
      });
    return () => {
      active = false;
    };
  }, [selected, current]);

  function beginRoleChange(role: Role) {
    if (!current || role === current.role) return;
    setPendingRole(role);
    setMessage("");
  }
  async function confirmRoleChange() {
    if (!current || !pendingRole) return;
    const approved = await confirm({
      title: "Rolle ändern?",
      description: `${current.display_name} wird von ${roleLabel(current.role)} zu ${roleLabel(pendingRole)} geändert. Möchtest du diese Rollenänderung wirklich durchführen?`,
      confirmLabel: "Rolle ändern",
      danger: ["admin", "portal_admin"].includes(current.role),
    });
    if (!approved) return;
    setBusy(true);
    try {
      await api(`/portal/admin/users/${current.user_id}/role`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: pendingRole, confirmed: true }),
      });
      setPendingRole(null);
      setMessage(`Die Rolle von ${current.display_name} wurde geändert.`);
      await done();
    } catch (cause) {
      setMessage(friendlyError(cause, "Rollenänderung fehlgeschlagen"));
    } finally {
      setBusy(false);
    }
  }
  function changeAccess(
    item: UserAccess,
    field: "can_read" | "can_upload",
    value: boolean,
  ) {
    setAccess((rows) =>
      rows.map((row) =>
        row.knowledgebase_id === item.knowledgebase_id
          ? { ...row, [field]: value }
          : row,
      ),
    );
    setDirty(true);
  }
  async function saveUser() {
    if (!current) return;
    setBusy(true);
    setMessage("");
    try {
      await api(`/portal/admin/users/${current.user_id}/manager`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ manager_user_id: managerId || null }),
      });
      const existingDelegate = delegations.find(
        (item) => item.manager_user_id === current.user_id && !item.valid_from && !item.valid_until,
      );
      if (existingDelegate && existingDelegate.delegate_user_id !== delegateId)
        await api(`/portal/admin/delegations?manager_user_id=${encodeURIComponent(current.user_id)}&delegate_user_id=${encodeURIComponent(existingDelegate.delegate_user_id)}`, { method: "DELETE" });
      if (delegateId && existingDelegate?.delegate_user_id !== delegateId)
        await api("/portal/admin/delegations", {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ manager_user_id: current.user_id, delegate_user_id: delegateId }),
        });
      await api(
        `/portal/admin/users/${current.user_id}/owner-proposal-permission`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ allowed: ownerPermission }),
        },
      );
      await Promise.all(
        access.map((item) =>
          api(`/portal/admin/users/${current.user_id}/knowledgebase-access`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              knowledgebase_id: item.knowledgebase_id,
              can_read: Boolean(item.can_read),
              can_upload: Boolean(item.can_upload),
            }),
          }),
        ),
      );
      setDirty(false);
      setMessage(`Änderungen für ${current.display_name} wurden gespeichert.`);
      await done();
    } catch (cause) {
      setMessage(
        friendlyError(cause, "Änderungen konnten nicht gespeichert werden."),
      );
    } finally {
      setBusy(false);
    }
  }
  async function saveAbsence() {
    if (
      !absenceManager ||
      !delegate ||
      !absentFrom ||
      !absentUntil ||
      absenceReason.trim().length < 3
    )
      return setMessage(
        "Bitte Führungskraft, Vertretung, Zeitraum und Grund vollständig angeben.",
      );
    setBusy(true);
    setMessage("");
    try {
      await api("/portal/admin/absences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          manager_user_id: absenceManager,
          delegate_user_id: delegate,
          absent_from: absentFrom,
          absent_until: absentUntil,
          reason: absenceReason.trim(),
        }),
      });
      setAbsenceManager("");
      setDelegate("");
      setAbsentFrom("");
      setAbsentUntil("");
      setAbsenceReason("");
      await loadAbsences();
      setMessage("Abwesenheit und Vertretung wurden gemeinsam gespeichert.");
    } catch (cause) {
      setMessage(
        friendlyError(cause, "Abwesenheit konnte nicht gespeichert werden."),
      );
    } finally {
      setBusy(false);
    }
  }
  async function removeAbsence(managerUserId: string) {
    setBusy(true);
    try {
      await api("/portal/admin/absences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          manager_user_id: managerUserId,
          delegate_user_id: null,
          absent_from: null,
          absent_until: null,
          reason: "Entfernt",
        }),
      });
      await loadAbsences();
      setMessage("Abwesenheit wurde entfernt.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="wp-page">
      <Title
        eyebrow="Administration"
        title="Benutzer und Rechte"
        text="Wähle links einen Benutzer aus und bearbeite seine Zuordnung und Rechte direkt daneben."
      />
      {message && <p className="wp-message">{message}</p>}
      <div className="wp-user-admin-layout">
        <aside className="wp-user-directory" aria-label="Benutzer auswählen">
          <div className="wp-section-head">
            <div>
              <span>Benutzer</span>
              <strong>{users.length} Konten</strong>
            </div>
            <label className="wp-user-search">
              <span>Benutzer suchen</span>
              <input
                type="search"
                value={userQuery}
                placeholder="Name, E-Mail oder Rolle"
                onChange={(event) => setUserQuery(event.target.value)}
              />
            </label>
          </div>
          {visibleUsers.map((user) => (
            <button
              type="button"
              key={user.user_id}
              className={selected === user.user_id ? "selected" : ""}
              onClick={() => {
                setSelected(user.user_id);
                setPendingRole(null);
              }}
            >
              <span className="wp-avatar">
                {user.display_name.slice(0, 2).toUpperCase()}
              </span>
              <span>
                <strong>{user.display_name}</strong>
                <small>{user.email}</small>
                <em>
                  {
                    (
                      {
                        employee: "Mitarbeiter",
                        manager: "Führungskraft",
                        admin: "Admin",
                        portal_admin: "Portal-Admin",
                      } as Record<string, string>
                    )[user.role]
                  }
                </em>
              </span>
              <ChevronRight />
            </button>
          ))}
          {visibleUsers.length === 0 && (
            <p className="wp-user-directory-empty">
              Kein passender Benutzer gefunden.
            </p>
          )}
        </aside>
        {current ? (
          <div className="wp-user-detail">
            <div className="wp-user-detail-head">
              <div className="wp-avatar large">
                {current.display_name.slice(0, 2).toUpperCase()}
              </div>
              <div>
                <span>Ausgewählter Benutzer</span>
                <h2>{current.display_name}</h2>
                <p>{current.email}</p>
              </div>
              <Badge status={current.active ? "active" : "Deaktiviert"} />
            </div>
            <div className="wp-settings-section">
              <h3>Rolle und Zuordnung</h3>
              <div className="wp-grid">
                <label>
                  Rolle
                  <select
                    value={pendingRole ?? current.role}
                    disabled={
                      session.role !== "portal_admin" &&
                      ["admin", "portal_admin"].includes(current.role)
                    }
                    onChange={(e) => beginRoleChange(e.target.value as Role)}
                  >
                    <option value="employee">Mitarbeiter</option>
                    <option value="manager">Führungskraft</option>
                    <option value="admin">Admin</option>
                    {session.role === "portal_admin" && (
                      <option value="portal_admin">Portal-Admin</option>
                    )}
                  </select>
                  <small>Jede Rollenänderung wird vor dem Speichern noch einmal bestätigt.</small>
                </label>
                <SearchableUserPicker
                  label="Zugeordnete Führungskraft"
                  emptyLabel="Keine Führungskraft"
                  value={managerId}
                  users={managers.filter((user) => user.user_id !== current.user_id)}
                  onChange={(userId) => { setManagerId(userId); setDirty(true); }}
                />
                {["manager", "admin", "portal_admin"].includes(pendingRole ?? current.role) && (
                  <SearchableUserPicker
                    label="Zugeordnete Vertretung"
                    emptyLabel="Keine Vertretung"
                    value={delegateId}
                    users={users.filter((user) => user.active && user.user_id !== current.user_id)}
                    onChange={(userId) => { setDelegateId(userId); setDirty(true); }}
                  />
                )}
              </div>
              {pendingRole && (
                <button
                  type="button"
                  className="wp-primary"
                  onClick={() => void confirmRoleChange()}
                  disabled={busy}
                >
                  Rollenänderung prüfen
                </button>
              )}
              <label className="wp-check-row">
                <input
                  type="checkbox"
                  checked={ownerPermission}
                  onChange={(e) => {
                    setOwnerPermission(e.target.checked);
                    setDirty(true);
                  }}
                />
                <span>
                  <strong>Andere Dokument-Owner vorschlagen</strong>
                  <small>
                    Der Benutzer darf beim Upload eine andere verantwortliche
                    Person auswählen.
                  </small>
                </span>
              </label>
            </div>
            <div className="wp-settings-section">
              <h3>Wissensbereiche</h3>
              <p>
                Lege fest, welche Bereiche gelesen und mit neuen Dokumenten
                ergänzt werden dürfen.
              </p>
              <div className="wp-access-grid">
                {access.map((item) => (
                  <article key={item.knowledgebase_id}>
                    <div>
                      <strong>{item.label}</strong>
                      <small>{item.knowledgebase_id}</small>
                    </div>
                    <label>
                      <input
                        type="checkbox"
                        checked={Boolean(item.can_read)}
                        onChange={(e) =>
                          changeAccess(item, "can_read", e.target.checked)
                        }
                      />{" "}
                      Lesen
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={Boolean(item.can_upload)}
                        onChange={(e) =>
                          changeAccess(item, "can_upload", e.target.checked)
                        }
                      />{" "}
                      Hochladen
                    </label>
                  </article>
                ))}
              </div>
            </div>
            <div className="wp-savebar">
              <span>
                {dirty
                  ? "Ungespeicherte Änderungen"
                  : "Alle Änderungen gespeichert"}
              </span>
              <button
                className="wp-primary"
                disabled={!dirty || busy}
                onClick={() => void saveUser()}
              >
                {busy ? <LoaderCircle className="spin" /> : <CheckCircle2 />}{" "}
                Änderungen speichern
              </button>
            </div>
          </div>
        ) : (
          <div className="wp-empty-hint">Bitte wähle einen Benutzer aus.</div>
        )}
      </div>
      <div className="wp-absence-section">
        <div className="wp-section-head">
          <div>
            <span>Freigabevertretung</span>
            <h2>Abwesenheit eintragen</h2>
            <p>
              Zeitraum und Vertretung werden gemeinsam gespeichert. Neue
              Freigaben gehen während der Abwesenheit sofort an die Vertretung.
            </p>
          </div>
        </div>
        <div className="wp-absence-form">
          <label>
            Abwesende Führungskraft
            <select
              value={absenceManager}
              onChange={(e) => setAbsenceManager(e.target.value)}
            >
              <option value="">Bitte wählen</option>
              {managers.map((user) => (
                <option key={user.user_id} value={user.user_id}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Vertretung
            <select
              value={delegate}
              onChange={(e) => setDelegate(e.target.value)}
            >
              <option value="">Bitte wählen</option>
              {users
                .filter(
                  (user) => user.active && user.user_id !== absenceManager,
                )
                .map((user) => (
                  <option key={user.user_id} value={user.user_id}>
                    {user.display_name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Von
            <input
              type="date"
              value={absentFrom}
              onChange={(e) => setAbsentFrom(e.target.value)}
            />
          </label>
          <label>
            Bis
            <input
              type="date"
              value={absentUntil}
              onChange={(e) => setAbsentUntil(e.target.value)}
            />
          </label>
          <label className="wide">
            Grund
            <input
              value={absenceReason}
              onChange={(e) => setAbsenceReason(e.target.value)}
              placeholder="z. B. Urlaub oder Fortbildung"
            />
          </label>
          <button
            className="wp-primary"
            disabled={busy}
            onClick={() => void saveAbsence()}
          >
            <CheckCircle2 /> Abwesenheit speichern
          </button>
        </div>
        <div className="wp-absence-list">
          {absences.length ? (
            absences.map((item) => (
              <article key={item.manager_user_id}>
                <div className="wp-avatar">
                  {userName(item.manager_user_id).slice(0, 2).toUpperCase()}
                </div>
                <div>
                  <strong>{userName(item.manager_user_id)}</strong>
                  <span>
                    {item.absent_from} bis {item.absent_until === "9999-12-31" ? "auf Weiteres" : item.absent_until} · {item.reason}
                  </span>
                  <small>Vertretung: {userName(item.delegate_user_id)}</small>
                  {item.source === "outlook" && <small>Automatisch mit Outlook synchronisiert</small>}
                </div>
                {item.source !== "outlook" && (
                  <button
                    className="wp-outline-button"
                    disabled={busy}
                    onClick={() => void removeAbsence(item.manager_user_id)}
                  >
                    Entfernen
                  </button>
                )}
              </article>
            ))
          ) : (
            <p className="wp-empty-hint">
              Aktuell sind keine Abwesenheiten eingetragen.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function countList(
  counts: Record<string, number> | undefined,
  labels: Record<string, string>,
  empty: string,
) {
  const rows = Object.entries(counts || {});
  if (!rows.length) return <p className="wp-empty-hint">{empty}</p>;
  return (
    <div className="wp-counts">
      {rows.map(([key, value]) => (
        <article key={key}>
          <strong>{value}</strong>
          <span>{labels[key] || key}</span>
        </article>
      ))}
    </div>
  );
}

function AuditView({
  entries,
  users: _users,
}: {
  entries: AuditEntry[];
  users: PortalUser[];
}) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase("de");
  const visibleEntries = entries.filter((entry) => {
    if (!normalizedQuery) return true;
    return [
      entry.actor_name,
      entry.event_label,
      entry.subject_label,
      entry.details_label,
      entry.event_type,
    ].some((value) => value.toLocaleLowerCase("de").includes(normalizedQuery));
  });
  return (
    <section className="wp-page">
      <Title
        eyebrow="Nachvollziehbarkeit"
        title="Auditprotokoll"
        text="Kritische Aktionen aus Rollenverwaltung und Dokumentlebenszyklus in einer gemeinsamen Ansicht."
      />
      <label className="wp-audit-search">
        <span>Auditprotokoll durchsuchen</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Zum Beispiel Dokument, Wissensbereich, Nutzer oder Aktion"
        />
      </label>
      <div className="wp-actions">
        <a className="wp-primary" href={`${API}/portal/admin/audit/export.csv`}>
          CSV exportieren
        </a>
        <a className="wp-primary" href={`${API}/portal/admin/audit/export.pdf`}>
          PDF exportieren
        </a>
      </div>
      <p className="wp-audit-result-count" role="status">
        {visibleEntries.length} {visibleEntries.length === 1 ? "Eintrag" : "Einträge"} angezeigt
      </p>
      <div className="wp-task-list">
        {visibleEntries.map((entry, index) => (
          <article key={`${entry.occurred_at}-${index}`}>
            <div className="wp-task-icon">
              <ShieldCheck />
            </div>
            <div className="wp-task-copy">
              <Badge status={entry.event_type} />
              <h2>{entry.event_label}</h2>
              <span><strong>Betroffen:</strong> {entry.subject_label}</span>
              {entry.details_label !== "Keine weiteren Angaben" && (
                <span><strong>Änderung:</strong> {entry.details_label}</span>
              )}
              <p>
                {new Date(entry.occurred_at).toLocaleString("de-DE")} ·{" "}
                ausgeführt von {entry.actor_name}
              </p>
            </div>
          </article>
        ))}
        {!visibleEntries.length && (
          <p className="wp-empty-hint">Zu dieser Suche wurden keine Audit-Einträge gefunden.</p>
        )}
      </div>
    </section>
  );
}

function FeedbackForm() {
  const [context, setContext] = useState<FeedbackContext | null>(null),
    [options, setOptions] = useState<FeedbackOptions>({ documents: [], knowledgebases: [] }),
    [documentIds, setDocumentIds] = useState<string[]>([]),
    [knowledgebaseIds, setKnowledgebaseIds] = useState<string[]>([]),
    [documentSearch, setDocumentSearch] = useState(""),
    [reason, setReason] = useState("incorrect"),
    [comment, setComment] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [success, setSuccess] = useState(false);
  const [attachments, setAttachments] = useState<File[]>([]);
  const screenshotInput = useRef<HTMLInputElement>(null);
  function pasteScreenshot(event: ReactClipboardEvent<HTMLTextAreaElement>) {
    const image = Array.from(event.clipboardData.items).find((item) => item.type.startsWith("image/"));
    const file = image?.getAsFile();
    if (!file) return;
    event.preventDefault();
    const extension = file.type === "image/png" ? "png" : "jpg";
    if (attachments.length >= 5) {
      setMessage("Du kannst höchstens fünf Dateien anhängen.");
      return;
    }
    setAttachments((current) => [...current, new File(
      [file], `screenshot-${Date.now()}.${extension}`, { type: file.type },
    )].slice(0, 5));
    setMessage("Screenshot aus der Zwischenablage übernommen.");
  }
  useEffect(() => {
    const params = new URLSearchParams(window.location.search),
      chatId = params.get("chat_id"),
      messageId = params.get("message_id"),
      linkedDocumentIds = (params.get("document_ids") || "").split(",").filter(Boolean),
      linkedKnowledgebaseIds = (params.get("knowledgebase_ids") || "").split(",").filter(Boolean);
    void api<FeedbackOptions>("/portal/feedback/options")
      .then((loaded) => {
        setOptions(loaded);
        setDocumentIds(linkedDocumentIds.filter((id) => loaded.documents.some((item) => item.document_id === id)));
        setKnowledgebaseIds(linkedKnowledgebaseIds.filter((id) => loaded.knowledgebases.some((item) => item.knowledgebase_id === id)));
      })
      .catch(() => undefined);
    if (!chatId || !messageId) return;
    void api<FeedbackContext>(
      `/portal/feedback/context?chat_id=${encodeURIComponent(chatId)}&message_id=${encodeURIComponent(messageId)}`,
    )
      .then((loaded) => {
        setContext(loaded);
        setOptions({ documents: loaded.documents, knowledgebases: loaded.knowledgebases });
        setDocumentIds((linkedDocumentIds.length ? linkedDocumentIds : loaded.document_ids || [])
          .filter((id) => loaded.documents.some((item) => item.document_id === id)));
        setKnowledgebaseIds((linkedKnowledgebaseIds.length ? linkedKnowledgebaseIds : loaded.knowledgebase_ids || [])
          .filter((id) => loaded.knowledgebases.some((item) => item.knowledgebase_id === id)));
      })
      .catch(() =>
        setMessage(
          "Der Chatkontext konnte nicht automatisch geladen werden. Bitte beschreibe den Fehler kurz.",
        ),
      );
  }, []);
  async function submit() {
    setBusy(true);
    setMessage("");
    const reportContext = context || {
      question: "", answer: "", sources: [], passages: [],
      runtime: { source: "knowledge_portal" }, request_id: crypto.randomUUID(),
    };
    try {
      const result = await api<{ feedback_id: string }>("/portal/feedback/rag", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...reportContext, reason, comment,
          document_ids: documentIds, knowledgebase_ids: knowledgebaseIds,
        }),
      });
    // Der Anhang folgt der Meldung, weil er ihre Kennung braucht. Schlaegt er
    // fehl, bleibt die Meldung bestehen und der Fehler wird benannt.
      if (attachments.length) {
        try {
          for (const attachment of attachments) {
            const form = new FormData();
            form.append("file", attachment);
            const response = await fetch(
              `${API}/portal/feedback/${result.feedback_id}/screenshot`,
              { method: "POST", credentials: "include", body: form },
            );
            if (!response.ok) {
              const body = await response.json().catch(() => ({}));
              throw new Error(body.detail || `request_${response.status}`);
            }
          }
        } catch (cause) {
          setAttachments([]);
          setComment("");
          return setMessage(
            `Deine Meldung wurde gespeichert, mindestens eine Datei konnte aber nicht angehängt werden: ${friendlyError(cause, "unbekannter Grund")}`,
          );
        }
      }
      setComment("");
      setAttachments([]);
      setSuccess(true);
    } catch (cause) {
      setMessage(friendlyError(cause, "Die Meldung konnte nicht gesendet werden."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="wp-page narrow">
      <Title
        eyebrow="Qualität sichern"
        title="Wissensfehler melden"
        text="Frage, Antwort, Quellen und technische Versionen werden automatisch aus dem zugehörigen Chat übernommen."
      />
      <div className="wp-form">
        <label>
          Was ist aufgefallen?
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="incorrect">Information ist falsch</option>
            <option value="outdated">Information ist veraltet</option>
            <option value="conflicting_sources">
              Quellen widersprechen sich
            </option>
            <option value="irrelevant_source">
              Quelle passt nicht zur Frage
            </option>
            <option value="suspected_permission_issue">
              Ich durfte diese Information vermutlich nicht sehen
            </option>
            <option value="other">Sonstiges</option>
          </select>
        </label>
        <label>
          Ergänzung
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onPaste={pasteScreenshot}
            placeholder="Was genau sollten wir prüfen?"
          />
          <small className="wp-hint">Du kannst einen kopierten Screenshot hier mit Strg+V einfügen.</small>
        </label>
        <div className="wp-feedback-references">
          <div className="wp-kb-field">
            <span>Betroffene Wissensbereiche (optional)</span>
            <details className="wp-kb-multiselect">
              <summary>
                <span>{knowledgebaseIds.length
                  ? options.knowledgebases.filter((item) => knowledgebaseIds.includes(item.knowledgebase_id)).map((item) => item.label).join(", ")
                  : "Keine ausgewählt"}</span>
                <ChevronRight size={16} />
              </summary>
              <fieldset className="wp-kb-options">
                <legend className="sr-only">Betroffene Wissensbereiche auswählen</legend>
                {options.knowledgebases.map((item) => (
                  <label key={item.knowledgebase_id}>
                    <input type="checkbox" checked={knowledgebaseIds.includes(item.knowledgebase_id)}
                      onChange={(event) => setKnowledgebaseIds((current) => event.target.checked
                        ? [...current, item.knowledgebase_id]
                        : current.filter((id) => id !== item.knowledgebase_id))} />
                    {item.label}
                  </label>
                ))}
              </fieldset>
            </details>
          </div>
          <div className="wp-kb-field">
            <span>Betroffene Dokumente (optional)</span>
            <details className="wp-kb-multiselect">
              <summary>
                <span>{documentIds.length
                  ? options.documents.filter((item) => documentIds.includes(item.document_id)).map((item) => item.title).join(", ")
                  : "Keine ausgewählt"}</span>
                <ChevronRight size={16} />
              </summary>
              <fieldset className="wp-kb-options">
                <legend className="sr-only">Betroffene Dokumente auswählen</legend>
                <input
                  className="wp-feedback-document-search"
                  type="search"
                  value={documentSearch}
                  onChange={(event) => setDocumentSearch(event.target.value)}
                  placeholder="Dokument suchen …"
                  aria-label="Dokument suchen"
                />
                {options.documents.filter((item) =>
                  item.title.toLocaleLowerCase("de").includes(documentSearch.trim().toLocaleLowerCase("de")),
                ).map((item) => (
                  <label key={item.document_id}>
                    <input type="checkbox" checked={documentIds.includes(item.document_id)}
                      onChange={(event) => setDocumentIds((current) => event.target.checked
                        ? [...current, item.document_id]
                        : current.filter((id) => id !== item.document_id))} />
                    {item.title}
                  </label>
                ))}
                {options.documents.length > 0 && !options.documents.some((item) =>
                  item.title.toLocaleLowerCase("de").includes(documentSearch.trim().toLocaleLowerCase("de")),
                ) && <small className="wp-hint">Kein passendes Dokument gefunden.</small>}
              </fieldset>
            </details>
          </div>
        </div>
        {context && (
          <div className="wp-owner">
            <ShieldCheck />
            <div>
              <strong>Chatkontext wurde sicher übernommen</strong>
              <span>Request-ID: {context.request_id}</span>
            </div>
          </div>
        )}
        <div className="wp-feedback-upload">
          <strong>Dateien hochladen (optional)</strong>
          <input
            ref={screenshotInput}
            className="sr-only"
            type="file"
            multiple
            accept="image/png,image/jpeg,.pdf,.docx,.xlsx,.pptx,.txt,.md"
            onChange={(event) => {
              const selected = Array.from(event.target.files || []);
              setAttachments((current) => [...current, ...selected].slice(0, 5));
              if (attachments.length + selected.length > 5) setMessage("Es wurden nur die ersten fünf Dateien übernommen.");
              event.target.value = "";
            }}
          />
          <button type="button" className="wp-secondary" onClick={() => screenshotInput.current?.click()}>
            <FileUp size={16} /> Datei auswählen
          </button>
          <small className="wp-hint">Bis zu fünf Dateien mit jeweils maximal 5 MB. Nur Admins sehen die Anhänge.</small>
          {!!attachments.length && (
            <ul className="wp-feedback-attachment-list">
              {attachments.map((attachment, index) => (
                <li key={`${attachment.name}-${attachment.lastModified}-${index}`}>
                  <span>{attachment.name}</span>
                  <button type="button" onClick={() => setAttachments((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Entfernen</button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <button className="wp-primary" disabled={busy} onClick={() => void submit()}>
          {busy ? <><LoaderCircle className="spin" size={16} /> Meldung wird gesendet …</> : "Meldung freigeben und senden"}
        </button>
        {message && <p className="wp-message">{message}</p>}
      </div>
      {success && (
        <div className="wp-confirm-backdrop" role="presentation">
          <div className="wp-confirm-dialog wp-feedback-success" role="dialog" aria-modal="true" aria-labelledby="feedback-success-title">
            <CheckCircle2 className="green" />
            <h2 id="feedback-success-title">Vielen Dank für deine Meldung</h2>
            <p>Ein Admin wurde informiert und kümmert sich darum.</p>
            <button className="wp-primary" onClick={() => setSuccess(false)}>Schließen</button>
          </div>
        </div>
      )}
    </section>
  );
}

function KnowledgebaseAdmin({
  changes,
  users,
  session,
  done,
}: {
  changes: KBChange[];
  users: PortalUser[];
  session: Session;
  done: () => Promise<void>;
}) {
  const confirm = useConfirmation();
  // Antragsteller mit Klarnamen; die reine Benutzer-ID sagt niemandem etwas.
  const userNames = Object.fromEntries(
    users.map((user) => [user.user_id, user.display_name]),
  );
  const [kind, setKind] = useState("create"),
    [target, setTarget] = useState(""),
    [label, setLabel] = useState(""),
    [slug, setSlug] = useState(""),
    [reason, setReason] = useState("");
  const [overview, setOverview] = useState<KBOverview[]>([]),
    [open, setOpen] = useState("");
  const [notice, setNotice] = useState("");
  const [successNotice, setSuccessNotice] = useState("");
  useEffect(() => {
    void api<{ knowledgebases: KBOverview[] }>(
      "/portal/admin/knowledgebase-overview",
    )
      .then((payload) => setOverview(payload.knowledgebases))
      .catch(() => setOverview([]));
  }, [changes]);
  // Archivieren und Entfernen machen alle zugeordneten Dokumente unauffindbar.
  // Ohne diesen Hinweis geschieht das lautlos.
  function affectedDocuments() {
    if (!["archive", "delete"].includes(kind)) return 0;
    return (
      overview.find((base) => base.knowledgebase_id === target)
        ?.document_count || 0
    );
  }
  async function requestChange() {
    const affected = affectedDocuments();
    const targetLabel = kind === "create"
      ? label
      : overview.find((base) => base.knowledgebase_id === target)?.label || target;
    const actionLabel = changeKindText[kind] || kind;
    const approved = await confirm({
      title: `Wissensbereich ${actionLabel.toLocaleLowerCase("de-DE")}?`,
      description: affected > 0
        ? `Du möchtest „${targetLabel}“ ${actionLabel.toLocaleLowerCase("de-DE")}. ${affected} ${affected === 1 ? "zugeordnetes Dokument" : "zugeordnete Dokumente"} ${affected === 1 ? "ist" : "sind"} danach über Vinci nicht mehr auffindbar. Möchtest du fortfahren?`
        : `Du möchtest den Wissensbereich „${targetLabel}“ ${actionLabel.toLocaleLowerCase("de-DE")}. Möchtest du diese Aktion wirklich durchführen?`,
      confirmLabel: actionLabel,
      danger: ["archive", "delete"].includes(kind),
    });
    if (!approved) return;
    setNotice("");
    const payload: { label?: string; slug?: string; purpose?: string } = {};
    if (kind === "create")
      Object.assign(payload, { label, slug, purpose: reason });
    if (kind === "rename") payload.label = label;
    const action: AdminAction = {
      path: "/portal/admin/knowledgebase-changes",
      method: "POST",
      body: {
        kind,
        knowledgebase_id: kind === "create" ? null : target,
        payload,
        confirmed: true,
      },
    };
    const response = await api<{ change: KBChange }>(action.path, {
      method: action.method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(action.body),
    });
    const completedText: Record<string, string> = {
      create: "Der Wissensbereich wurde erfolgreich angelegt.",
      rename: "Der Wissensbereich wurde erfolgreich umbenannt.",
      archive: "Der Wissensbereich wurde erfolgreich archiviert.",
      delete: "Der Wissensbereich wurde erfolgreich entfernt.",
    };
    const completed = response.change.status === "approved";
    setSuccessNotice(
      completed
        ? completedText[kind] || "Die Änderung wurde erfolgreich gespeichert."
        : "Der Änderungsantrag wurde erfolgreich eingereicht und wartet auf die Freigabe durch einen Portal-Admin.",
    );
    if (completed) {
      setLabel("");
      setSlug("");
      setTarget("");
      setReason("");
    }
    await done();
  }
  async function decide(request_id: string, approve: boolean) {
    if (!reason.trim()) return;
    const change = changes.find((item) => item.request_id === request_id);
    const actionLabel = approve ? "Antrag freigeben" : "Antrag ablehnen";
    const approved = await confirm({
      title: `${actionLabel}?`,
      description: `Du möchtest den Antrag „${change ? changeKindText[change.kind] || change.kind : request_id}“ ${approve ? "freigeben" : "ablehnen"}. Möchtest du diese Entscheidung wirklich speichern?`,
      confirmLabel: approve ? "Freigeben" : "Ablehnen",
      danger: !approve,
    });
    if (!approved) return;
    setNotice("");
    await api(`/portal/admin/knowledgebase-changes/${request_id}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approve, reason, confirmed: true }),
    });
    setSuccessNotice(
      approve
        ? "Der Änderungsantrag wurde freigegeben und die Änderung erfolgreich ausgeführt."
        : "Der Änderungsantrag wurde abgelehnt.",
    );
    setReason("");
    await done();
  }
  return (
    <section className="wp-page">
      {successNotice && (
        <div className="wp-confirm-backdrop" role="presentation">
          <div className="wp-confirm-dialog wp-feedback-success" role="dialog" aria-modal="true" aria-labelledby="kb-success-title">
            <CheckCircle2 className="green" />
            <h2 id="kb-success-title">Änderung erfolgreich</h2>
            <p>{successNotice}</p>
            <button className="wp-primary" onClick={() => setSuccessNotice("")}>Schließen</button>
          </div>
        </div>
      )}
      <Title
        eyebrow="Administration"
        title="Knowledge Bases verwalten"
        text="Normale Admins bereiten Änderungen vor; Portal-Admins geben sie frei oder führen sie direkt aus."
      />
      <div className="wp-form">
        <div className="wp-grid">
          <label>
            Aktion
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="create">Neu anlegen</option>
              <option value="rename">Umbenennen</option>
              <option value="archive">Archivieren</option>
              <option value="delete">Endgültig entfernen</option>
            </select>
          </label>
          {kind !== "create" && (
            <label>
              Knowledge Base
              <select
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
                <option value="">Bitte wählen</option>
                {overview
                  .filter((base) =>
                    kind === "delete"
                      ? base.status === "archived"
                      : base.status === "active",
                  )
                  .map((base) => (
                    <option
                      key={base.knowledgebase_id}
                      value={base.knowledgebase_id}
                    >
                      {base.label}
                      {base.status === "archived" ? " (archiviert)" : ""}
                    </option>
                  ))}
              </select>
              {kind === "delete" && (
                <small className="wp-hint">
                  Nur archivierte Wissensbereiche können endgültig entfernt
                  werden.
                </small>
              )}
            </label>
          )}
          {["create", "rename"].includes(kind) && (
            <label>
              Name
              <input value={label} onChange={(e) => setLabel(e.target.value)} />
            </label>
          )}
          {kind === "create" && (
            <label>
              Kurzname
              <input
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="z. B. service"
              />
            </label>
          )}
        </div>
        <label>
          Zweck oder Begründung
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        {notice && <p className="wp-message">{notice}</p>}
        <button className="wp-primary" onClick={() => void requestChange()}>
          Änderung einreichen
        </button>
      </div>
      <h2>Wissensbereiche und ihre Dokumente</h2>
      <div className="wp-kb-overview">
        {overview.length ? (
          overview.map((base) => (
            <article
              key={base.knowledgebase_id}
              className={open === base.knowledgebase_id ? "selected" : ""}
            >
              <button
                type="button"
                className="wp-kb-head"
                aria-expanded={open === base.knowledgebase_id}
                onClick={() =>
                  setOpen((current) =>
                    current === base.knowledgebase_id
                      ? ""
                      : base.knowledgebase_id,
                  )
                }
              >
                <ChevronRight
                  className={open === base.knowledgebase_id ? "wp-rot" : ""}
                />
                <span>
                  <strong>{base.label}</strong>
                  <small>{base.purpose || base.slug}</small>
                </span>
                <span className="wp-kb-count">
                  {base.document_count}{" "}
                  {base.document_count === 1 ? "Dokument" : "Dokumente"}
                </span>
              </button>
              {open === base.knowledgebase_id && (
                <div className="wp-kb-docs">
                  {base.documents.length ? (
                    <table>
                      <thead>
                        <tr>
                          <th>Titel</th>
                          <th>Status</th>
                          <th>Owner</th>
                          <th>Gültig bis</th>
                        </tr>
                      </thead>
                      <tbody>
                        {base.documents.map((doc) => (
                          <tr key={doc.document_id}>
                            <td>{doc.title}</td>
                            <td>{statusText[doc.status] || doc.status}</td>
                            <td>{doc.owner_name}</td>
                            <td>{doc.valid_until || "offen"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="wp-empty-hint">
                      Diesem Wissensbereich ist noch kein Dokument zugeordnet.
                    </p>
                  )}
                </div>
              )}
            </article>
          ))
        ) : (
          <p className="wp-empty-hint">
            Es ist noch kein Wissensbereich angelegt.
          </p>
        )}
      </div>
      <h2>Änderungsanträge</h2>
      <div className="wp-doc-list">
        {changes.length ? (
          changes.map((change) => (
            <article key={change.request_id}>
              <div className="wp-trash-row">
                <div className="wp-trash-copy">
                  <Badge status={change.status} />
                  <strong>
                    {changeKindText[change.kind] || change.kind}:{" "}
                    {change.payload?.label ||
                      overview.find(
                        (base) =>
                          base.knowledgebase_id === change.knowledgebase_id,
                      )?.label ||
                      change.knowledgebase_id}
                  </strong>
                  <span>
                    Beantragt von{" "}
                    {userNames[change.requested_by] || change.requested_by}
                  </span>
                  <small className="wp-hint">{change.request_id}</small>
                </div>
                <div className="wp-trash-side">
                  {session.role === "portal_admin" &&
                  change.status === "pending" ? (
                    <div className="wp-actions">
                      <button
                        onClick={() => void decide(change.request_id, false)}
                      >
                        Ablehnen
                      </button>
                      <button
                        className="approve"
                        onClick={() => void decide(change.request_id, true)}
                      >
                        Freigeben
                      </button>
                    </div>
                  ) : (
                    <p className="wp-hint">
                      {change.status === "pending"
                        ? "Wartet auf einen Portal-Admin."
                        : "Bereits entschieden."}
                    </p>
                  )}
                </div>
              </div>
            </article>
          ))
        ) : (
          <p className="wp-empty-hint">Kein offener Änderungsantrag.</p>
        )}
      </div>
    </section>
  );
}

function MigrationView({
  users,
  kbs,
  session,
}: {
  users: PortalUser[];
  kbs: KB[];
  session: Session;
}) {
  const confirm = useConfirmation();
  const [items, setItems] = useState<MigrationItem[]>([]),
    [tasks, setTasks] = useState<MigrationTask[]>([]),
    [selected, setSelected] = useState("");
  const [owner, setOwner] = useState(""),
    [confidentiality, setConfidentiality] = useState("internal"),
    [authorityLevel, setAuthorityLevel] = useState(5),
    [scopeDescription, setScopeDescription] = useState("");
  const [targetKnowledgebaseId, setTargetKnowledgebaseId] = useState("");
  const [filter, setFilter] = useState("open"),
    [search, setSearch] = useState("");
  const [dispositionReason, setDispositionReason] = useState("");
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const load = useCallback(async () => {
    const [inventory, taskPayload] = await Promise.all([
      api<{ items: MigrationItem[] }>("/portal/admin/migration/inventory"),
      api<{ tasks: MigrationTask[] }>("/portal/admin/migration/tasks"),
    ]);
    setItems(inventory.items);
    setTasks(taskPayload.tasks);
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(
      () =>
        void load().catch((cause) =>
          setMessage(
            friendlyError(cause, "Altbestände konnten nicht geladen werden."),
          ),
        ),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [load]);
  async function scan() {
    setBusy(true);
    setMessage("");
    try {
      const result = await api<{ items: MigrationItem[] }>(
        "/portal/admin/migration/inventory",
        { method: "POST" },
      );
      setItems(result.items);
      await load();
      setMessage(`${result.items.length} Dateien wurden erfasst und geprüft.`);
    } catch (cause) {
      setMessage(friendlyError(cause, "Bestandsaufnahme fehlgeschlagen."));
    } finally {
      setBusy(false);
    }
  }
  async function resolve() {
    if (!selected || !owner || !current)
      return setMessage("Bitte wähle eine Datei und einen Owner aus.");
    const targetKb = kbs.find(
      (kb) => kb.knowledgebase_id === targetKnowledgebaseId,
    );
    if (!targetKb)
      return setMessage(
        "Bitte wähle den Wissensbereich aus, in den das Dokument übernommen werden soll.",
      );
    const authority = authorityOptions.find(
      (option) => option.level === authorityLevel,
    )!;
    const scope: Record<string, unknown> = {
      knowledgebase_ids: [targetKb.knowledgebase_id],
    };
    if (scopeDescription.trim()) scope.description = scopeDescription.trim();
    setBusy(true);
    try {
      await api("/portal/admin/migration/metadata", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: selected,
          owner_email: owner,
          confidentiality,
          authority_type: authority.type,
          authority_level: authority.level,
          knowledgebase_id: targetKb.knowledgebase_id,
          scope,
        }),
      });
      await load();
      setMessage(
        "Metadaten und Zuständigkeit wurden gespeichert. Die Angaben bleiben für den nächsten Altbestand vorausgewählt.",
      );
    } catch (cause) {
      setMessage(
        friendlyError(cause, "Metadaten konnten nicht gespeichert werden."),
      );
    } finally {
      setBusy(false);
    }
  }
  async function stage(path: string) {
    const item = items.find((entry) => entry.path === path);
    const approved = await confirm({
      title: "Altbestand übernehmen?",
      description: `Du möchtest „${item?.original_path || path}“ in den regulären Freigabeprozess übernehmen. Die Datei wird anschließend dem ausgewählten Owner zur Prüfung zugeordnet. Möchtest du fortfahren?`,
      confirmLabel: "Übernehmen",
    });
    if (!approved) return;
    setBusy(true);
    try {
      const action: AdminAction = {
        path: "/portal/admin/migration/stage",
        method: "POST",
        body: { path, confirmed: true },
        returnTab: "migration",
      };
      await api(action.path, {
        method: action.method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action.body),
      });
      await load();
      setMessage(
        "Der Altbestand wurde als normaler Freigabevorgang an den Owner übergeben.",
      );
    } catch (cause) {
      setMessage(
        friendlyError(cause, "Übernahme konnte nicht gestartet werden."),
      );
    } finally {
      setBusy(false);
    }
  }
  async function changeDisposition(path: string, restore = false) {
    if (dispositionReason.trim().length < 3)
      return setMessage(
        "Bitte gib eine kurze Begründung mit mindestens drei Zeichen an.",
      );
    setBusy(true);
    setMessage("");
    try {
      await api(`/portal/admin/migration/${restore ? "restore" : "exclude"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, reason: dispositionReason.trim() }),
      });
      await load();
      setSelected("");
      setDispositionReason("");
      setMessage(
        restore
          ? "Der Altbestand ist wieder in der normalen Prüfliste."
          : "Der Altbestand wurde in ‚Nicht übernehmen‘ verschoben. Die Quelldatei bleibt erhalten.",
      );
    } catch (cause) {
      setMessage(
        friendlyError(
          cause,
          restore
            ? "Der Altbestand konnte nicht zurückgeholt werden."
            : "Der Altbestand konnte nicht zurückgestellt werden.",
        ),
      );
    } finally {
      setBusy(false);
    }
  }
  const current = items.find((item) => item.path === selected),
    openByPath = tasks.reduce<Record<string, number>>((counts, task) => {
      counts[task.path] = (counts[task.path] || 0) + 1;
      return counts;
    }, {}),
    visibleItems = items.filter((item) => {
      const matchesSearch =
        !search.trim() ||
        item.path
          .toLocaleLowerCase("de")
          .includes(search.trim().toLocaleLowerCase("de"));
      const matchesFilter =
        filter === "all" ||
        (filter === "open"
          ? ["metadata_required", "ready_to_stage", "quarantine"].includes(
              item.status,
            )
          : item.status === filter);
      return matchesSearch && matchesFilter;
    });
  const metadataForm =
    current && current.status === "metadata_required" ? (
      <div
        className="wp-migration-editor"
        aria-label={`Fehlende Angaben für ${current.path}`}
      >
        <div className="wp-editor-heading">
          <div>
            <span>Ausgewähltes Dokument</span>
            <h2>Angaben prüfen und ergänzen</h2>
          </div>
          <Badge status="Bearbeitung" />
        </div>
        <p className="wp-editor-intro">
          Diese Angaben werden nur für dieses Dokument gespeichert. Danach
          kannst du es in den regulären Freigabeprozess übergeben.
        </p>
        <div className="wp-migration-fields">
          <label>
            Ziel-Wissensbereich
            <select
              value={targetKnowledgebaseId}
              onChange={(e) => setTargetKnowledgebaseId(e.target.value)}
            >
              <option value="">Bitte wählen</option>
              {kbs.map((kb) => (
                <option key={kb.knowledgebase_id} value={kb.knowledgebase_id}>
                  {kb.label}
                </option>
              ))}
            </select>
            <small>
              Der erkannte Ordner wird vorausgewählt. Du kannst ihn fachlich
              korrigieren.
            </small>
          </label>
          <label>
            Verantwortlicher Owner
            <select value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">Bitte wählen</option>
              {users
                .filter((user) => user.active && user.manager_user_id)
                .map((user) => (
                  <option key={user.user_id} value={user.email}>
                    {user.display_name} ({user.email})
                  </option>
                ))}
            </select>
            <small>
              Für die zweistufige Freigabe werden nur Benutzer mit zugeordneter
              Führungskraft angezeigt.
            </small>
          </label>
          <label>
            Wer darf das Dokument sehen?
            <select
              value={confidentiality}
              onChange={(e) => setConfidentiality(e.target.value)}
            >
              {confidentialityOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <small>
              Unternehmensweit, nur in freigegebenen Bereichen oder
              ausschließlich für einzeln berechtigte Personen.
            </small>
          </label>
          <label>
            Verbindlichkeit
            <select
              value={authorityLevel}
              onChange={(e) => setAuthorityLevel(Number(e.target.value))}
            >
              {authorityOptions.map((option) => (
                <option key={option.level} value={option.level}>
                  {option.level}. {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="wp-field-wide">
            Wo und für wen gilt das Dokument? <span>(optional)</span>
            <textarea
              value={scopeDescription}
              onChange={(e) => setScopeDescription(e.target.value)}
              placeholder="z. B. Service an allen Standorten oder nur Verkauf Hannover"
            />
          </label>
        </div>
        <div className="wp-editor-footer">
          <span>Speichern startet noch keine Veröffentlichung.</span>
          <button
            className="wp-action-button primary"
            disabled={busy}
            onClick={() => void resolve()}
          >
            {busy ? <LoaderCircle className="spin" /> : <CheckCircle2 />}{" "}
            Angaben speichern
          </button>
        </div>
      </div>
    ) : null;
  return (
    <section className="wp-page">
      <Title
        eyebrow="Kontrollierte Übernahme"
        title="Altbestände migrieren"
        text="Originale und Markdown bleiben erhalten. Sicherheit, Qualität, Rechte und Zuständigkeit werden vor jeder Freigabe geprüft."
      />
      <div className="wp-migration-toolbar">
        <button
          className="wp-toolbar-button"
          disabled={busy}
          onClick={() => void scan()}
        >
          {busy ? <LoaderCircle className="spin" /> : <FileSearch />} Bestand
          neu prüfen
        </button>
        <label>
          Ansicht
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="open">Noch zu bearbeiten</option>
            <option value="metadata_required">Angaben fehlen</option>
            <option value="ready_to_stage">Bereit zur Übernahme</option>
            <option value="quarantine">Sicherheitsprüfung nötig</option>
            <option value="staged">Bereits übergeben</option>
            <option value="excluded">Nicht übernehmen</option>
            <option value="all">Alle Altbestände</option>
          </select>
        </label>
        <label>
          Dokument suchen
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Dateiname oder Ordner"
          />
        </label>
      </div>
      {message && <p className="wp-message">{message}</p>}
      <p className="wp-hint">
        {visibleItems.length} von {items.length} Altbeständen werden angezeigt.
      </p>
      <div className="wp-doc-list">
        {visibleItems.length ? (
          visibleItems.map((item) => (
            <article
              key={item.path}
              className={selected === item.path ? "selected" : ""}
            >
              <button
                type="button"
                className="wp-doc-head"
                aria-label={`Dokument auswählen und Angaben bearbeiten: ${item.path}`}
                aria-expanded={selected === item.path}
                onClick={() => {
                  const opening = selected !== item.path;
                  setSelected(opening ? item.path : "");
                  setDispositionReason("");
                  if (opening)
                    setTargetKnowledgebaseId(
                      kbs.find((kb) => kb.slug === item.knowledgebase_slug)
                        ?.knowledgebase_id || "",
                    );
                }}
              >
                <span className="wp-task-icon">
                  <FileSearch />
                </span>
                <span className="wp-task-copy">
                  <Badge status={item.status} />
                  <strong>{item.path}</strong>
                  <small>
                    {item.knowledgebase_slug ||
                      "noch keinem Wissensbereich zugeordnet"}{" "}
                    · {openByPath[item.path] || 0} offene Aufgaben · Frist{" "}
                    {item.transition_deadline}
                  </small>
                  <span className="wp-select-hint">
                    {selected === item.path
                      ? "Ausgewählt – Angaben unten bearbeiten"
                      : "Dokument auswählen und Angaben bearbeiten"}
                  </span>
                </span>
                <ChevronRight
                  className={selected === item.path ? "wp-rot" : ""}
                />
              </button>
              {selected === item.path && (
                <div className="wp-doc-panel">
                  <p className="wp-preview-note">
                    Nutze die Vorschau, um den Inhalt zu prüfen. Die Angaben für
                    die Übernahme bearbeitest du direkt darunter.
                  </p>
                  <div className="wp-preview-actions">
                    <a
                      className="wp-outline-button"
                      href={`${API}/portal/admin/migration/file?path=${encodeURIComponent(item.path)}&kind=original`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Original ansehen (nur Vorschau)
                    </a>
                    {item.markdown_path && (
                      <a
                        className="wp-outline-button"
                        href={`${API}/portal/admin/migration/file?path=${encodeURIComponent(item.path)}&kind=markdown`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Markdown ansehen (nur Vorschau)
                      </a>
                    )}
                  </div>
                  <p className="wp-migration-status">
                    Aufbereitung:{" "}
                    {migrationCheckText[item.conversion_quality] ||
                      item.conversion_quality}{" "}
                    · Sicherheitsprüfung:{" "}
                    {migrationCheckText[item.prompt_injection_risk] ||
                      item.prompt_injection_risk}
                  </p>
                  {item.missing.length > 0 && (
                    <p className="wp-reason">
                      Noch zu klären:{" "}
                      {item.missing
                        .map((gap) => migrationGapText[gap] || gap)
                        .join(", ")}
                    </p>
                  )}
                  <div className="wp-disposition">
                    <div>
                      <strong>
                        {item.status === "excluded"
                          ? "Zurückgestellter Altbestand"
                          : "Dieses Dokument nicht übernehmen"}
                      </strong>
                      <p>
                        {item.status === "excluded"
                          ? `Begründung: ${item.exclusion_reason || "nicht angegeben"}. Die Quelldatei bleibt erhalten und kann wieder zur Prüfung zurückgeholt werden.`
                          : "Du musst dafür keine Angaben zur Übernahme ausfüllen. Das Dokument wird nicht gelöscht und kann später wieder zur Prüfung zurückgeholt werden."}
                      </p>
                    </div>
                    <label>
                      Kurze Begründung
                      <input
                        value={dispositionReason}
                        onChange={(e) => setDispositionReason(e.target.value)}
                        placeholder={
                          item.status === "excluded"
                            ? "Warum soll es wieder geprüft werden?"
                            : "Warum wird es nicht übernommen?"
                        }
                      />
                    </label>
                    <button
                      className="wp-outline-button"
                      disabled={busy}
                      onClick={() =>
                        void changeDisposition(
                          item.path,
                          item.status === "excluded",
                        )
                      }
                    >
                      {item.status === "excluded"
                        ? "Wieder zur Prüfung zurückholen"
                        : "In ‚Nicht übernehmen‘ verschieben"}
                    </button>
                  </div>
                  {item.status === "metadata_required" && metadataForm}
                  {item.status === "ready_to_stage" ? (
                    <button
                      className="wp-action-button primary"
                      disabled={busy}
                      onClick={() => void stage(item.path)}
                    >
                      <CheckCircle2 /> In regulären Freigabeprozess übernehmen
                    </button>
                  ) : item.status === "staged" ? (
                    <p className="wp-message">
                      Der Owner hat den Vorgang in seiner Aufgabenliste.
                    </p>
                  ) : null}
                </div>
              )}
            </article>
          ))
        ) : (
          <p className="wp-empty-hint">
            Für diese Auswahl gibt es keine Altbestände.
          </p>
        )}
      </div>
    </section>
  );
}

function QualityDashboardView({ data }: { data: QualityDashboard | null }) {
  if (!data)
    return (
      <section className="wp-page">
        <LoaderCircle className="spin" />
      </section>
    );
  const cards = [
    ["Aktive Dokumente", data.active_documents],
    ["Abgelaufene Dokumente", data.expired_documents],
    ["Ablauf in ≤ 15 Arbeitstagen", data.expiring_within_15_workdays],
    ["Offene Freigaben", data.workflow_quality?.open_approvals],
    [
      "Ø Bearbeitungszeit",
      data.workflow_quality?.average_processing_minutes == null
        ? "–"
        : `${data.workflow_quality.average_processing_minutes} min`,
    ],
    ["Eskalationen", data.workflow_quality?.escalations],
    ["Überfällige Vorgänge", data.workflow_quality?.overdue_cases],
    ["Dubletten", data.workflow_quality?.duplicates],
    ["Mögliche neue Versionen", data.workflow_quality?.version_candidates],
    ["Widersprüche", data.workflow_quality?.conflicts],
    [
      "Fehlgeschlagene Konvertierungen",
      data.workflow_quality?.failed_conversions,
    ],
    ["Sicherheitsfunde", data.workflow_quality?.security_findings],
    ["Offene Wissensfehler", data.open_feedback],
    ["Offene Systemincidents", data.open_incidents],
    ["Ausstehende Mails", data.mail?.pending],
    ["Fehlgeschlagene Mails", data.mail?.failed],
    [
      "Führungskräfte ohne Vertretung",
      data.governance?.managers_without_delegate,
    ],
    [
      "Dokumente ohne gültige Verantwortung",
      data.governance?.documents_without_active_owner_or_manager,
    ],
    ["Wissensanfragen (30 Tage)", data.retrieval?.requests],
    [
      "Dokumenttreffer",
      data.retrieval?.document_hit_rate_percent == null
        ? "–"
        : `${data.retrieval.document_hit_rate_percent} %`,
    ],
    [
      "Quellenabdeckung",
      data.retrieval?.source_coverage_percent == null
        ? "–"
        : `${data.retrieval.source_coverage_percent} %`,
    ],
    ["Unbeantwortete interne Fragen", data.retrieval?.unanswered_questions],
    [
      "Ø Retrieval-Latenz",
      data.retrieval?.average_latency_ms == null
        ? "–"
        : `${data.retrieval.average_latency_ms} ms`,
    ],
    [
      "P95 Retrieval-Latenz",
      data.retrieval?.p95_latency_ms == null
        ? "–"
        : `${data.retrieval.p95_latency_ms} ms`,
    ],
    [
      "Retrieval-Fehlerrate",
      data.retrieval?.error_rate_percent == null
        ? "–"
        : `${data.retrieval.error_rate_percent} %`,
    ],
  ];
  return (
    <section className="wp-page">
      <Title
        eyebrow="Qualität und Betrieb"
        title="Admin-Qualitätsdashboard"
        text="Aggregierte Qualitäts- und Betriebswerte. Sie dürfen nicht zur individuellen Leistungs- oder Verhaltensbewertung verwendet werden."
      />
      <div className="wp-cards">
        {cards.map(([label, value]) => (
          <article key={String(label)}>
            <div>
              <strong>{String(value ?? 0)}</strong>
              <span>{label}</span>
            </div>
          </article>
        ))}
      </div>
      <div className="wp-kbs">
        <article>
          <ShieldCheck />
          <div>
            <strong>Hybridindex</strong>
            <span>{data.index?.ok ? "Erreichbar" : "Nicht erreichbar"}</span>
          </div>
        </article>
        <article>
          <ShieldCheck />
          <div>
            <strong>Letztes Backup</strong>
            <span>{data.backup?.last_backup || "Noch nicht ausgeführt"}</span>
          </div>
        </article>
        <article>
          <ShieldCheck />
          <div>
            <strong>Letzter Restore-Test</strong>
            <span>
              {data.backup?.last_restore_test || "Noch nicht ausgeführt"}
            </span>
          </div>
        </article>
      </div>
      <h2>Vorgänge nach Status</h2>
      {countList(
        data.workflow_cases,
        statusText,
        "Aktuell sind keine Vorgänge offen.",
      )}
      <h2>Migration</h2>
      {countList(data.migration, statusText, "Es läuft keine Migration.")}
    </section>
  );
}

function RestrictedTermsView({
  terms,
  done,
}: {
  terms: RestrictedTerm[];
  done: () => Promise<void>;
}) {
  const [term, setTerm] = useState(""),
    [busy, setBusy] = useState(""),
    [message, setMessage] = useState("");
  async function add() {
    if (term.trim().length < 2)
      return setMessage(
        "Bitte gib ein Schlagwort mit mindestens zwei Zeichen ein.",
      );
    setBusy("add");
    setMessage("");
    try {
      await api("/portal/admin/restricted-terms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ term: term.trim() }),
      });
      setTerm("");
      await done();
      setMessage("Das Schlagwort ist ab sofort aktiv.");
    } catch (cause) {
      setMessage(
        friendlyError(cause, "Das Schlagwort konnte nicht gespeichert werden."),
      );
    } finally {
      setBusy("");
    }
  }
  async function remove(ruleId: string) {
    setBusy(ruleId);
    setMessage("");
    try {
      await api(`/portal/admin/restricted-terms/${ruleId}`, {
        method: "DELETE",
      });
      await done();
      setMessage("Das Schlagwort wurde entfernt.");
    } catch (cause) {
      setMessage(
        friendlyError(cause, "Das Schlagwort konnte nicht entfernt werden."),
      );
    } finally {
      setBusy("");
    }
  }
  return (
    <section className="wp-page">
      <Title
        eyebrow="Dokumentschutz"
        title="Sperrwörter verwalten"
        text="Dokumente mit einem dieser Begriffe werden nicht automatisch weitergeleitet. Sie landen mit dem gefundenen Begriff direkt bei einem Admin zur Prüfung."
      />
      <div className="wp-form">
        <label>
          Neues Sperrwort oder feste Wortgruppe
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="z. B. interne Dokumentbezeichnung"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void add();
              }
            }}
          />
          <small>
            Groß- und Kleinschreibung spielt keine Rolle. Kurze Begriffe wie TPI
            werden nur als vollständiges Wort erkannt.
          </small>
        </label>
        <button
          className="wp-primary"
          disabled={busy === "add"}
          onClick={() => void add()}
        >
          {busy === "add" ? <LoaderCircle className="spin" /> : <ShieldCheck />}{" "}
          Schlagwort hinzufügen
        </button>
        {message && <p className="wp-message">{message}</p>}
      </div>
      <h2>Aktive Sperrwörter</h2>
      <div className="wp-doc-list">
        {terms.length ? (
          terms.map((item) => (
            <article key={item.rule_id}>
              <div className="wp-trash-row">
                <div className="wp-trash-copy">
                  <Badge status="active" />
                  <strong>{item.term}</strong>
                  <span>Treffer führen immer zur Adminprüfung.</span>
                </div>
                <button
                  className="wp-outline-button"
                  disabled={busy === item.rule_id}
                  onClick={() => void remove(item.rule_id)}
                >
                  Entfernen
                </button>
              </div>
            </article>
          ))
        ) : (
          <p className="wp-empty-hint">Es sind keine Sperrwörter hinterlegt.</p>
        )}
      </div>
    </section>
  );
}

const feedbackReasonText: Record<string, string> = {
  incorrect: "Information ist falsch",
  outdated: "Information ist veraltet",
  conflicting_sources: "Quellen widersprechen sich",
  irrelevant_source: "Quelle passt nicht zur Frage",
  suspected_permission_issue: "Möglicher Berechtigungsfehler",
  other: "Sonstiger Wissensfehler",
};

function technicalIncident(item: Pick<QualityRow, "summary" | "diagnostic_json">) {
  let diagnostic: Record<string, unknown> = {};
  try { diagnostic = JSON.parse(item.diagnostic_json || "{}"); } catch { diagnostic = {}; }
  const code = String(diagnostic.error_code || diagnostic.error_type || "unbekannt");
  const reasons: Record<string, string> = {
    embedding_service_unavailable: "Der Dienst für die automatische Ähnlichkeitsanalyse war nicht erreichbar oder konnte das Dokument nicht verarbeiten.",
    RetrievalError: "Die Wissenssuche konnte eine Anfrage technisch nicht abschließen.",
  };
  return { diagnostic, reason: reasons[code] || `Technischer Fehlercode: ${code}` };
}

function QualityCasesView({ data, done }: { data: QualityCases; done: () => Promise<void> }) {
  const [selected, setSelected] = useState<QualityRow | null>(null),
    [reply, setReply] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const rows: QualityRow[] = [
    ...(data.incidents || []).map((item) => ({
      ...item,
      type: "incident",
      id: item.incident_id,
      summary: item.step === "retrieval" ? "Technischer Fehler bei der Wissenssuche" : `Technischer Fehler: ${item.step}`,
    })),
    ...(data.feedback || []).map((item) => ({
      ...item,
      type: "feedback",
      id: item.feedback_id,
      summary: feedbackReasonText[item.reason] || "Wissensfehler",
    })),
  ];
  async function sendReply() {
    if (!selected || selected.type !== "feedback" || reply.trim().length < 3) return;
    setBusy(true); setMessage("");
    try {
      await api(`/portal/admin/quality-cases/feedback/${selected.id}/message`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: reply.trim() }),
      });
      setReply("");
      setMessage("Die Rückmeldung wurde als Mitteilung und per E-Mail versendet.");
    } catch (cause) {
      setMessage(friendlyError(cause, "Die Rückmeldung konnte nicht versendet werden."));
    } finally { setBusy(false); }
  }
  async function resolveCase() {
    if (!selected || reply.trim().length < 3) return setMessage("Bitte dokumentiere kurz, wie der Fall gelöst wurde.");
    setBusy(true); setMessage("");
    try {
      await api(`/portal/admin/quality-cases/${selected.type}/${selected.id}/resolve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resolution: reply.trim() }),
      });
      setSelected(null); setReply("");
      await done();
    } catch (cause) {
      setMessage(friendlyError(cause, "Der Fall konnte nicht abgeschlossen werden."));
    } finally { setBusy(false); }
  }
  return (
    <section className="wp-page">
      <Title
        eyebrow="Prüfung erforderlich"
        title="Qualitätsfälle"
        text="Kritische Rechte- und Systemfälle sowie fachliche Wissensfehler werden zentral bearbeitet."
      />
      <div className="wp-task-list">
        {rows.length ? (
          rows.map((item) => (
            <article key={item.id} className="wp-quality-case-card">
              <div className="wp-task-icon">
                <AlertTriangle />
              </div>
              <div className="wp-task-copy">
                <Badge status={item.severity || "normal"} />
                <h2>
                  {item.summary}
                </h2>
                <p>
                  {new Date(item.created_at).toLocaleString("de-DE")}
                </p>
                {item.reported_by_name && <span><strong>Gemeldet von:</strong> {item.reported_by_name}</span>}
                {item.comment && <span>{item.comment}</span>}
                {!!item.knowledgebases?.length && (
                  <span><strong>Wissensbereiche:</strong> {item.knowledgebases.map((base) => base.label).join(", ")}</span>
                )}
                {!!item.documents?.length && (
                  <span><strong>Dokumente:</strong> {item.documents.map((document) => document.title).join(", ")}</span>
                )}
                {item.type === "incident" && (
                  <>
                    <span><strong>Was ist passiert:</strong> {technicalIncident(item).reason}</span>
                    {technicalIncident(item).diagnostic.title && <span><strong>Dokument:</strong> {String(technicalIncident(item).diagnostic.title)}</span>}
                    {technicalIncident(item).diagnostic.original_filename && <span><strong>Datei:</strong> {String(technicalIncident(item).diagnostic.original_filename)}</span>}
                    <span>Dieser Fall wurde automatisch durch das System erzeugt.</span>
                  </>
                )}
              </div>
              <div className="wp-quality-case-actions">
                {item.screenshot_filename && (
                  <a className="wp-secondary" href={`${API}/portal/admin/feedback/${item.id}/screenshot`} target="_blank" rel="noreferrer">
                    Screenshot ansehen
                  </a>
                )}
                {item.attachments?.map((attachment) => (
                  <a key={attachment.attachment_id} className="wp-secondary"
                    href={`${API}/portal/admin/feedback/${item.id}/attachments/${attachment.attachment_id}`}
                    target="_blank" rel="noreferrer">
                    {attachment.original_filename}
                  </a>
                ))}
                <button className="wp-secondary" onClick={() => { setSelected(item); setReply(""); setMessage(""); }}>
                  Fall bearbeiten
                </button>
              </div>
            </article>
          ))
        ) : (
          <div className="wp-empty">
            <CheckCircle2 />
            <h2>Keine offenen Qualitätsfälle</h2>
          </div>
        )}
      </div>
      {selected && (
        <div className="wp-confirm-backdrop" role="presentation">
          <div className="wp-confirm-dialog wp-quality-case-dialog" role="dialog" aria-modal="true" aria-labelledby="quality-case-title">
            <AlertTriangle />
            <h2 id="quality-case-title">{selected.summary}</h2>
            {selected.reported_by_name && <p>Gemeldet von <strong>{selected.reported_by_name}</strong></p>}
            {selected.type === "incident" && <div><strong>Technische Einordnung</strong><p>{technicalIncident(selected).reason}</p></div>}
            {selected.comment && <div><strong>Hinweis des Nutzers</strong><p>{selected.comment}</p></div>}
            {selected.question && <details><summary>Übernommene Frage anzeigen</summary><p>{selected.question}</p></details>}
            {selected.answer && <details><summary>Beanstandete Antwort anzeigen</summary><p>{selected.answer}</p></details>}
            {!!selected.knowledgebases?.length && <p><strong>Wissensbereiche:</strong> {selected.knowledgebases.map((base) => base.label).join(", ")}</p>}
            {!!selected.documents?.length && <p><strong>Dokumente:</strong> {selected.documents.map((document) => document.title).join(", ")}</p>}
            {!!selected.attachments?.length && (
              <div><strong>Angehängte Dateien</strong><ul>
                {selected.attachments.map((attachment) => (
                  <li key={attachment.attachment_id}><a
                    href={`${API}/portal/admin/feedback/${selected.id}/attachments/${attachment.attachment_id}`}
                    target="_blank" rel="noreferrer">{attachment.original_filename}</a></li>
                ))}
              </ul></div>
            )}
            <label>
              Rückmeldung oder Abschlussnotiz
              <textarea value={reply} onChange={(event) => setReply(event.target.value)} placeholder="Was wurde geprüft oder korrigiert?" />
            </label>
            {message && <p className="wp-message" role="status">{message}</p>}
            <div className="wp-confirm-actions">
              <button onClick={() => setSelected(null)} disabled={busy}>Schließen</button>
              {selected.type === "feedback" && <button onClick={() => void sendReply()} disabled={busy || reply.trim().length < 3}>Nutzer benachrichtigen</button>}
              <button className="wp-primary" onClick={() => void resolveCase()} disabled={busy || reply.trim().length < 3}>
                {busy ? <LoaderCircle className="spin" size={16} /> : <CheckCircle2 size={16} />} Fall gelöst
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function DocumentList({
  documents,
  changes,
  ownershipTasks,
  users,
  session,
  done,
}: {
  documents: PortalDocument[];
  changes: DocumentChange[];
  ownershipTasks: OwnershipTask[];
  users: PortalUser[];
  session: Session;
  done: () => Promise<void>;
}) {
  const confirm = useConfirmation();
  const [selected, setSelected] = useState(""),
    [search, setSearch] = useState(""),
    [knowledgebaseFilter, setKnowledgebaseFilter] = useState(""),
    [desired, setDesired] = useState("restricted"),
    [proposedOwner, setProposedOwner] = useState("");
  const [message, setMessage] = useState(""),
    [bases, setBases] = useState<KBOverview[]>([]);
  const [reasonByDocument, setReasonByDocument] = useState<Record<string, string>>({});
  const [publicationSelections, setPublicationSelections] = useState<Record<string, string[]>>({}),
    [publicationBusy, setPublicationBusy] = useState<Record<string, boolean>>({});
  const publicationSaveLocks = useRef(new Set<string>());
  const reason = reasonByDocument[selected] || "";
  const isAdmin = ["admin", "portal_admin"].includes(session.role);
  useEffect(() => {
    if (!isAdmin) return;
    void api<{ knowledgebases: KBOverview[] }>(
      "/portal/admin/knowledgebase-overview",
    )
      .then((payload) =>
        setBases(
          payload.knowledgebases.filter((base) => base.status === "active"),
        ),
      )
      .catch(() => setBases([]));
  }, [isAdmin]);
  // Ein zweiter Klick schliesst die Kachel wieder, statt sie offen zu lassen.
  const toggle = (documentId: string) =>
    setSelected((current) => {
      setMessage("");
      return current === documentId ? "" : documentId;
    });

  // Alle Antraege verlangen serverseitig eine Begruendung. Fehlte sie, brach die
  // Aktion vorher wortlos ab; nichts geschah und niemand erfuhr warum.
  async function run(
    what: string,
    call: () => Promise<unknown>,
    needsReason = true,
  ) {
    if (needsReason && reason.trim().length < 3) {
      return setMessage(
        "Bitte gib zuerst eine Begründung mit mindestens drei Zeichen ein.",
      );
    }
    try {
      await call();
      setReasonByDocument((current) => ({ ...current, [selected]: "" }));
      setMessage(`${what} wurde eingereicht.`);
      await done();
    } catch (cause) {
      setMessage(friendlyError(cause, `${what} ist fehlgeschlagen.`));
    }
  }

  const post = (path: string, body: Record<string, unknown>) =>
    api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

  const publish = async (
    documentId: string,
    knowledgebaseId: string,
    active: boolean,
    nextSelection: string[],
  ) => {
    if (publicationSaveLocks.current.has(documentId)) return;
    const documentReason = reasonByDocument[documentId] || "";
    if (documentReason.trim().length < 3) {
      setMessage("Bitte gib zuerst eine Begründung mit mindestens drei Zeichen ein.");
      return;
    }
    if (nextSelection.length === 0) {
      setMessage("Mindestens ein Wissensbereich muss mit dem Dokument verknüpft bleiben.");
      return;
    }
    const knowledgebaseLabel =
      bases.find((base) => base.knowledgebase_id === knowledgebaseId)?.label || knowledgebaseId;
    const approved = await confirm({
      title: active
        ? "Wissensbereich hinzufügen?"
        : "Wissensbereich entfernen?",
      description: active
        ? `Das Dokument wird zusätzlich mit „${knowledgebaseLabel}“ verknüpft. Möchtest du fortfahren?`
        : `Die Verknüpfung des Dokuments mit „${knowledgebaseLabel}“ wird entfernt. Möchtest du fortfahren?`,
      confirmLabel: active ? "Hinzufügen" : "Entfernen",
      danger: !active,
    });
    if (!approved) return;
    publicationSaveLocks.current.add(documentId);
    setPublicationSelections((current) => ({ ...current, [documentId]: nextSelection }));
    setPublicationBusy((current) => ({ ...current, [documentId]: true }));
    setMessage("");
    try {
      await api(`/portal/admin/documents/${documentId}/publications`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          knowledgebase_id: knowledgebaseId,
          active,
          reason: documentReason,
        }),
      });
      setMessage(active ? "Der Wissensbereich wurde hinzugefügt." : "Der Wissensbereich wurde entfernt.");
      await done();
    } catch (cause) {
      setMessage(friendlyError(cause, "Die Verknüpfung konnte nicht geändert werden."));
    } finally {
      setPublicationSelections((current) => {
        const next = { ...current };
        delete next[documentId];
        return next;
      });
      publicationSaveLocks.current.delete(documentId);
      setPublicationBusy((current) => ({ ...current, [documentId]: false }));
    }
  };
  const requestRemoval = (kind: string) =>
    run(
      kind === "delete"
        ? ["admin", "portal_admin"].includes(session.role)
          ? "Die Verschiebung in den Papierkorb"
          : "Der Löschantrag"
        : "Der Deaktivierungsantrag",
      () =>
        post("/portal/removal-requests", {
          document_id: selected,
          kind,
          reason,
        }),
    );
  const renewal = async () => {
    if (reason.trim().length < 3) {
      return setMessage("Bitte gib zuerst eine Begründung mit mindestens drei Zeichen ein.");
    }
    const document = documents.find((item) => item.document_id === selected);
    const approved = await confirm({
      title: "Gültigkeit verlängern?",
      description: `Du bestätigst, dass „${document?.title || selected}“ weiterhin aktuell ist. Nach den erforderlichen Freigaben wird die Gültigkeit verlängert. Möchtest du fortfahren?`,
      confirmLabel: "Gültigkeit verlängern",
    });
    if (!approved) return;
    return run("Die Verlängerung", () =>
      post("/portal/document-changes/renewal", {
        document_id: selected,
        reason,
        confirmed: true,
      }),
    );
  };
  const classification = () =>
    run("Die Einstufungsänderung", () =>
      post("/portal/document-changes/confidentiality", {
        document_id: selected,
        desired,
        reason,
      }),
    );
  const decide = (id: string, approve: boolean) =>
    run(
      approve ? "Die Freigabe" : "Die Ablehnung",
      () =>
        post(`/portal/document-changes/${id}/decision`, {
          approve,
          reason: reason || "Geprüft und entschieden",
        }),
      false,
    );
  const proposeOwner = (id: string) =>
    run(
      "Die Übernahmeanfrage",
      () =>
        post(`/portal/ownership-tasks/${id}/proposal`, {
          proposed_owner_user_id: proposedOwner,
          reason: reason || "Fachliche Zuständigkeit neu zugeordnet",
        }),
      false,
    );
  const confirmOwner = (id: string, accept: boolean) =>
    run(
      accept ? "Die Übernahme" : "Die Ablehnung",
      () =>
        post(`/portal/ownership-tasks/${id}/confirmation`, {
          accept,
          reason: reason || "Übernahme geprüft",
        }),
      false,
    );

  const groupedDocuments = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("de-DE");
    const visible = documents.filter((document) => {
      const belongsToSelectedKnowledgebase =
        !knowledgebaseFilter ||
        document.primary_knowledgebase?.knowledgebase_id === knowledgebaseFilter;
      const searchable = document.title.toLocaleLowerCase("de-DE");
      return belongsToSelectedKnowledgebase && (!term || searchable.includes(term));
    });
    const grouped = new Map<string, PortalDocument[]>();
    for (const document of visible) {
      const label = document.primary_knowledgebase?.label || "Noch nicht veröffentlicht";
      grouped.set(label, [...(grouped.get(label) || []), document]);
    }
    return [...grouped.entries()]
      .sort(([left], [right]) => left.localeCompare(right, "de-DE"))
      .map(([label, entries]) => ({
        label,
        documents: entries.sort((left, right) => left.title.localeCompare(right.title, "de-DE")),
      }));
  }, [documents, search, knowledgebaseFilter]);
  const knowledgebaseOptions = useMemo(() => {
    const unique = new Map<string, string>();
    for (const document of documents) {
      if (document.primary_knowledgebase) {
        unique.set(
          document.primary_knowledgebase.knowledgebase_id,
          document.primary_knowledgebase.label,
        );
      }
    }
    return [...unique.entries()].sort((left, right) =>
      left[1].localeCompare(right[1], "de-DE"),
    );
  }, [documents]);

  return (
    <section className="wp-page">
      <Title
        eyebrow="Wissensbestand"
        title="Dokumente"
        text="Gültigkeit, Vertraulichkeit und Entfernung werden nachvollziehbar beantragt und freigegeben."
      />
      <div className="wp-document-filters">
        <label className="wp-document-search">
          Dokumente suchen
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Dokumenttitel eingeben"
          />
        </label>
        <label>
          Knowledgebase filtern
          <select
            value={knowledgebaseFilter}
            onChange={(event) => setKnowledgebaseFilter(event.target.value)}
          >
            <option value="">Alle Knowledgebases</option>
            {knowledgebaseOptions.map(([id, label]) => (
              <option key={id} value={id}>{label}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="wp-doc-list">
        {groupedDocuments.length ? (
          groupedDocuments.map((group) => (
            <section className="wp-document-group" key={group.label}>
              <h2>{group.label}</h2>
              <div>
              {group.documents.map((doc) => {
            const open = selected === doc.document_id;
            const storedKnowledgebaseIds = [
              doc.primary_knowledgebase,
              ...doc.additional_knowledgebases,
            ].flatMap((base) => base?.knowledgebase_id ? [base.knowledgebase_id] : []);
            const selectedKnowledgebaseIds =
              publicationSelections[doc.document_id] || storedKnowledgebaseIds;
            const selectedKnowledgebaseLabels = bases
              .filter((base) => selectedKnowledgebaseIds.includes(base.knowledgebase_id))
              .map((base) => base.label);
            const publicationsAreSaving = Boolean(publicationBusy[doc.document_id]);
            return (
              <article
                key={doc.document_id}
                className={open ? "selected" : ""}
              >
                {/* Kopf als Schaltflaeche: das Panel darunter enthaelt eigene Bedienelemente
            und darf deshalb nicht in einem Element mit role="button" liegen. */}
                <div className="wp-doc-head-row">
                  <button
                    type="button"
                    className="wp-doc-head"
                    aria-expanded={open}
                    onClick={() => toggle(doc.document_id)}
                  >
                  <span className="wp-task-icon">
                    <FileSearch />
                  </span>
                  <span className="wp-task-copy">
                    <Badge status={doc.status || "draft"} />
                    <strong>{doc.title}</strong>
                    <small>
                      Gültig bis {doc.valid_until || "offen"}
                    </small>
                    {doc.additional_knowledgebases.length > 0 && (
                      <small className="wp-additional-kbs">
                        Zusätzlich verknüpft: {doc.additional_knowledgebases.map((base) => base.label).join(", ")}
                      </small>
                    )}
                  </span>
                    <ChevronRight className={open ? "wp-rot" : ""} />
                  </button>
                  {doc.original_url && (
                    <a
                      className="wp-original-link"
                      href={doc.original_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Original ansehen
                    </a>
                  )}
                </div>
                {open && (
                  <div className="wp-doc-panel">
                    {doc.status !== "active" && (
                      <p className="wp-reason">
                        Dieses Dokument ist noch nicht aktiv. Es wird erst nach
                        der Freigabe für Vinci auffindbar.
                      </p>
                    )}
                    <label>
                      Begründung
                      <textarea
                        value={reasonByDocument[doc.document_id] || ""}
                        onChange={(e) =>
                          setReasonByDocument((current) => ({
                            ...current,
                            [doc.document_id]: e.target.value,
                          }))
                        }
                        placeholder="Warum soll das geschehen?"
                      />
                    </label>
                    <div className="wp-actions">
                      <button onClick={() => void renewal()}>
                        Gültigkeit verlängern
                      </button>
                      <label>
                        Wer darf das Dokument sehen?
                        <select
                          value={desired}
                          onChange={(e) => setDesired(e.target.value)}
                        >
                          {confidentialityOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button onClick={() => void classification()}>
                        Einstufung ändern
                      </button>
                      <button onClick={() => void requestRemoval("deactivate")}>
                        Deaktivierung beantragen
                      </button>
                      <button onClick={() => void requestRemoval("delete")}>
                        {["admin", "portal_admin"].includes(session.role)
                          ? "In Papierkorb verschieben"
                          : "Löschung beantragen"}
                      </button>
                    </div>
                    {isAdmin && doc.status === "active" ? (
                      <div className="wp-publish">
                        <span>Verknüpfte Knowledge Bases bearbeiten</span>
                        <details className="wp-kb-multiselect">
                          <summary>
                            <span>
                              {selectedKnowledgebaseLabels.length
                                ? selectedKnowledgebaseLabels.join(", ")
                                : "Bitte wählen"}
                            </span>
                            {publicationsAreSaving
                              ? <LoaderCircle className="spin" size={16} />
                              : <ChevronRight size={16} />}
                          </summary>
                          <fieldset className="wp-kb-options">
                            <legend className="sr-only">
                              Knowledge Bases für {doc.title} bearbeiten
                            </legend>
                            {bases.map((base) => {
                              const assigned = selectedKnowledgebaseIds.includes(base.knowledgebase_id);
                              return (
                                <label key={base.knowledgebase_id}>
                                  <input
                                    type="checkbox"
                                    checked={assigned}
                                    disabled={publicationsAreSaving}
                                    onChange={(event) => {
                                      const next = event.target.checked
                                        ? [...selectedKnowledgebaseIds, base.knowledgebase_id]
                                        : selectedKnowledgebaseIds.filter(
                                            (id) => id !== base.knowledgebase_id,
                                          );
                                      void publish(
                                        doc.document_id,
                                        base.knowledgebase_id,
                                        event.target.checked,
                                        [...new Set(next)],
                                      );
                                    }}
                                  />
                                  {base.label}
                                </label>
                              );
                            })}
                          </fieldset>
                        </details>
                        <small>
                          Änderungen werden direkt gespeichert und im Audit-Verlauf dokumentiert.
                        </small>
                      </div>
                    ) : isAdmin ? (
                      <div className="wp-info-box">
                        Erst nach der Freigabe kannst du weitere Wissensbereiche zuordnen.
                      </div>
                    ) : null}
                    {message && <p className="wp-message">{message}</p>}
                  </div>
                )}
              </article>
            );
          })}
              </div>
            </section>
          ))
        ) : (
          <div className="wp-empty">
            <CheckCircle2 />
            <h2>{documents.length ? "Keine passenden Dokumente" : "Noch kein Dokument"}</h2>
            <p>{documents.length ? "Passe den Suchbegriff an." : "Sobald du etwas bereitstellst, erscheint es hier."}</p>
          </div>
        )}
      </div>
      {changes.length > 0 && (
        <>
          <h2>Änderungsaufgaben</h2>
          <div className="wp-task-list">
            {changes.map((item) => (
              <article key={item.request_id}>
                <div className="wp-task-copy">
                  <Badge status={item.status} />
                  <h2>
                    {item.kind} · {item.document_id}
                  </h2>
                  <p>{item.reason}</p>
                </div>
                {["manager", "admin", "portal_admin"].includes(session.role) &&
                  item.status.startsWith("pending") && (
                    <div className="wp-actions">
                      <button
                        onClick={() => void decide(item.request_id, false)}
                      >
                        Ablehnen
                      </button>
                      <button
                        className="approve"
                        onClick={() => void decide(item.request_id, true)}
                      >
                        Freigeben
                      </button>
                    </div>
                  )}
              </article>
            ))}
          </div>
        </>
      )}
      {ownershipTasks.length > 0 && (
        <>
          <h2>Owner-Neuzuordnung</h2>
          <div className="wp-task-list">
            {ownershipTasks.map((task) => (
              <article key={task.task_id}>
                <div className="wp-task-copy">
                  <Badge status={task.status} />
                  <h2>{task.document_id}</h2>
                  <p>{task.reason}</p>
                </div>
                {["admin", "portal_admin"].includes(session.role) &&
                  task.status === "open" && (
                    <div className="wp-task-actions">
                      <select
                        value={proposedOwner}
                        onChange={(e) => setProposedOwner(e.target.value)}
                      >
                        <option value="">Neuen Owner wählen</option>
                        {users
                          .filter((user) => user.active)
                          .map((user) => (
                            <option key={user.user_id} value={user.user_id}>
                              {user.display_name}
                            </option>
                          ))}
                      </select>
                      <button
                        className="approve"
                        disabled={!proposedOwner}
                        onClick={() => void proposeOwner(task.task_id)}
                      >
                        Übernahme anfragen
                      </button>
                    </div>
                  )}
                {task.status === "pending_owner_confirmation" &&
                  task.proposed_owner_user_id === session.user_id && (
                    <div className="wp-actions">
                      <button
                        onClick={() => void confirmOwner(task.task_id, false)}
                      >
                        Ablehnen
                      </button>
                      <button
                        className="approve"
                        onClick={() => void confirmOwner(task.task_id, true)}
                      >
                        Verantwortung übernehmen
                      </button>
                    </div>
                  )}
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function TrashView({
  data,
  done,
  session,
}: {
  data: Removals;
  done: () => Promise<void>;
  session: Session;
}) {
  const confirm = useConfirmation();
  const [reason, setReason] = useState<Record<string, string>>({}),
    [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const canAdministerTrash = ["admin", "portal_admin"].includes(session.role);
  const openRequests = data.requests.filter(
    (item) => item.status === "pending",
  );

  async function call(
    id: string,
    what: string,
    path: string,
    body: Record<string, unknown>,
  ) {
    setBusy(id);
    setMessage("");
    try {
      await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setMessage(`${what} wurde ausgeführt.`);
      await done();
    } catch (cause) {
      setMessage(friendlyError(cause, `${what} ist fehlgeschlagen.`));
    } finally {
      setBusy("");
    }
  }

  const decide = (id: string, approve: boolean) =>
    call(
      id,
      approve ? "Die Bestätigung" : "Die Ablehnung",
      `/portal/admin/removal-requests/${id}/decision`,
      { approve, reason: reason[id] || "Adminentscheidung" },
    );
  const restore = (id: string) =>
    call(id, "Die Wiederherstellung", `/portal/admin/trash/${id}/restore`, {
      reason: reason[id] || "Wiederherstellung durch Admin",
    });
  const purge = async (id: string) => {
    const item = data.trash.find((entry) => entry.document_id === id);
    const approved = await confirm({
      title: "Dokument endgültig löschen?",
      description: `Du möchtest „${item?.title || id}“ endgültig löschen. Originaldatei, aufbereitete Fassung und Inhalt werden unwiderruflich entfernt. Nur die Auditdaten bleiben erhalten. Möchtest du fortfahren?`,
      confirmLabel: "Endgültig löschen",
      danger: true,
    });
    if (!approved) return;
    return call(id, "Die endgültige Löschung", `/portal/admin/trash/${id}/delete`, {
      reason: reason[id] || "Endgültige Löschung durch Admin",
      confirmed: true,
    });
  };

  return (
    <section className="wp-page">
      <Title
        eyebrow="Aufbewahrung"
        title="Papierkorb und Löschanträge"
        text="Dokumente bleiben mindestens 30 und höchstens 90 Tage wiederherstellbar; Legal Holds setzen die Löschung aus."
      />
      {message && <p className="wp-message">{message}</p>}
      <h2>Offene Anträge</h2>
      <div className="wp-doc-list">
        {openRequests.length ? (
          openRequests.map((item) => (
            <article key={item.request_id}>
              <div className="wp-trash-row">
                <div className="wp-trash-copy">
                  <Badge status={item.kind} />
                  <strong>{item.title || item.document_id}</strong>
                  <span>{item.reason}</span>
                  <small className="wp-hint">{item.document_id}</small>
                </div>
                <div className="wp-trash-side">
                  <textarea
                    placeholder="Begründung"
                    value={reason[item.request_id] || ""}
                    onChange={(e) =>
                      setReason({
                        ...reason,
                        [item.request_id]: e.target.value,
                      })
                    }
                  />
                  <div className="wp-actions">
                    <button
                      disabled={busy === item.request_id}
                      onClick={() => void decide(item.request_id, false)}
                    >
                      Ablehnen
                    </button>
                    <button
                      className="approve"
                      disabled={busy === item.request_id}
                      onClick={() => void decide(item.request_id, true)}
                    >
                      Bestätigen
                    </button>
                  </div>
                </div>
              </div>
            </article>
          ))
        ) : (
          <p className="wp-empty-hint">Kein offener Antrag.</p>
        )}
      </div>
      <h2>Papierkorb</h2>
      <div className="wp-doc-list">
        {data.trash.length ? (
          data.trash.map((item) => (
            <article key={item.document_id}>
              <div className="wp-trash-row">
                <div className="wp-trash-copy">
                  <Badge
                    status={item.legal_hold ? "Legal Hold" : "Papierkorb"}
                  />
                  <strong>{item.title || item.document_id}</strong>
                  <span>
                    Seit {item.trashed_at} · {item.reason}
                  </span>
                  <small className="wp-hint">{item.document_id}</small>
                </div>
                <div className="wp-trash-side">
                  <textarea
                    placeholder="Begründung"
                    value={reason[item.document_id] || ""}
                    onChange={(e) =>
                      setReason({
                        ...reason,
                        [item.document_id]: e.target.value,
                      })
                    }
                  />
                  <div className="wp-actions">
                    <button
                      className="approve"
                      disabled={busy === item.document_id}
                      onClick={() => void restore(item.document_id)}
                    >
                      Wiederherstellen
                    </button>
                    {canAdministerTrash && item.can_delete && (
                      <button
                        className="wp-danger"
                        disabled={busy === item.document_id}
                        onClick={() => void purge(item.document_id)}
                      >
                        Endgültig löschen
                      </button>
                    )}
                  </div>
                  {item.legal_hold && (
                    <p className="wp-hint">
                      Legal Hold: eine Löschung ist ausgesetzt.
                    </p>
                  )}
                  {!item.legal_hold && !item.can_delete && (
                    <p className="wp-hint">
                      Bis einschließlich {item.delete_eligible_on} kann das
                      Dokument nur wiederhergestellt werden. Danach wird die
                      endgültige Löschung freigeschaltet.
                    </p>
                  )}
                </div>
              </div>
            </article>
          ))
        ) : (
          <p className="wp-empty-hint">Der Papierkorb ist leer.</p>
        )}
      </div>
    </section>
  );
}
