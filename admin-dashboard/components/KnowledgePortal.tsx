"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronRight, Clock3, FileSearch, FileUp, LayoutDashboard, LoaderCircle, ShieldCheck, Users, XCircle } from "lucide-react";

const API = "/wissen/api";
type Role = "employee" | "manager" | "admin" | "portal_admin";
type Session = { user_id: string; email: string; display_name: string; role: Role };
type KB = { knowledgebase_id: string; label: string; purpose?: string };
type Match = { document_id: string; title: string; level: string; knowledgebase_ids: string[]; version_candidate: boolean; has_conflict: boolean; match_percent?: number; conflict_count?: number };
type UploadResult = { case_id: string; status: string; requires_admin: boolean; owner_confirmation_required?:boolean; exact_duplicate_document_id?: string; matches: Match[]; confidentiality:string; confidentiality_reason:string; conversion_quality?:string; conversion_issues?:string[] };
type Task = { case_id: string; title: string; original_filename: string; status: string; target_knowledgebase_id: string; requested_action?: string; requires_admin: boolean };
type PortalUser = { user_id: string; email: string; display_name: string; role: Role; active: boolean; manager_user_id?: string };
type UserAccess = { knowledgebase_id: string; label: string; can_read: number | boolean; can_upload: number | boolean };
type AuditEntry = { occurred_at: string; actor_user_id: string; event_type: string; subject_type: string; subject_id: string };
type KBOverviewDocument = {document_id:string;title:string;owner_name:string;status:string;valid_until?:string};
type KBOverview = {knowledgebase_id:string;slug:string;label:string;purpose:string;status:string;document_count:number;status_counts:Record<string,number>;documents:KBOverviewDocument[]};
type KBChange = { request_id: string; kind: string; knowledgebase_id?: string; requested_by: string; status: string; payload: Record<string,any> };
type PortalDocument = {document_id:string;title:string;owner_user_id:string;active_version_id?:string;status?:string;valid_until?:string;knowledgebase_id?:string};
type OwnershipTask = {task_id:string;document_id:string;previous_owner_user_id:string;manager_user_id?:string;proposed_owner_user_id?:string;status:string;reason:string};
type UploadJob = {job_id:string;status:string;step:string;progress:number;result?:UploadResult;error_code?:string};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { credentials: "include", ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `request_${response.status}`);
  return body;
}

const statusText: Record<string, string> = {
  pending_employee_decision: "Deine Entscheidung fehlt", duplicate_blocked: "Identisches Dokument gefunden",
  pending_manager_approval: "Prüfung durch Führungskraft", pending_admin_approval: "Prüfung durch Admin",
  needs_correction: "Aufbereitung prüfen", security_blocked: "Sicherheitsprüfung erforderlich",
  ready_to_activate: "Bereit zur Veröffentlichung", active: "Aktiv",
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
  identical: "Identisch", very_high: "Sehr hohe Ähnlichkeit",
  medium: "Mittlere Ähnlichkeit", low: "Geringe Ähnlichkeit",
};

const confidentialityText: Record<string, string> = {
  internal: "Intern", restricted: "Bereichsbeschränkt", confidential: "Vertraulich",
};

// PRD 16.1: Mitarbeitende sehen eine dreistufige Bewertung, keine technischen Details.
const qualityRating: Record<string, { tone: string; title: string; text: string }> = {
  good: { tone: "ok", title: "Alles in Ordnung", text: "Der Inhalt wurde vollständig und lesbar übernommen." },
  low: { tone: "check", title: "Bitte prüfen", text: "Einzelne Stellen solltest du dir vor der Freigabe ansehen." },
  failed: { tone: "blocked", title: "Upload kann so nicht verarbeitet werden", text: "Bitte lade das Dokument in einer besser lesbaren Fassung erneut hoch." },
};

// PRD 21.1: Nutzer sehen eine verständliche Meldung, niemals den technischen Fehlercode.
const errorText: Record<string, string> = {
  kahle_microsoft_tenant_required: "Dieses Konto gehört nicht zum KAHLE-Verzeichnis. Bitte melde dich mit deinem KAHLE-Konto an.",
  openwebui_login_required: "Bitte melde dich zuerst mit deinem Microsoft-Konto an.",
  openwebui_identity_incomplete: "Deinem Konto fehlen Angaben. Bitte wende dich an einen Admin.",
  portal_user_inactive: "Dein Zugang ist derzeit nicht aktiv. Bitte wende dich an einen Admin.",
  admin_required: "Diese Aktion darf nur ein Admin ausführen.",
  portal_admin_required: "Diese Aktion darf nur ein Portal-Admin ausführen.",
  fresh_microsoft_authentication_required: "Bitte bestätige die Aktion mit einer erneuten Microsoft-Anmeldung.",
  no_readable_knowledgebases: "Dir ist noch kein Wissensbereich zum Lesen zugeordnet.",
  unsupported_file_type: "Dieser Dateityp wird nicht unterstützt. Erlaubt sind PDF, DOCX, XLSX, PPTX, TXT und Markdown.",
  file_too_large: "Die Datei ist zu groß. Erlaubt sind maximal 50 MB.",
  upload_too_large: "Die Datei ist zu groß. Erlaubt sind maximal 50 MB.",
  original_not_available: "Die Originaldatei ist derzeit nicht verfügbar.",
  source_not_available: "Die Quelle ist derzeit nicht verfügbar.",
  document_not_found: "Das Dokument wurde nicht gefunden.",
  qdrant_unavailable: "Die Wissenssuche ist gerade nicht erreichbar. Bitte versuche es später erneut.",
  valid_workdays_or_valid_until_required: "Bitte gib entweder eine Anzahl Arbeitstage oder ein Datum an.",
  invalid_valid_until: "Das gewählte Datum ist ungültig.",
  valid_until_not_in_future: "Das Datum muss nach dem heutigen Tag liegen.",
  valid_until_has_no_workday: "Bis zu diesem Datum liegt kein Arbeitstag.",
  valid_workdays_out_of_range: "Die Gültigkeit darf höchstens 60 Arbeitstage betragen.",
};

function friendlyError(cause: unknown, fallback: string) {
  const raw = cause instanceof Error ? cause.message : "";
  if (errorText[raw]) return errorText[raw];
  if (/^request_(401|403)$/.test(raw)) return "Dafür fehlt dir die Berechtigung.";
  if (raw === "request_404") return "Der Vorgang wurde nicht gefunden.";
  if (/^request_5\d\d$/.test(raw)) return "Das Portal ist vorübergehend nicht erreichbar. Bitte versuche es in einigen Minuten erneut.";
  return fallback;
}

// Der Dateiname ist fast immer der gewuenschte Titel. Endung entfernen, damit
// niemand ".pdf.docx" abtippen muss.
function titleFromFilename(filename: string) {
  return filename.replace(/(\.[a-z0-9]{2,5})+$/i, "").replace(/[_-]+/g, " ").trim();
}

// Warum ein Vorgang bei Admin oder Fuehrungskraft liegt. Ohne diese Angabe
// sieht die entscheidende Person nur, dass etwas wartet, nicht weshalb.
const subjectText: Record<string, string> = {
  user: "Benutzer", document: "Dokument", document_case: "Vorgang",
  knowledgebase: "Wissensbereich", rag_feedback: "Wissensfehler",
};

const reviewReason: Record<string, string> = {
  pending_admin_approval: "Der Fall verlangt eine Adminentscheidung.",
  pending_manager_approval: "Reguläre Freigabe durch die Führungskraft.",
  security_blocked: "Eine Sicherheitsprüfung hat angeschlagen.",
  needs_correction: "Die Aufbereitung muss überprüft werden.",
  duplicate_blocked: "Ein identisches Dokument ist bereits vorhanden.",
  error: "Bei der Verarbeitung ist ein technischer Fehler aufgetreten.",
};

function conversionIssueText(issue:string) {
  const table=/table_column_structure_inconsistent:line=(\d+):expected=(\d+):actual=(\d+)/.exec(issue);
  if(table) return `Tabellenzeile ${table[1]}: ${table[2]} Spalten erwartet, ${table[3]} erkannt.`;
  if(issue==="character_encoding_corrupted") return "Zeichenkodierung ist beschädigt.";
  if(issue==="conversion_output_too_short") return "Die Konvertierung hat zu wenig verwertbaren Inhalt erzeugt.";
  return issue;
}

function Badge({ status }: { status: string }) {
  const warning = ["duplicate_blocked", "security_blocked", "needs_correction"].includes(status);
  return <span className={`wp-badge ${warning ? "warn" : ""}`}>{statusText[status] || status}</span>;
}

export default function KnowledgePortal() {
  const [session, setSession] = useState<Session | null>(null), [kbs, setKbs] = useState<KB[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]), [users, setUsers] = useState<PortalUser[]>([]), [audit, setAudit] = useState<AuditEntry[]>([]), [changes, setChanges] = useState<KBChange[]>([]), [quality, setQuality] = useState<any>(null), [qualityCases, setQualityCases] = useState<any>({incidents:[],feedback:[]}), [documents, setDocuments] = useState<PortalDocument[]>([]), [removals,setRemovals]=useState<any>({requests:[],trash:[]}), [documentChanges,setDocumentChanges]=useState<any[]>([]), [ownershipTasks,setOwnershipTasks]=useState<OwnershipTask[]>([]);
  const [tab, setTab] = useState("overview"), [error, setError] = useState(""), [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try {
      setError(""); const current = await api<Session>("/portal/session"); setSession(current);
      const [kbPayload, taskPayload, documentPayload, documentChangePayload, ownershipPayload] = await Promise.all([api<{ knowledgebases: KB[] }>("/portal/knowledgebases?access=upload"), api<{ tasks: Task[] }>("/portal/tasks"), api<{documents:PortalDocument[]}>("/portal/documents"), api<{changes:any[]}>("/portal/document-changes"), api<{tasks:OwnershipTask[]}>("/portal/ownership-tasks")]);
      setKbs(kbPayload.knowledgebases); setTasks(taskPayload.tasks); setDocuments(documentPayload.documents); setDocumentChanges(documentChangePayload.changes); setOwnershipTasks(ownershipPayload.tasks);
      if (["admin", "portal_admin"].includes(current.role)) { const [userPayload, auditPayload, changePayload, qualityPayload, qualityCasePayload, removalPayload] = await Promise.all([api<{ users: PortalUser[] }>("/portal/admin/users"), api<{entries: AuditEntry[]}>("/portal/admin/audit?limit=100"), api<{changes: KBChange[]}>("/portal/admin/knowledgebase-changes"), api<any>("/portal/admin/dashboard"), api<any>("/portal/admin/quality-cases"), api<any>("/portal/admin/removals")]); setUsers(userPayload.users); setAudit(auditPayload.entries); setChanges(changePayload.changes); setQuality(qualityPayload); setQualityCases(qualityCasePayload); setRemovals(removalPayload); }
    } catch (cause) { setError(friendlyError(cause, "Portal konnte nicht geladen werden")); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); const params = new URLSearchParams(window.location.search); if (params.get("feedback")) setTab("feedback"); }, [refresh]);
  useEffect(() => {
    if (!session) return;
    const pending = sessionStorage.getItem("pending-role-change");
    if (!pending) return;
    try {
      const { userId, role } = JSON.parse(pending);
      void api(`/portal/admin/users/${userId}/role`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role }),
      }).then(() => { sessionStorage.removeItem("pending-role-change"); return refresh(); })
        .catch(cause => setError(friendlyError(cause, "Rollenänderung fehlgeschlagen")));
    } catch { sessionStorage.removeItem("pending-role-change"); }
  }, [session, refresh]);
  useEffect(() => {
    if (!session) return;
    const pending = sessionStorage.getItem("pending-admin-action");
    if (!pending) return;
    try { const action = JSON.parse(pending); void api(action.path, {method:action.method,headers:{"Content-Type":"application/json"},body:JSON.stringify(action.body)}).then(() => {sessionStorage.removeItem("pending-admin-action");setTab("knowledgebases");return refresh();}).catch(cause => setError(friendlyError(cause, "Adminaktion fehlgeschlagen"))); } catch { sessionStorage.removeItem("pending-admin-action"); }
  }, [session, refresh]);
  const isAdmin = session ? ["admin", "portal_admin"].includes(session.role) : false;
  const tabs = useMemo(() => [["overview", "Übersicht", LayoutDashboard], ["upload", "Dokument hochladen", FileUp], ["tasks", isAdmin ? "Admin-Aufgaben" : "Meine Vorgänge", FileSearch], ["documents", "Dokumente", FileSearch], ["feedback", "Wissensfehler melden", AlertTriangle], ...(isAdmin ? [["quality", "Qualitätsdashboard", FileSearch], ["quality-cases", "Qualitätsfälle", AlertTriangle], ["users", "Benutzer & Rechte", Users], ["knowledgebases", "Knowledge Bases", LayoutDashboard], ["trash", "Papierkorb", XCircle], ["audit", "Audit", ShieldCheck]] : [])], [isAdmin]);
  if (loading) return <main className="wp-loading"><LoaderCircle className="spin" /> Wissensportal wird geladen …</main>;
  if (!session) return <main className="wp-loading error"><AlertTriangle /> {error || "Microsoft-Anmeldung erforderlich"}</main>;
  return <div className="wp-shell">
    <header className="wp-header"><div><strong>KAHLE-<span>Vinci</span></strong><small>Wissensportal</small></div><div className="wp-user"><span>{session.display_name}</span><small>{session.email} · {session.role.replace("_", "-")}</small></div></header>
    <aside className="wp-nav"><p>Wissen verwalten</p>{tabs.map(([id, label, Icon]: any) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}><Icon size={19} /><span>{label}</span>{id === "tasks" && tasks.length > 0 && <b>{tasks.length}</b>}<ChevronRight size={15} /></button>)}<div className="wp-security"><ShieldCheck /><div><strong>Sicher verarbeitet</strong><small>Rechte, Gültigkeit und Quellen werden automatisch geprüft.</small></div></div></aside>
    <main className="wp-main">{error && <div className="wp-alert"><AlertTriangle />{error}<button onClick={() => setError("")}>Schließen</button></div>}{tab === "overview" && <Overview session={session} tasks={tasks} kbs={kbs} go={setTab} />}{tab === "upload" && <Upload session={session} kbs={kbs} done={refresh} />}{tab === "tasks" && <Tasks tasks={tasks} session={session} done={refresh} />}{tab === "documents" && <DocumentList documents={documents} changes={documentChanges} ownershipTasks={ownershipTasks} users={users} session={session} done={refresh} />}{tab === "feedback" && <FeedbackForm />}{tab === "quality" && isAdmin && <QualityDashboardView data={quality} />}{tab === "quality-cases" && isAdmin && <QualityCasesView data={qualityCases} />}{tab === "users" && isAdmin && <UserAdmin users={users} session={session} done={refresh} />}{tab === "knowledgebases" && isAdmin && <KnowledgebaseAdmin kbs={kbs} changes={changes} session={session} done={refresh} />}{tab === "trash" && isAdmin && <TrashView data={removals} done={refresh} session={session} />}{tab === "audit" && isAdmin && <AuditView entries={audit} users={users} />}</main>
  </div>;
}

function Overview({ session, tasks, kbs, go }: { session: Session; tasks: Task[]; kbs: KB[]; go: (value: string) => void }) {
  return <section className="wp-page"><Title eyebrow={`Guten Tag, ${session.display_name.split(" ")[0]}`} title="Was möchtest du heute erledigen?" /><div className="wp-cards"><button onClick={() => go("upload")}><FileUp /><div><strong>Dokument bereitstellen</strong><span>Datei ablegen, Ziel wählen – Vinci übernimmt die Prüfung.</span></div><ChevronRight /></button><button onClick={() => go("tasks")}><Clock3 /><div><strong>{tasks.length ? `${tasks.length} offene Vorgänge` : "Keine offenen Vorgänge"}</strong><span>{tasks.length ? "Entscheidungen und Freigaben warten auf dich." : "Im Moment ist alles erledigt."}</span></div><ChevronRight /></button></div><h2>Deine Wissensbereiche</h2><div className="wp-kbs">{kbs.length ? kbs.map(kb => <article key={kb.knowledgebase_id}><ShieldCheck /><div><strong>{kb.label}</strong><span>{kb.purpose || "Für Upload freigegeben"}</span></div></article>) : <p>Dir ist aktuell noch kein Uploadbereich zugeordnet.</p>}</div></section>;
}

function Title({ eyebrow, title, text }: { eyebrow: string; title: string; text?: string }) { return <div className="wp-title"><div><p>{eyebrow}</p><h1>{title}</h1>{text && <span>{text}</span>}</div></div>; }

function Upload({ session, kbs, done }: { session: Session; kbs: KB[]; done: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null), [kb, setKb] = useState(kbs[0]?.knowledgebase_id || ""), [title, setTitle] = useState("");
  const [days, setDays] = useState(60), [confidentiality, setConfidentiality] = useState("internal"), [busy, setBusy] = useState(false);
  const [validityMode, setValidityMode] = useState("workdays"), [validUntil, setValidUntil] = useState("");
  const [result, setResult] = useState<UploadResult | null>(null), [message, setMessage] = useState("");
  const [job, setJob] = useState<UploadJob | null>(null);
  const [ownerCandidates,setOwnerCandidates]=useState<PortalUser[]>([]),[canProposeOwner,setCanProposeOwner]=useState(false),[ownerUserId,setOwnerUserId]=useState(session.user_id);
  useEffect(()=>{void api<any>("/portal/owner-candidates").then(payload=>{setCanProposeOwner(payload.can_propose_other);setOwnerCandidates(payload.users);});},[]);
  // PRD 12.3: Die Verarbeitung laeuft serverseitig weiter. Die laufende Job-ID wird
  // deshalb gemerkt, damit der Vorgang nach Reload oder Tabwechsel wieder erscheint.
  const follow = useCallback(async (jobId: string, known?: UploadJob) => {
    setBusy(true); setMessage("");
    try {
      sessionStorage.setItem(RUNNING_UPLOAD_JOB, jobId);
      let current = known ?? await api<UploadJob>(`/portal/upload-jobs/${jobId}`); setJob(current);
      while (!["completed", "failed"].includes(current.status)) {
        await new Promise(resolve => window.setTimeout(resolve, 700));
        current = await api<UploadJob>(`/portal/upload-jobs/${jobId}`); setJob(current);
      }
      if (current.status === "failed") throw new Error(current.error_code || "Verarbeitung fehlgeschlagen");
      if (!current.result) throw new Error("Verarbeitungsergebnis fehlt");
      setResult(current.result); await done();
    } catch (cause) { setMessage(friendlyError(cause, "Upload fehlgeschlagen")); }
    finally { sessionStorage.removeItem(RUNNING_UPLOAD_JOB); setBusy(false); }
  }, [done]);
  useEffect(() => {
    const running = sessionStorage.getItem(RUNNING_UPLOAD_JOB);
    if (!running) return;
    const timer = window.setTimeout(() => void follow(running), 0);
    return () => window.clearTimeout(timer);
  }, [follow]);
  function chooseFile(next: File | null) {
    setFile(next);
    // Nur vorbelegen, solange nichts Eigenes eingetragen ist.
    if (next && !title.trim()) setTitle(titleFromFilename(next.name));
  }
  async function submit() {
    if (!file || !kb || !title.trim()) return setMessage("Bitte Datei, Titel und Wissensbereich auswählen.");
    if (validityMode === "date" && !validUntil) return setMessage("Bitte ein Datum für die Gültigkeit wählen.");
    setBusy(true); setMessage("");
    try {
      const form = new FormData(); form.append("file", file); form.append("knowledgebase_id", kb);
      form.append("title", title.trim());
      // PRD 17.1: Arbeitstage oder ein geprüftes Datum, niemals beides. Die
      // Umrechnung bleibt serverseitig, damit Feiertage verbindlich zählen.
      if (validityMode === "date") form.append("valid_until", validUntil); else form.append("valid_workdays", String(days));
      form.append("confidentiality", confidentiality); form.append("owner_user_id", ownerUserId);
      const response = await fetch(`${API}/portal/upload-jobs`, { method: "POST", credentials: "include", body: form });
      const created = await response.json(); if (!response.ok) throw new Error(created.detail || "Upload fehlgeschlagen");
      await follow(created.job_id, created);
    } catch (cause) { setMessage(friendlyError(cause, "Upload fehlgeschlagen")); setBusy(false); }
  }
  async function action(value: string, targetDocumentId?:string) { if (!result) return; setBusy(true); try { await api(`/portal/cases/${result.case_id}/action`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: value, target_document_id: targetDocumentId }) }); setResult(null); setFile(null); setTitle(""); setMessage("Weitergeleitet. Das Dokument wird erst nach der Freigabe in Vinci auffindbar; du wirst benachrichtigt."); await done(); } catch (cause) { setMessage(friendlyError(cause, "Aktion fehlgeschlagen")); } finally { setBusy(false); } }
  return <section className="wp-page narrow"><Title eyebrow="Neues Wissen" title="Dokument bereitstellen" text="Du legst nur die Datei ab. Das Portal prüft Sicherheit, Aufbereitung und ähnliche Inhalte." />{!result ? <div className="wp-form"><label className={`wp-drop ${file ? "selected" : ""}`} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); chooseFile(e.dataTransfer.files[0] || null); }}>{file ? <><CheckCircle2 /><strong>{file.name}</strong><span>{(file.size / 1048576).toFixed(1)} MB · Datei ändern</span></> : <><FileUp /><strong>Datei hier ablegen</strong><span>oder klicken und auswählen · maximal 50 MB</span></>}<input type="file" accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv" onChange={e => chooseFile(e.target.files?.[0] || null)} /></label><div className="wp-grid"><label>Titel<input value={title} onChange={e => setTitle(e.target.value)} placeholder="Worum geht es?" /></label><label>Ziel-Wissensbereich<select value={kb} onChange={e => setKb(e.target.value)}><option value="">Bitte wählen</option>{kbs.map(item => <option key={item.knowledgebase_id} value={item.knowledgebase_id}>{item.label}</option>)}</select></label><label>Gültigkeit<select value={validityMode} onChange={e => setValidityMode(e.target.value)}><option value="workdays">Für eine Anzahl Arbeitstage</option><option value="date">Bis zu einem Datum</option></select></label>{validityMode === "workdays" ? <label>Arbeitstage<select value={days} onChange={e => setDays(Number(e.target.value))}>{[60,45,30,20,10].map(value => <option key={value}>{value}</option>)}</select></label> : <label>Gültig bis<input type="date" value={validUntil} onChange={e => setValidUntil(e.target.value)} /></label>}<label>Mindesteinstufung<select value={confidentiality} onChange={e => setConfidentiality(e.target.value)}><option value="internal">Intern</option><option value="restricted">Bereichsbeschränkt</option><option value="confidential">Vertraulich</option></select></label></div><div className="wp-owner"><ShieldCheck /><div><strong>Dokument-Owner</strong>{canProposeOwner?<><select value={ownerUserId} onChange={e=>setOwnerUserId(e.target.value)}><option value={session.user_id}>{session.display_name} ({session.email})</option>{ownerCandidates.filter(user=>user.user_id!==session.user_id).map(user=><option key={user.user_id} value={user.user_id}>{user.display_name} ({user.email})</option>)}</select><span>Ein anderer Owner muss die Übernahme ausdrücklich bestätigen.</span></>:<span>{session.email} · Erinnerungen werden automatisch deinem Konto zugeordnet.</span>}</div></div>{job && busy && <div className="wp-owner" role="status"><LoaderCircle className="spin"/><div><strong>{stepText[job.step] || stepText.uploaded}</strong><span>{job.progress}% abgeschlossen – du kannst diese Seite verlassen, die Prüfung läuft weiter.</span></div></div>}{message && <p className="wp-message">{message}</p>}<button className="wp-primary" disabled={busy || !file || !kb} onClick={() => void submit()}>{busy && <LoaderCircle className="spin" />} Sicher prüfen</button></div> : <div className="wp-result">{result.status === "duplicate_blocked" ? <XCircle className="red" /> : result.requires_admin ? <AlertTriangle className="amber" /> : <CheckCircle2 className="green" />}<h2>{result.status === "duplicate_blocked" ? "Dokument bereits vorhanden" : result.matches.length ? "Ähnliche Inhalte gefunden" : "Prüfung abgeschlossen"}</h2><p>{result.owner_confirmation_required ? "Der vorgeschlagene Owner muss die Verantwortung zuerst bestätigen." : result.requires_admin ? "Dieser Fall wird nach deiner Auswahl direkt einem Admin vorgelegt." : "Wähle, wie es weitergehen soll."}</p><div className="wp-owner"><ShieldCheck/><div><strong>Automatische Einstufung: {confidentialityText[result.confidentiality]||result.confidentiality}</strong><span>{result.confidentiality_reason}</span></div></div>{result.conversion_quality&&qualityRating[result.conversion_quality]&&<div className={`wp-quality ${qualityRating[result.conversion_quality].tone}`} role="status">{result.conversion_quality==="good"?<CheckCircle2/>:result.conversion_quality==="low"?<AlertTriangle/>:<XCircle/>}<div><strong>Aufbereitung: {qualityRating[result.conversion_quality].title}</strong><span>{qualityRating[result.conversion_quality].text}</span></div></div>}{result.conversion_issues&&result.conversion_issues.length>0&&<div className="wp-alert"><AlertTriangle/><div><strong>Aufbereitung muss geprüft werden</strong>{result.conversion_issues.map(issue=><span key={issue}>{conversionIssueText(issue)}</span>)}</div></div>}{result.matches.map(match => <article key={match.document_id} className="wp-match"><div><strong>{match.title}</strong><span>{match.has_conflict ? `Möglicher Widerspruch${match.conflict_count ? ` in ${match.conflict_count} Textstelle${match.conflict_count===1?"":"n"}` : ""}` : match.version_candidate ? "Mögliche neue Version" : "Ähnlicher Inhalt"}</span>{match.knowledgebase_ids?.length ? <small>Bereits in: {match.knowledgebase_ids.join(", ")}</small> : null}</div><span className="wp-match-level"><strong>{matchLevelText[match.level] || match.level}</strong>{typeof match.match_percent === "number" ? <small>{match.match_percent} % Übereinstimmung</small> : null}</span>{match.version_candidate&&!match.has_conflict&&<button onClick={()=>void action("replace",match.document_id)}>Dieses Dokument als neue Version ersetzen</button>}</article>)}{!result.owner_confirmation_required&&["pending_employee_decision","duplicate_blocked"].includes(result.status)&&<div className="wp-actions">{!result.exact_duplicate_document_id && <button onClick={() => void action("create")}>Als neues Dokument vorschlagen</button>}{result.exact_duplicate_document_id && <button onClick={() => void action("publish_existing")}>Vorhandenes zusätzlich veröffentlichen</button>}<button className="secondary" onClick={() => void action("discard")}>Verwerfen</button></div>}</div>}</section>;
}

function Tasks({ tasks, session, done }: { tasks: Task[]; session: Session; done: () => Promise<void> }) {
  const [reason, setReason] = useState<Record<string,string>>({}), [busy, setBusy] = useState("");
  const [review, setReview] = useState<any>(null), [revision, setRevision] = useState(""), [confirmed, setConfirmed] = useState(false);
  const canDecide = session.role !== "employee", isAdmin = ["admin","portal_admin"].includes(session.role);
  const ownDecision = (status: string) =>
    ["pending_employee_decision", "duplicate_blocked"].includes(status);
  async function chooseAction(caseId: string, action: string) {
    setBusy(caseId);
    try {
      await api(`/portal/cases/${caseId}/action`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})});
      await done();
    } finally { setBusy(""); }
  }
  async function decide(caseId: string, decision: string) { setBusy(caseId); try { await api(`/portal/cases/${caseId}/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, reason: reason[caseId] || (decision === "approve" ? "Fachlich geprüft und freigegeben" : "Zur weiteren Prüfung") }) }); await done(); } finally { setBusy(""); } }
  async function openReview(caseId: string) { const payload = await api<any>(`/portal/cases/${caseId}/review`); setReview(payload); setRevision(isAdmin ? payload.markdown : ""); setConfirmed(false); }
  async function revise() { if (!review) return; setBusy(review.case.case_id); try { await api(`/portal/cases/${review.case.case_id}/revision`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({instruction:isAdmin?"":revision,replacement_markdown:isAdmin?revision:"",reason:reason[review.case.case_id]||"Freigegebene Korrektur",confirmed})}); setReview(null); await done(); } finally {setBusy("");} }
  if (review) return <section className="wp-page"><Title eyebrow="Dokumentprüfung" title={review.case.title} text={isAdmin ? "Original und RAG-Markdown können direkt miteinander verglichen werden." : "Original und aufbereitete Fassung können direkt miteinander verglichen werden."} /><div className="wp-actions"><a className="wp-primary" target="_blank" rel="noreferrer" href={review.original_url}>Original öffnen</a><button onClick={() => setReview(null)}>Zurück</button></div><div className="wp-form"><label>{isAdmin ? "RAG-Markdown bearbeiten" : "Aufbereitete Fassung"}<textarea rows={22} readOnly={!isAdmin} value={isAdmin ? revision : review.markdown} onChange={e => isAdmin && setRevision(e.target.value)} /></label>{(isAdmin || session.role === "employee") && <><label>{isAdmin ? "Begründung" : "Korrektur in Alltagssprache"}<textarea value={isAdmin ? (reason[review.case.case_id]||"") : revision} onChange={e => isAdmin ? setReason({...reason,[review.case.case_id]:e.target.value}) : setRevision(e.target.value)} /></label><label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> Ich gebe diese Korrektur ausdrücklich zur Verarbeitung frei.</label><button className="wp-primary" disabled={!confirmed || busy === review.case.case_id} onClick={() => void revise()}>Neue Entwurfsversion anlegen und vollständig prüfen</button></>}</div></section>;
  return <section className="wp-page"><Title eyebrow="Arbeitsvorrat" title={session.role === "employee" ? "Meine Vorgänge" : "Offene Freigaben"} text="Du siehst nur Vorgänge, für die du zuständig bist." /><div className="wp-task-list">{tasks.length ? tasks.map(task => <article key={task.case_id}><div className="wp-task-icon"><FileSearch /></div><div className="wp-task-copy"><Badge status={task.status} /><h2>{task.title}</h2><p>{task.original_filename} · {task.target_knowledgebase_id}</p><p className="wp-reason">{reviewReason[task.status] || "Wartet auf eine Entscheidung."}</p>{task.requires_admin && <span className="wp-escalated"><AlertTriangle /> Adminentscheidung erforderlich</span>}<div className="wp-task-buttons"><button className="wp-secondary" onClick={() => void openReview(task.case_id)}>Original und Markdown prüfen</button>{ownDecision(task.status)&&<>{task.status==="duplicate_blocked"?<button className="wp-secondary approve" disabled={busy===task.case_id} onClick={()=>void chooseAction(task.case_id,"publish_existing")}>Vorhandenes zusätzlich veröffentlichen</button>:<button className="wp-secondary approve" disabled={busy===task.case_id} onClick={()=>void chooseAction(task.case_id,"create")}>Als neues Dokument vorschlagen</button>}<button className="wp-secondary" disabled={busy===task.case_id} onClick={()=>void chooseAction(task.case_id,"discard")}>Verwerfen</button></>}</div></div>{canDecide && task.status.includes("approval") && <div className="wp-task-actions"><textarea placeholder="Kurze Begründung" value={reason[task.case_id] || ""} onChange={e => setReason({...reason,[task.case_id]:e.target.value})} /><div><button onClick={() => void decide(task.case_id,"reject")}>Ablehnen</button><button onClick={() => void decide(task.case_id,"escalate")}>Weiterleiten</button><button className="approve" disabled={busy === task.case_id} onClick={() => void decide(task.case_id,"approve")}>Freigeben</button></div></div>}</article>) : <div className="wp-empty"><CheckCircle2 /><h2>Alles erledigt</h2><p>Aktuell wartet kein Vorgang auf dich.</p></div>}</div></section>;
}

function UserAdmin({ users, session, done }: { users: PortalUser[]; session: Session; done: () => Promise<void> }) {
  const [selected, setSelected] = useState(users[0]?.user_id || "");
  const [access, setAccess] = useState<UserAccess[]>([]);
  const [message, setMessage] = useState("");
  const [ownerPermission,setOwnerPermission]=useState(false);
  const [delegations,setDelegations]=useState<any[]>([]),[delegationManager,setDelegationManager]=useState(""),[delegate,setDelegate]=useState(""),[validUntil,setValidUntil]=useState("");
  const [absences,setAbsences]=useState<any[]>([]),[absenceManager,setAbsenceManager]=useState(""),[absentFrom,setAbsentFrom]=useState(""),[absentUntil,setAbsentUntil]=useState(""),[absenceReason,setAbsenceReason]=useState("");
  const managers = users.filter(user => ["manager", "admin", "portal_admin"].includes(user.role) && user.active);
  const current = users.find(user => user.user_id === selected);
  useEffect(() => { void Promise.all([api<any>("/portal/admin/delegations"),api<any>("/portal/admin/absences")]).then(([delegationPayload,absencePayload])=>{setDelegations(delegationPayload.delegations);setAbsences(absencePayload.absences);}); }, []);
  useEffect(() => {
    if (!selected) return;
    void api<{access: UserAccess[]}>(`/portal/admin/users/${selected}/knowledgebase-access`)
      .then(payload => setAccess(payload.access)).catch(cause => setMessage(friendlyError(cause, "Rechte konnten nicht geladen werden")));
    void api<{allowed:boolean}>(`/portal/admin/users/${selected}/owner-proposal-permission`).then(payload=>setOwnerPermission(payload.allowed));
  }, [selected]);
  async function beginRoleChange(userId: string, role: Role) {
    const start = await api<{authorization_url:string}>("/portal/auth/step-up/start?return_to=/wissen/");
    sessionStorage.setItem("pending-role-change", JSON.stringify({userId,role}));
    window.location.assign(start.authorization_url);
  }
  async function setManager(manager_user_id: string) {
    if (!current) return;
    await api(`/portal/admin/users/${current.user_id}/manager`, { method: "PATCH", headers: {"Content-Type":"application/json"}, body: JSON.stringify({manager_user_id: manager_user_id || null}) });
    setMessage("Führungskraft wurde gespeichert."); await done();
  }
  async function setOwnerProposalPermission(allowed:boolean){if(!current)return;await api(`/portal/admin/users/${current.user_id}/owner-proposal-permission`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({allowed})});setOwnerPermission(allowed);setMessage("Owner-Vorschlagsrecht wurde gespeichert.");}
  async function setRight(item: UserAccess, field: "can_read" | "can_upload", value: boolean) {
    if (!current) return;
    const next = {...item, [field]: value};
    await api(`/portal/admin/users/${current.user_id}/knowledgebase-access`, { method: "PUT", headers: {"Content-Type":"application/json"}, body: JSON.stringify({knowledgebase_id:item.knowledgebase_id,can_read:Boolean(next.can_read),can_upload:Boolean(next.can_upload)}) });
    setAccess(rows => rows.map(row => row.knowledgebase_id === item.knowledgebase_id ? next : row));
    setMessage("Berechtigung wurde gespeichert.");
  }
  async function saveDelegation(){if(!delegationManager||!delegate)return;await api("/portal/admin/delegations",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({manager_user_id:delegationManager,delegate_user_id:delegate,valid_from:null,valid_until:validUntil||null})});setMessage("Vertretung gespeichert.");setDelegations((await api<any>("/portal/admin/delegations")).delegations);}
  async function removeDelegation(item:any){await api(`/portal/admin/delegations?manager_user_id=${encodeURIComponent(item.manager_user_id)}&delegate_user_id=${encodeURIComponent(item.delegate_user_id)}`,{method:"DELETE"});setDelegations(rows=>rows.filter(row=>row!==item));}
  async function saveAbsence(){if(!absenceManager||!absentFrom||!absentUntil||!absenceReason.trim())return setMessage("Bitte Führungskraft, Zeitraum und Grund angeben.");await api("/portal/admin/absences",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({manager_user_id:absenceManager,absent_from:absentFrom,absent_until:absentUntil,reason:absenceReason.trim()})});setMessage("Abwesenheit gespeichert; neue Fälle gehen im Zeitraum direkt an die Vertretung.");setAbsences((await api<any>("/portal/admin/absences")).absences);}
  return <section className="wp-page"><Title eyebrow="Administration" title="Benutzer und Rechte" text="Rollen, Führungskräfte sowie Lese- und Uploadrechte werden hier zentral verwaltet." />
    {message && <p className="wp-message">{message}</p>}
    <div className="wp-users">{users.map(user => <article key={user.user_id} className={selected === user.user_id ? "selected" : ""}><div className="wp-avatar">{user.display_name.slice(0,2).toUpperCase()}</div><button type="button" className="wp-pick" aria-pressed={selected === user.user_id} onClick={() => setSelected(user.user_id)}><strong>{user.display_name}</strong><span>{user.email}</span></button><select value={user.role} disabled={session.role !== "portal_admin" && ["admin","portal_admin"].includes(user.role)} onChange={e => void beginRoleChange(user.user_id,e.target.value as Role)}><option value="employee">Mitarbeiter</option><option value="manager">Führungskraft</option><option value="admin">Admin</option>{session.role === "portal_admin" && <option value="portal_admin">Portal-Admin</option>}</select><Badge status={user.active ? "active" : "Deaktiviert"} /></article>)}</div>
    <div className="wp-form"><h2>Vertretungen</h2><div className="wp-grid"><label>Führungskraft<select value={delegationManager} onChange={e=>setDelegationManager(e.target.value)}><option value="">Bitte wählen</option>{managers.map(user=><option key={user.user_id} value={user.user_id}>{user.display_name}</option>)}</select></label><label>Vertretung<select value={delegate} onChange={e=>setDelegate(e.target.value)}><option value="">Bitte wählen</option>{users.filter(user=>user.active).map(user=><option key={user.user_id} value={user.user_id}>{user.display_name}</option>)}</select></label><label>Gültig bis<input type="date" value={validUntil} onChange={e=>setValidUntil(e.target.value)}/></label></div><button className="wp-primary" onClick={()=>void saveDelegation()}>Vertretung speichern</button>{delegations.map(item=><p key={`${item.manager_user_id}-${item.delegate_user_id}`}>{users.find(u=>u.user_id===item.manager_user_id)?.display_name} → {users.find(u=>u.user_id===item.delegate_user_id)?.display_name} bis {item.valid_until||'offen'} <button onClick={()=>void removeDelegation(item)}>Entfernen</button></p>)}</div>
    <div className="wp-form"><h2>Abwesenheiten</h2><p>Während des eingetragenen Zeitraums erhalten die hinterlegten Vertretungen neue Freigaben sofort.</p><div className="wp-grid"><label>Führungskraft<select value={absenceManager} onChange={e=>setAbsenceManager(e.target.value)}><option value="">Bitte wählen</option>{managers.map(user=><option key={user.user_id} value={user.user_id}>{user.display_name}</option>)}</select></label><label>Von<input type="date" value={absentFrom} onChange={e=>setAbsentFrom(e.target.value)}/></label><label>Bis<input type="date" value={absentUntil} onChange={e=>setAbsentUntil(e.target.value)}/></label><label>Grund<input value={absenceReason} onChange={e=>setAbsenceReason(e.target.value)} placeholder="z. B. Urlaub"/></label></div><button className="wp-primary" onClick={()=>void saveAbsence()}>Abwesenheit speichern</button>{absences.map(item=><p key={item.manager_user_id}>{users.find(u=>u.user_id===item.manager_user_id)?.display_name} · {item.absent_from} bis {item.absent_until} · {item.reason}</p>)}</div>
    {current && <div className="wp-form"><h2>Zuordnung für {current.display_name}</h2><label>Führungskraft<select value={current.manager_user_id || ""} onChange={e => void setManager(e.target.value)}><option value="">Keine Führungskraft</option>{managers.filter(user => user.user_id !== current.user_id).map(user => <option key={user.user_id} value={user.user_id}>{user.display_name}</option>)}</select></label><label><input type="checkbox" checked={ownerPermission} onChange={e=>void setOwnerProposalPermission(e.target.checked)}/> Darf beim Upload einen anderen aktiven Owner vorschlagen</label><h2>Wissensbereiche</h2><div className="wp-kbs">{access.map(item => <article key={item.knowledgebase_id}><div><strong>{item.label}</strong><span>{item.knowledgebase_id}</span></div><label><input type="checkbox" checked={Boolean(item.can_read)} onChange={e => void setRight(item,"can_read",e.target.checked)} /> Lesen</label><label><input type="checkbox" checked={Boolean(item.can_upload)} onChange={e => void setRight(item,"can_upload",e.target.checked)} /> Hochladen</label></article>)}</div></div>}
  </section>;
}


function countList(
  counts: Record<string, number> | undefined,
  labels: Record<string, string>,
  empty: string,
) {
  const rows = Object.entries(counts || {});
  if (!rows.length) return <p className="wp-empty-hint">{empty}</p>;
  return <div className="wp-counts">{rows.map(([key, value]) =>
    <article key={key}><strong>{value}</strong><span>{labels[key] || key}</span></article>)}</div>;
}

function AuditView({ entries, users }: { entries: AuditEntry[]; users: PortalUser[] }) {
  // Rohe UUIDs sagen niemandem etwas. Die Benutzerliste ist ohnehin geladen.
  const nameOf = (userId: string) =>
    users.find(user => user.user_id === userId)?.display_name || userId;
  // Betroffene Objekte ebenfalls benennen; eine UUID allein sagt nichts.
  const labelOf = (subjectType: string, subjectId: string) =>
    subjectType === "user" ? nameOf(subjectId) : subjectId;
  return <section className="wp-page"><Title eyebrow="Nachvollziehbarkeit" title="Auditprotokoll" text="Kritische Aktionen aus Rollenverwaltung und Dokumentlebenszyklus in einer gemeinsamen Ansicht." /><div className="wp-actions"><a className="wp-primary" href={`${API}/portal/admin/audit/export.csv`}>CSV exportieren</a><a className="wp-primary" href={`${API}/portal/admin/audit/export.pdf`}>PDF exportieren</a></div><div className="wp-task-list">{entries.map((entry, index) => <article key={`${entry.occurred_at}-${index}`}><div className="wp-task-icon"><ShieldCheck /></div><div className="wp-task-copy"><Badge status={entry.event_type} /><h2>{subjectText[entry.subject_type]||entry.subject_type}: {labelOf(entry.subject_type, entry.subject_id)}</h2><p>{new Date(entry.occurred_at).toLocaleString("de-DE")} · {nameOf(entry.actor_user_id)}</p></div></article>)}</div></section>;
}


function FeedbackForm() {
  const [context, setContext] = useState<any>(null), [reason, setReason] = useState("incorrect"), [comment, setComment] = useState(""), [message, setMessage] = useState("");
  const [screenshot, setScreenshot] = useState<File | null>(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search), chatId = params.get("chat_id"), messageId = params.get("message_id");
    if (!chatId || !messageId) return;
    void api<any>(`/portal/feedback/context?chat_id=${encodeURIComponent(chatId)}&message_id=${encodeURIComponent(messageId)}`).then(setContext).catch(() => setMessage("Der Chatkontext konnte nicht automatisch geladen werden. Bitte beschreibe den Fehler kurz."));
  }, []);
  async function submit() {
    if (!context) return setMessage("Bitte öffne diese Meldung direkt über den Link unter einer Vinci-Antwort.");
    const result = await api<{feedback_id:string}>("/portal/feedback/rag", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...context,reason,comment})});
    // Der Anhang folgt der Meldung, weil er ihre Kennung braucht. Schlaegt er
    // fehl, bleibt die Meldung bestehen und der Fehler wird benannt.
    if (screenshot) {
      const form = new FormData(); form.append("file", screenshot);
      try {
        const response = await fetch(`${API}/portal/feedback/${result.feedback_id}/screenshot`,
          { method: "POST", credentials: "include", body: form });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || `request_${response.status}`);
        }
      } catch (cause) {
        setScreenshot(null); setComment("");
        return setMessage(`Die Meldung wurde unter ${result.feedback_id} angelegt, das Bild konnte aber nicht angehängt werden: ${friendlyError(cause, "unbekannter Grund")}`);
      }
    }
    setMessage(`Danke. Die Meldung wurde unter ${result.feedback_id} angelegt.`);
    setComment(""); setScreenshot(null);
  }
  return <section className="wp-page narrow"><Title eyebrow="Qualität sichern" title="Wissensfehler melden" text="Frage, Antwort, Quellen und technische Versionen werden automatisch aus dem zugehörigen Chat übernommen." /><div className="wp-form"><label>Was ist aufgefallen?<select value={reason} onChange={e => setReason(e.target.value)}><option value="incorrect">Information ist falsch</option><option value="outdated">Information ist veraltet</option><option value="conflicting_sources">Quellen widersprechen sich</option><option value="irrelevant_source">Quelle passt nicht zur Frage</option><option value="suspected_permission_issue">Ich durfte diese Information vermutlich nicht sehen</option><option value="other">Sonstiges</option></select></label><label>Ergänzung<textarea value={comment} onChange={e => setComment(e.target.value)} placeholder="Was genau sollten wir prüfen?" /></label>{context && <div className="wp-owner"><ShieldCheck /><div><strong>Chatkontext wurde sicher übernommen</strong><span>Request-ID: {context.request_id}</span></div></div>}<label>Screenshot (optional)<input type="file" accept="image/png,image/jpeg" onChange={e => setScreenshot(e.target.files?.[0] || null)} /><small className="wp-hint">PNG oder JPEG bis 5 MB. Nur Admins sehen das Bild.</small></label><button className="wp-primary" onClick={() => void submit()}>Meldung freigeben und senden</button>{message && <p className="wp-message">{message}</p>}</div></section>;
}


function KnowledgebaseAdmin({ kbs, changes, session, done }: { kbs: KB[]; changes: KBChange[]; session: Session; done: () => Promise<void> }) {
  const [kind,setKind]=useState("create"),[target,setTarget]=useState(""),[label,setLabel]=useState(""),[slug,setSlug]=useState(""),[reason,setReason]=useState("");
  const [overview,setOverview]=useState<KBOverview[]>([]),[open,setOpen]=useState("");
  useEffect(()=>{void api<{knowledgebases:KBOverview[]}>("/portal/admin/knowledgebase-overview")
    .then(payload=>setOverview(payload.knowledgebases)).catch(()=>setOverview([]));},[changes]);
  async function stepUp(action:any) { const start=await api<{authorization_url:string}>("/portal/auth/step-up/start?return_to=/wissen/"); sessionStorage.setItem("pending-admin-action",JSON.stringify(action)); window.location.assign(start.authorization_url); }
  async function requestChange() { const payload:any={}; if(kind==="create") Object.assign(payload,{label,slug,purpose:reason}); if(kind==="rename") payload.label=label; const action={path:"/portal/admin/knowledgebase-changes",method:"POST",body:{kind,knowledgebase_id:kind==="create"?null:target,payload}}; if(session.role==="portal_admin") return stepUp(action); await api(action.path,{method:action.method,headers:{"Content-Type":"application/json"},body:JSON.stringify(action.body)}); await done(); }
  async function decide(request_id:string,approve:boolean){ if(!reason.trim()) return; await stepUp({path:`/portal/admin/knowledgebase-changes/${request_id}/decision`,method:"POST",body:{approve,reason}}); }
  return <section className="wp-page"><Title eyebrow="Administration" title="Knowledge Bases verwalten" text="Normale Admins bereiten Änderungen vor; Portal-Admins geben sie frei oder führen sie direkt aus." /><div className="wp-form"><div className="wp-grid"><label>Aktion<select value={kind} onChange={e=>setKind(e.target.value)}><option value="create">Neu anlegen</option><option value="rename">Umbenennen</option><option value="archive">Archivieren</option><option value="delete">Endgültig entfernen</option></select></label>{kind!=="create"&&<label>Knowledge Base<select value={target} onChange={e=>setTarget(e.target.value)}><option value="">Bitte wählen</option>{kbs.map(k=><option key={k.knowledgebase_id} value={k.knowledgebase_id}>{k.label}</option>)}</select></label>}{["create","rename"].includes(kind)&&<label>Name<input value={label} onChange={e=>setLabel(e.target.value)}/></label>}{kind==="create"&&<label>Kurzname<input value={slug} onChange={e=>setSlug(e.target.value)} placeholder="z. B. service"/></label>}</div><label>Zweck oder Begründung<textarea value={reason} onChange={e=>setReason(e.target.value)}/></label><button className="wp-primary" onClick={()=>void requestChange()}>Änderung einreichen</button></div><h2>Wissensbereiche und ihre Dokumente</h2><div className="wp-kb-overview">{overview.length ? overview.map(base=><article key={base.knowledgebase_id} className={open===base.knowledgebase_id?"selected":""}><button type="button" className="wp-kb-head" aria-expanded={open===base.knowledgebase_id} onClick={()=>setOpen(current=>current===base.knowledgebase_id?"":base.knowledgebase_id)}><ChevronRight className={open===base.knowledgebase_id?"wp-rot":""}/><span><strong>{base.label}</strong><small>{base.purpose||base.slug}</small></span><span className="wp-kb-count">{base.document_count} {base.document_count===1?"Dokument":"Dokumente"}</span></button>{open===base.knowledgebase_id&&<div className="wp-kb-docs">{base.documents.length ? <table><thead><tr><th>Titel</th><th>Status</th><th>Owner</th><th>Gültig bis</th></tr></thead><tbody>{base.documents.map(doc=><tr key={doc.document_id}><td>{doc.title}</td><td>{statusText[doc.status]||doc.status}</td><td>{doc.owner_name}</td><td>{doc.valid_until||"offen"}</td></tr>)}</tbody></table> : <p className="wp-empty-hint">Diesem Wissensbereich ist noch kein Dokument zugeordnet.</p>}</div>}</article>) : <p className="wp-empty-hint">Es ist noch kein Wissensbereich angelegt.</p>}</div><h2>Änderungsanträge</h2><div className="wp-task-list">{changes.map(change=><article key={change.request_id}><div className="wp-task-copy"><Badge status={change.status}/><h2>{change.kind} · {change.knowledgebase_id||change.payload?.label}</h2><p>Beantragt von {change.requested_by}</p></div>{session.role==="portal_admin"&&change.status==="pending"&&<div className="wp-actions"><button onClick={()=>void decide(change.request_id,false)}>Ablehnen</button><button className="approve" onClick={()=>void decide(change.request_id,true)}>Freigeben</button></div>}</article>)}</div></section>;
}


function QualityDashboardView({data}:{data:any}) {
  if(!data) return <section className="wp-page"><LoaderCircle className="spin"/></section>;
  const cards=[['Aktive Dokumente',data.active_documents],['Ablauf in ≤ 15 Arbeitstagen',data.expiring_within_15_workdays],['Offene Wissensfehler',data.open_feedback],['Offene Systemincidents',data.open_incidents],['Ausstehende Mails',data.mail?.pending],['Fehlgeschlagene Mails',data.mail?.failed],['Führungskräfte ohne Vertretung',data.governance?.managers_without_delegate],['Dokumente ohne gültige Verantwortung',data.governance?.documents_without_active_owner_or_manager]];
  return <section className="wp-page"><Title eyebrow="Qualität und Betrieb" title="Admin-Qualitätsdashboard" text="Freigaben, Migration, Index, Backup und Incidents auf einen Blick."/><div className="wp-cards">{cards.map(([label,value])=><article key={String(label)}><div><strong>{String(value??0)}</strong><span>{label}</span></div></article>)}</div><div className="wp-kbs"><article><ShieldCheck/><div><strong>Hybridindex</strong><span>{data.index?.ok?'Erreichbar':'Nicht erreichbar'}</span></div></article><article><ShieldCheck/><div><strong>Letztes Backup</strong><span>{data.backup?.last_backup||'Noch nicht ausgeführt'}</span></div></article><article><ShieldCheck/><div><strong>Letzter Restore-Test</strong><span>{data.backup?.last_restore_test||'Noch nicht ausgeführt'}</span></div></article></div><h2>Vorgänge nach Status</h2>{countList(data.workflow_cases, statusText, "Aktuell sind keine Vorgänge offen.")}<h2>Migration</h2>{countList(data.migration, statusText, "Es läuft keine Migration.")}</section>;
}


function QualityCasesView({data}:{data:any}) {
 const rows=[...(data?.incidents||[]).map((item:any)=>({...item,type:'Systemincident',id:item.incident_id,summary:item.step})),...(data?.feedback||[]).map((item:any)=>({...item,type:'Wissensfehler',id:item.feedback_id,summary:item.reason}))];
 return <section className="wp-page"><Title eyebrow="Prüfung erforderlich" title="Qualitätsfälle" text="Kritische Rechte- und Systemfälle sowie fachliche Wissensfehler werden zentral bearbeitet."/><div className="wp-task-list">{rows.length?rows.map((item:any)=><article key={item.id}><div className="wp-task-icon"><AlertTriangle/></div><div className="wp-task-copy"><Badge status={item.severity||'normal'}/><h2>{item.type}: {item.summary}</h2><p>{item.id} · {item.created_at}</p>{item.comment&&<span>{item.comment}</span>}</div></article>):<div className="wp-empty"><CheckCircle2/><h2>Keine offenen Qualitätsfälle</h2></div>}</div></section>;
}


function DocumentList({documents,changes,ownershipTasks,users,session,done}:{documents:PortalDocument[];changes:any[];ownershipTasks:OwnershipTask[];users:PortalUser[];session:Session;done:()=>Promise<void>}) {
  const [selected,setSelected]=useState(""),[reason,setReason]=useState(""),[confirmed,setConfirmed]=useState(false),[desired,setDesired]=useState("restricted"),[proposedOwner,setProposedOwner]=useState("");
  const [message,setMessage]=useState("");
  // Ein zweiter Klick schliesst die Kachel wieder, statt sie offen zu lassen.
  const toggle = (documentId: string) =>
    setSelected(current => { setMessage(""); return current === documentId ? "" : documentId; });

  // Alle Antraege verlangen serverseitig eine Begruendung. Fehlte sie, brach die
  // Aktion vorher wortlos ab; nichts geschah und niemand erfuhr warum.
  async function run(what: string, call: () => Promise<unknown>, needsReason = true) {
    if (needsReason && reason.trim().length < 3) {
      return setMessage("Bitte gib zuerst eine Begründung mit mindestens drei Zeichen ein.");
    }
    try {
      await call();
      setReason(""); setConfirmed(false); setMessage(`${what} wurde eingereicht.`);
      await done();
    } catch (cause) {
      setMessage(friendlyError(cause, `${what} ist fehlgeschlagen.`));
    }
  }

  const post = (path: string, body: Record<string, unknown>) =>
    api(path, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});

  const requestRemoval = (kind:string) => run(
    kind === "delete" ? (["admin","portal_admin"].includes(session.role) ? "Die Verschiebung in den Papierkorb" : "Der Löschantrag") : "Der Deaktivierungsantrag",
    () => post("/portal/removal-requests", {document_id:selected,kind,reason}));
  const renewal = () => run("Die Verlängerung",
    () => post("/portal/document-changes/renewal", {document_id:selected,reason,confirmed}));
  const classification = () => run("Die Einstufungsänderung",
    () => post("/portal/document-changes/confidentiality", {document_id:selected,desired,reason}));
  const decide = (id:string,approve:boolean) => run(approve?"Die Freigabe":"Die Ablehnung",
    () => post(`/portal/document-changes/${id}/decision`, {approve,reason:reason||"Geprüft und entschieden"}), false);
  const proposeOwner = (id:string) => run("Die Übernahmeanfrage",
    () => post(`/portal/ownership-tasks/${id}/proposal`, {proposed_owner_user_id:proposedOwner,reason:reason||"Fachliche Zuständigkeit neu zugeordnet"}), false);
  const confirmOwner = (id:string,accept:boolean) => run(accept?"Die Übernahme":"Die Ablehnung",
    () => post(`/portal/ownership-tasks/${id}/confirmation`, {accept,reason:reason||"Übernahme geprüft"}), false);

  return <section className="wp-page"><Title eyebrow="Wissensbestand" title="Dokumente" text="Gültigkeit, Vertraulichkeit und Entfernung werden nachvollziehbar beantragt und freigegeben."/>
    <div className="wp-doc-list">{documents.length ? documents.map(doc=>{
      const open = selected===doc.document_id;
      return <article key={`${doc.document_id}-${doc.knowledgebase_id}`} className={open?"selected":""}>
        {/* Kopf als Schaltflaeche: das Panel darunter enthaelt eigene Bedienelemente
            und darf deshalb nicht in einem Element mit role="button" liegen. */}
        <button type="button" className="wp-doc-head" aria-expanded={open} onClick={()=>toggle(doc.document_id)}>
          <span className="wp-task-icon"><FileSearch/></span>
          <span className="wp-task-copy"><Badge status={doc.status||"draft"}/><strong>{doc.title}</strong>
            <small>{doc.knowledgebase_id||"Noch nicht veröffentlicht"} · gültig bis {doc.valid_until||"offen"}</small></span>
          <ChevronRight className={open?"wp-rot":""}/>
        </button>
        {open&&<div className="wp-doc-panel">
          {doc.status!=="active"&&<p className="wp-reason">Dieses Dokument ist noch nicht aktiv. Es wird erst nach der Freigabe für Vinci auffindbar.</p>}
          <label>Begründung<textarea value={reason} onChange={e=>setReason(e.target.value)} placeholder="Warum soll das geschehen?"/></label>
          <label className="wp-check"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/> Ich bestätige, dass der Inhalt weiterhin aktuell ist.</label>
          <div className="wp-actions">
            <button onClick={()=>void renewal()}>Gültigkeit verlängern</button>
            <label>Vertraulichkeit<select value={desired} onChange={e=>setDesired(e.target.value)}><option value="internal">Intern</option><option value="restricted">Bereichsbeschränkt</option><option value="confidential">Vertraulich</option></select></label>
            <button onClick={()=>void classification()}>Einstufung ändern</button>
            <button onClick={()=>void requestRemoval("deactivate")}>Deaktivierung beantragen</button>
            <button onClick={()=>void requestRemoval("delete")}>{["admin","portal_admin"].includes(session.role)?"In Papierkorb verschieben":"Löschung beantragen"}</button>
          </div>
          {message&&<p className="wp-message">{message}</p>}
        </div>}
      </article>;
    }) : <div className="wp-empty"><CheckCircle2/><h2>Noch kein Dokument</h2><p>Sobald du etwas bereitstellst, erscheint es hier.</p></div>}</div>
    {changes.length>0&&<><h2>Änderungsaufgaben</h2><div className="wp-task-list">{changes.map(item=><article key={item.request_id}><div className="wp-task-copy"><Badge status={item.status}/><h2>{item.kind} · {item.document_id}</h2><p>{item.reason}</p></div>{["manager","admin","portal_admin"].includes(session.role)&&item.status.startsWith("pending")&&<div className="wp-actions"><button onClick={()=>void decide(item.request_id,false)}>Ablehnen</button><button className="approve" onClick={()=>void decide(item.request_id,true)}>Freigeben</button></div>}</article>)}</div></>}
    {ownershipTasks.length>0&&<><h2>Owner-Neuzuordnung</h2><div className="wp-task-list">{ownershipTasks.map(task=><article key={task.task_id}><div className="wp-task-copy"><Badge status={task.status}/><h2>{task.document_id}</h2><p>{task.reason}</p></div>{["admin","portal_admin"].includes(session.role)&&task.status==="open"&&<div className="wp-task-actions"><select value={proposedOwner} onChange={e=>setProposedOwner(e.target.value)}><option value="">Neuen Owner wählen</option>{users.filter(user=>user.active).map(user=><option key={user.user_id} value={user.user_id}>{user.display_name}</option>)}</select><button className="approve" disabled={!proposedOwner} onClick={()=>void proposeOwner(task.task_id)}>Übernahme anfragen</button></div>}{task.status==="pending_owner_confirmation"&&task.proposed_owner_user_id===session.user_id&&<div className="wp-actions"><button onClick={()=>void confirmOwner(task.task_id,false)}>Ablehnen</button><button className="approve" onClick={()=>void confirmOwner(task.task_id,true)}>Verantwortung übernehmen</button></div>}</article>)}</div></>}
  </section>;
}


function TrashView({data,done,session}:{data:any;done:()=>Promise<void>;session:Session}) {
  const [reason,setReason]=useState<Record<string,string>>({}),[busy,setBusy]=useState("");
  const [message,setMessage]=useState(""),[pendingDelete,setPendingDelete]=useState("");
  const isPortalAdmin = session.role === "portal_admin";
  const openRequests = ((data.requests||[]) as any[]).filter(item => item.status === "pending");

  async function call(id: string, what: string, path: string, body: Record<string, unknown>) {
    setBusy(id); setMessage("");
    try {
      await api(path, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      setMessage(`${what} wurde ausgeführt.`);
      await done();
    } catch (cause) {
      setMessage(friendlyError(cause, `${what} ist fehlgeschlagen.`));
    } finally { setBusy(""); setPendingDelete(""); }
  }

  const decide = (id:string,approve:boolean) => call(id, approve?"Die Bestätigung":"Die Ablehnung",
    `/portal/admin/removal-requests/${id}/decision`, {approve,reason:reason[id]||"Adminentscheidung"});
  const restore = (id:string) => call(id, "Die Wiederherstellung",
    `/portal/admin/trash/${id}/restore`, {reason:reason[id]||"Wiederherstellung durch Admin"});
  const purge = (id:string) => call(id, "Die endgültige Löschung",
    `/portal/admin/trash/${id}/delete`, {reason:reason[id]||"Endgültige Löschung durch Portal-Admin"});

  return <section className="wp-page"><Title eyebrow="Aufbewahrung" title="Papierkorb und Löschanträge" text="Dokumente bleiben mindestens 30 und höchstens 90 Tage wiederherstellbar; Legal Holds setzen die Löschung aus."/>
    {message&&<p className="wp-message">{message}</p>}
    <h2>Offene Anträge</h2>
    <div className="wp-doc-list">{openRequests.length ? openRequests.map((item:any)=>
      <article key={item.request_id}><div className="wp-trash-row">
        <div className="wp-trash-copy"><Badge status={item.kind}/><strong>{item.title||item.document_id}</strong>
          <span>{item.reason}</span><small className="wp-hint">{item.document_id}</small></div>
        <div className="wp-trash-side">
          <textarea placeholder="Begründung" value={reason[item.request_id]||""} onChange={e=>setReason({...reason,[item.request_id]:e.target.value})}/>
          <div className="wp-actions">
            <button disabled={busy===item.request_id} onClick={()=>void decide(item.request_id,false)}>Ablehnen</button>
            <button className="approve" disabled={busy===item.request_id} onClick={()=>void decide(item.request_id,true)}>Bestätigen</button>
          </div>
        </div>
      </div></article>) : <p className="wp-empty-hint">Kein offener Antrag.</p>}</div>
    <h2>Papierkorb</h2>
    <div className="wp-doc-list">{(data.trash||[]).length ? (data.trash||[]).map((item:any)=>
      <article key={item.document_id}><div className="wp-trash-row">
        <div className="wp-trash-copy"><Badge status={item.legal_hold?"Legal Hold":"Papierkorb"}/>
          <strong>{item.title||item.document_id}</strong>
          <span>Seit {item.trashed_at} · {item.reason}</span><small className="wp-hint">{item.document_id}</small></div>
        <div className="wp-trash-side">
          <textarea placeholder="Begründung" value={reason[item.document_id]||""} onChange={e=>setReason({...reason,[item.document_id]:e.target.value})}/>
          <div className="wp-actions">
            <button className="approve" disabled={busy===item.document_id} onClick={()=>void restore(item.document_id)}>Wiederherstellen</button>
            {/* Endgueltiges Loeschen ist unumkehrbar und deshalb zweistufig. */}
            {isPortalAdmin&&!item.legal_hold&&(pendingDelete===item.document_id
              ? <><button className="wp-danger" disabled={busy===item.document_id} onClick={()=>void purge(item.document_id)}>Wirklich endgültig löschen</button>
                  <button onClick={()=>setPendingDelete("")}>Abbrechen</button></>
              : <button className="wp-danger" onClick={()=>setPendingDelete(item.document_id)}>Endgültig löschen</button>)}
          </div>
          {pendingDelete===item.document_id&&<p className="wp-hint">Das Original, das Markdown und der Inhalt werden unwiderruflich gelöscht. Nur die Auditdaten bleiben.</p>}
          {item.legal_hold&&<p className="wp-hint">Legal Hold: eine Löschung ist ausgesetzt.</p>}
        </div>
      </div></article>) : <p className="wp-empty-hint">Der Papierkorb ist leer.</p>}</div>
  </section>;
}
