"""Deterministic interactive PDF forms for KAHLE governance."""
from __future__ import annotations
import io
import re
from datetime import datetime
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
BLUE,LIGHT_BLUE=HexColor("#0072B8"),HexColor("#EAF4FA")
INK,MUTED=HexColor("#17212B"),HexColor("#5E6B76")
BORDER,ROW=HexColor("#B8C6D1"),HexColor("#F4F7F9")
class Form:
 def __init__(self,stamp):
  self.out=io.BytesIO(); self.c=canvas.Canvas(self.out,pagesize=A4,pageCompression=1); self.w,self.h=A4; self.l,self.r=48,self.w-48; self.stamp=stamp; self.page=0; self.new_page()
 @property
 def form(self): return self.c.acroForm
 def footer(self):
  c=self.c; c.setFillColor(INK); c.rect(0,self.h-42,self.w,42,fill=1,stroke=0); c.setFillColor(white); c.setFont("Helvetica-Bold",12); c.drawString(self.l,self.h-27,"KAHLE / KI-GOVERNANCE"); c.setFillColor(BLUE); c.rect(self.w-64,self.h-42,16,42,fill=1,stroke=0); c.setStrokeColor(BORDER); c.line(self.l,32,self.r,32); c.setFillColor(MUTED); c.setFont("Helvetica",7.5); c.drawString(self.l,19,"Autohaus KAHLE GmbH & Co. KG · Am Leineufer 49 · 30419 Hannover"); c.drawRightString(self.r,19,f"Seite {self.page}")
 def new_page(self):
  if self.page: self.footer(); self.c.showPage()
  self.page+=1; self.y=self.h-68
 def ensure(self,n):
  if self.y-n<48: self.new_page()
 def title(self):
  c=self.c; c.setFillColor(BLUE); c.setFont("Helvetica-Bold",8); c.drawString(self.l,self.y,"KAHLE INTERN · AUSFÜLLBARE PDF-VORLAGE"); self.y-=28; c.setFillColor(INK); c.setFont("Helvetica-Bold",23); c.drawString(self.l,self.y,"Antrag auf Freigabe einer KI-Nutzung"); self.y-=22; c.setFillColor(LIGHT_BLUE); c.roundRect(self.l,self.y-53,self.r-self.l,53,4,fill=1,stroke=0); c.setFillColor(INK); c.setFont("Helvetica",8.5)
  for i,line in enumerate(["Dieses interaktive Formular dokumentiert Prüfung und gemeinsame Entscheidung über eine","genehmigungspflichtige KI-Nutzung. Erforderliche Fachprüfungen und Mitzeichnungen bleiben bestehen.",f"Erstellt mit KAHLE-Vinci · {self.stamp}"]): c.drawString(self.l+12,self.y-15-i*13,line)
  self.y-=68
 def heading(self,text):
  self.ensure(33); c=self.c; c.setFillColor(BLUE); c.rect(self.l,self.y-23,self.r-self.l,23,fill=1,stroke=0); c.setFillColor(white); c.setFont("Helvetica-Bold",10); c.drawString(self.l+9,self.y-15,text); self.y-=30
 def text(self,label,name,multi=False):
  height=58 if multi else 35; self.ensure(height); c=self.c; c.setFillColor(ROW); c.rect(self.l,self.y-height+3,self.r-self.l,height-3,fill=1,stroke=0); c.setFillColor(INK); c.setFont("Helvetica-Bold",8); c.drawString(self.l+7,self.y-12,label); self.form.textfield(name=name,tooltip=label,x=self.l+180,y=self.y-height+9,width=self.r-self.l-188,height=height-24,borderColor=BORDER,fillColor=white,textColor=INK,borderWidth=.8,forceBorder=True,fontName="Helvetica",fontSize=8.5,fieldFlags="multiline" if multi else ""); self.y-=height
 def choice(self,label,name,options):
  self.ensure(36); c=self.c; c.setFillColor(INK); c.setFont("Helvetica-Bold",8); c.drawString(self.l+7,self.y-13,label); values=["Bitte auswählen",*options]; self.form.choice(name=name,tooltip=label,value=values[0],options=values,x=self.l+180,y=self.y-28,width=self.r-self.l-188,height=20,borderColor=BORDER,fillColor=white,textColor=INK,borderWidth=.8,forceBorder=True,fontName="Helvetica",fontSize=8.5,fieldFlags="combo"); self.y-=36
 def check(self,label,name):
  self.ensure(24); self.form.checkbox(name=name,tooltip=label,x=self.l+7,y=self.y-17,size=11,buttonStyle="check",borderColor=BORDER,fillColor=white,textColor=BLUE,checked=False,forceBorder=True); self.c.setFillColor(INK); self.c.setFont("Helvetica",8.5); self.c.drawString(self.l+25,self.y-14,label); self.y-=24
 def note(self,text):
  self.ensure(42); self.c.setFillColor(LIGHT_BLUE); self.c.roundRect(self.l,self.y-34,self.r-self.l,34,3,fill=1,stroke=0); self.c.setFillColor(INK); self.c.setFont("Helvetica",8); self.c.drawString(self.l+9,self.y-14,text[:105]); self.c.drawString(self.l+9,self.y-26,text[105:210]); self.y-=43
 def finish(self): self.footer(); self.c.save(); return self.out.getvalue()
def fields(f,items,multi=()):
 for label,name in items: f.text(label,name,name in multi)
def render_ki_permission_form_pdf(generated_at=None):
 f=Form(generated_at or datetime.now().strftime("%d.%m.%Y %H:%M")); f.title()
 f.heading("1. Vorgang und Antragsteller"); fields(f,[("Vorgangsnummer","case_id"),("Antragsdatum","application_date"),("Name","applicant_name"),("Abteilung / Funktion","applicant_department"),("Standort","applicant_location"),("E-Mail / Telefon","applicant_contact"),("Führungskraft","manager_name")])
 f.heading("2. Beantragte KI-Nutzung"); fields(f,[("KI-System / Produkt","ai_system_name"),("Anbieter / Version / URL","ai_vendor_version"),("Einsatzzweck und erwarteter Nutzen","purpose"),("Nutzerkreis","user_group")],{"purpose"}); f.choice("Einsatzhäufigkeit","frequency",["Einmalig","Gelegentlich","Regelmäßig","Dauerhaft"]); fields(f,[("Geplanter Start","planned_start"),("Beantragte Laufzeit","requested_duration")])
 f.heading("3. Grund der Genehmigungspflicht")
 for a,b in [("KI-System steht nicht auf der KAHLE-Whitelist","reason_not_whitelisted"),("Nutzung eines GPAI-/Consumer-Tools","reason_gpai"),("Mögliche Hochrisiko-KI-Anwendung","reason_high_risk"),("HR-Entscheidung, Leistungs- oder Verhaltenskontrolle","reason_hr"),("Scoring oder Profiling von Kunden oder Beschäftigten","reason_scoring"),("Verarbeitung vertraulicher oder personenbezogener Daten","reason_sensitive_data"),("Sonstiger genehmigungspflichtiger Einsatz","reason_other")]: f.check(a,b)
 f.text("Erläuterung","approval_reason_details",True)
 f.heading("4. Daten, Betroffene und technische Nutzung"); fields(f,[("Verarbeitete Datenarten","data_categories"),("Betroffene Personengruppen","affected_persons"),("Eingaben in das KI-System","ai_inputs"),("Erzeugte Ergebnisse und Verwendung","ai_outputs"),("Speicherort / Datenübertragung","storage_transfer"),("Menschliche Prüfung der Ergebnisse","human_oversight")],{"data_categories","ai_inputs","ai_outputs","human_oversight"})
 f.heading("5. Fachliche Prüfungen"); f.choice("Risikoeinstufung","risk_level",["Niedrig","Begrenzt","Hoch / vertiefte Prüfung","Unklar"]); status=["Nicht erforderlich","Erforderlich","Abgeschlossen","Offen"]
 for a,b in [("Datenschutzprüfung","privacy_review"),("Datenschutz-Folgenabschätzung (DSFA)","dsfa_status"),("IT-Sicherheitsprüfung","security_review")]: f.choice(a,b,status)
 f.choice("Betriebsrat / Personalvertretung","works_council_review",["Nicht betroffen","Beteiligung erforderlich","Beteiligt","Offen"]); f.text("Prüfvermerke / Anlagen","review_notes",True)
 f.heading("6. Erklärung des Antragstellers")
 for a,b in [("Ich verwende die KI ausschließlich für den beschriebenen Zweck.","declaration_purpose"),("Ich lade nur zulässige Daten und Informationen hoch.","declaration_data"),("Ich prüfe KI-Ergebnisse fachlich und verantworte ihre Nutzung.","declaration_review"),("Ich beachte Auflagen, Befristungen, Dokumentations- und Meldepflichten.","declaration_conditions"),("Ich melde Vorfälle und wesentliche Änderungen unverzüglich.","declaration_incidents")]: f.check(a,b)
 fields(f,[("Name Antragsteller","applicant_signature_name"),("Datum","applicant_signature_date"),("Unterschrift / digitale Bestätigung","applicant_signature")])
 f.heading("7. Gemeinsame Entscheidung")
 for a,b in [("Freigegeben","decision_approved"),("Freigegeben mit Auflagen","decision_conditional"),("Zurückgestellt – weitere Prüfung erforderlich","decision_deferred"),("Abgelehnt","decision_rejected")]: f.check(a,b)
 fields(f,[("Gültig ab","valid_from"),("Gültig bis","valid_until"),("Auflagen und Nutzungsgrenzen","conditions"),("Überprüfung / Wiedervorlage","review_date"),("Begründung bei Ablehnung","rejection_reason")],{"conditions","rejection_reason"})
 f.heading("8. Fachliche Mitzeichnungen (nur wenn erforderlich)"); fields(f,[("Fachbereich / Führungskraft – Name","business_owner_name"),("Datum / Unterschrift","business_owner_approval"),("Datenschutzbeauftragte / DSK – Name","privacy_approver_name"),("Datum / Unterschrift","privacy_approval"),("IT-Sicherheit – Name","security_approver_name"),("Datum / Unterschrift","security_approval"),("Betriebsrat / Personalvertretung – Name","works_council_approver_name"),("Datum / Unterschrift","works_council_approval")])
 f.heading("9. Verbindliche Endfreigabe"); f.note("Die Nutzung ist erst freigegeben, wenn KI-Beauftragter und Geschäftsführung gemeinsam bestätigt haben.")
 fields(f,[("KI-Beauftragter – Name","ai_officer_name"),("KI-Beauftragter – Datum","ai_officer_date"),("KI-Beauftragter – Unterschrift","ai_officer_signature"),("Geschäftsführung – Name","management_name"),("Geschäftsführung – Datum","management_date"),("Geschäftsführung – Unterschrift","management_signature")]); f.note("Wesentliche Änderungen an Zweck, System, Anbieter, Datenarten oder Nutzerkreis erfordern eine erneute Prüfung."); return f.finish()


def render_ki_policy_quiz_pdf(generated_at=None):
    """Create a genuine AcroForm knowledge check for KAHLE KI policy v1.4."""
    try:
        from .fillable_forms import KI_POLICY_QUIZ_MC
    except ImportError:
        from fillable_forms import KI_POLICY_QUIZ_MC
    f=Form(generated_at or datetime.now().strftime("%d.%m.%Y %H:%M"))
    f.c.setFillColor(BLUE); f.c.setFont("Helvetica-Bold",8); f.c.drawString(f.l,f.y,"KAHLE INTERN · SCHULUNG & COMPLIANCE")
    f.y-=28; f.c.setFillColor(INK); f.c.setFont("Helvetica-Bold",23); f.c.drawString(f.l,f.y,"Wissenstest zur KAHLE-KI-Richtlinie")
    f.y-=20; f.note("Interaktiver Fragebogen zur KI-Richtlinie v1.4. Bitte selbstständig bearbeiten; Auswertung durch die Schulungsleitung.")
    f.heading("1. Teilnehmer und Durchführung")
    fields(f,[("Name","quiz_participant_name"),("Abteilung / Funktion","quiz_department"),("Standort","quiz_location"),("Datum","quiz_date"),("Schulung / Anlass","quiz_training")])
    f.heading("2. Multiple-Choice-Fragen")
    for index,(question,options) in enumerate(KI_POLICY_QUIZ_MC,1):
        f.ensure(66); f.c.setFillColor(INK); f.c.setFont("Helvetica-Bold",8.5)
        words=question.split(); line=''; lines=[]
        for word in words:
            candidate=(line+' '+word).strip()
            if f.c.stringWidth(candidate,"Helvetica-Bold",8.5)>f.r-f.l-14: lines.append(line); line=word
            else: line=candidate
        if line: lines.append(line)
        for line in lines: f.c.drawString(f.l+7,f.y-12,line); f.y-=11
        f.choice("Antwort",f"quiz_q{index}",options); f.y-=4
    f.heading("3. Praxis- und Transferfragen")
    scenarios=[
        "Ein Kollege möchte Kundendaten in ein öffentliches, nicht freigegebenes KI-Tool laden. Wie reagieren Sie und warum?",
        "Ein KI-System liefert eine Empfehlung, die eine Personalentscheidung beeinflussen könnte. Welche Schritte sind erforderlich?",
        "Nennen Sie einen meldepflichtigen KI-Vorfall und beschreiben Sie den vorgesehenen Meldeweg.",
    ]
    for offset,question in enumerate(scenarios,len(KI_POLICY_QUIZ_MC)+1):
        f.ensure(88); f.c.setFillColor(INK); f.c.setFont("Helvetica-Bold",8.5); f.c.drawString(f.l+7,f.y-12,f"{offset}. {question[:92]}")
        if len(question)>92: f.c.drawString(f.l+7,f.y-23,question[92:184]); f.y-=11
        f.y-=16; f.text("Antwort / Begründung",f"quiz_q{offset}",True)
    f.heading("4. Bestätigung des Teilnehmenden")
    f.check("Ich habe den Fragebogen selbstständig und nach bestem Wissen beantwortet.","quiz_declaration")
    f.check("Mir ist bekannt, dass KI-Ergebnisse geprüft und Vorfälle gemeldet werden müssen.","quiz_acknowledgement")
    fields(f,[("Name","quiz_signature_name"),("Datum","quiz_signature_date"),("Unterschrift / digitale Bestätigung","quiz_signature")])
    f.heading("5. Auswertung durch die Schulungsleitung")
    fields(f,[("Erreichte Punkte","quiz_score"),("Maximalpunkte","quiz_max_score")])
    f.choice("Ergebnis","quiz_result",["Bestanden","Nachschulung erforderlich","Noch nicht bewertet"])
    f.text("Feedback / Lernfelder","quiz_feedback",True)
    fields(f,[("Bewertet von","quiz_reviewer"),("Bewertungsdatum","quiz_review_date")])
    f.note("Bewertungsvorschlag: 1 Punkt je Multiple Choice, je 2 Punkte für die drei Praxisfragen; maximal 15 Punkte.")
    return f.finish()

def _pdf_safe_text(value):
    """Keep only characters supported by ReportLab's built-in WinAnsi fonts."""
    cleaned=[]
    for char in str(value or ""):
        if char in "\n\t": cleaned.append(" "); continue
        try:
            char.encode("cp1252"); cleaned.append(char)
        except UnicodeEncodeError:
            cleaned.append(" ")
    return re.sub(r"\s+"," ","".join(cleaned)).strip()


def _wrapped_lines(form, text, font="Helvetica-Bold", size=8.5, width=None):
    width = width or (form.r-form.l-14); words=_pdf_safe_text(text).split(); lines=[]; line=""
    for word in words:
        candidate=(line+" "+word).strip()
        if form.c.stringWidth(candidate,font,size)>width and line: lines.append(line); line=word
        else: line=candidate
    if line: lines.append(line)
    return lines[:8]


def _draw_wrapped(form, text, font="Helvetica-Bold", size=8.5, width=None, leading=11):
    lines=_wrapped_lines(form,text,font,size,width)
    for value in lines:
        form.ensure(leading+2); form.c.setFillColor(INK); form.c.setFont(font,size); form.c.drawString(form.l+7,form.y-10,value); form.y-=leading


def render_dynamic_form_pdf(schema, generated_at=None):
    """Render a validated, scenario-independent interactive AcroForm schema."""
    f=Form(generated_at or datetime.now().strftime("%d.%m.%Y %H:%M"))
    title=_pdf_safe_text(str(schema.get("title") or "Interaktives KAHLE-Formular")[:120])
    f.c.setFillColor(BLUE); f.c.setFont("Helvetica-Bold",8); f.c.drawString(f.l,f.y,_pdf_safe_text(str(schema.get("kicker") or "KAHLE INTERN · INTERAKTIVES FORMULAR")[:95]))
    f.y-=28; f.c.setFillColor(INK); f.c.setFont("Helvetica-Bold",21)
    _draw_wrapped(f,title,font="Helvetica-Bold",size=21,width=f.r-f.l,leading=24)
    f.y-=4; f.note(_pdf_safe_text(str(schema.get("instructions") or "Bitte füllen Sie alle zutreffenden Felder vollständig aus.")[:210]))
    identity=schema.get("identity_fields") or []
    if identity:
        f.heading("Allgemeine Angaben")
        for index,item in enumerate(identity[:10],1):
            kind=str(item.get("type") or "text").lower(); label=_pdf_safe_text(str(item.get("label") or f"Angabe {index}")[:100]); name=str(item.get("id") or f"identity_{index}")[:48]
            if kind=="dropdown": f.choice(label,name,[str(v)[:100] for v in (item.get("options") or [])[:12]])
            elif kind=="checkbox": f.check(label,name)
            else: f.text(label,name,kind=="multiline")
    for section_no,section in enumerate((schema.get("sections") or [])[:12],1):
        f.heading(_pdf_safe_text(f"{section_no}. {str(section.get('title') or 'Abschnitt')[:95]}"))
        desc=_pdf_safe_text(str(section.get("description") or "").strip())
        if desc: _draw_wrapped(f,desc,font="Helvetica",size=8,width=f.r-f.l-14,leading=10); f.y-=4
        for item_no,item in enumerate((section.get("items") or [])[:16],1):
            kind=str(item.get("type") or "text").lower(); label=_pdf_safe_text(str(item.get("label") or f"Feld {item_no}")[:300]); name=str(item.get("id") or f"section_{section_no}_{item_no}")[:48]
            if kind=="checkbox":
                f.ensure(30); f.y-=6; f.check(label,name)
            elif kind=="dropdown":
                label_lines=_wrapped_lines(f,label,font="Helvetica-Bold",size=8.5,width=f.r-f.l-14)
                f.ensure(6+len(label_lines)*10+56); f.y-=6
                _draw_wrapped(f,label,font="Helvetica-Bold",size=8.5,width=f.r-f.l-14,leading=10)
                # The following widget paints its background up to y+3. Keep
                # that background clear of the final question baseline.
                f.y-=8
                f.choice("Antwort",name,[_pdf_safe_text(str(v)[:120]) for v in (item.get("options") or [])[:12]])
            else:
                if len(label)>85:
                    label_lines=_wrapped_lines(f,label,font="Helvetica-Bold",size=8.5,width=f.r-f.l-14)
                    f.ensure(6+len(label_lines)*10+14+(62 if kind=="multiline" else 39)); f.y-=6
                    _draw_wrapped(f,label,font="Helvetica-Bold",size=8.5,width=f.r-f.l-14,leading=10)
                    # Form.text paints the answer-row background three points
                    # above the cursor. This gap prevents it from covering text.
                    f.y-=14; label="Antwort"
                else:
                    f.ensure(6+(62 if kind=="multiline" else 39)); f.y-=6
                f.text(label,name,kind=="multiline")
    declarations=[_pdf_safe_text(str(v)[:300]) for v in (schema.get("declarations") or [])[:8] if str(v).strip()]
    if declarations:
        f.heading("Bestätigung")
        for i,label in enumerate(declarations,1):
            if len(label)>95: _draw_wrapped(f,label,font="Helvetica",size=8,width=f.r-f.l-35,leading=10); f.check("Bestätigt",f"declaration_{i}")
            else: f.check(label,f"declaration_{i}")
    signature=schema.get("signature_fields") or []
    if signature:
        for i,item in enumerate(signature[:8],1): f.text(_pdf_safe_text(str(item.get("label") or f"Bestätigung {i}")[:100]),str(item.get("id") or f"signature_{i}")[:48],str(item.get("type") or "text")=="multiline")
    return f.finish()