from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "deliverables" / "knowledge" / "Werbewiderspruch_Kontaktsperre_Vaudis_DSE_v2.0.pdf"


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D7DEE5"))
    canvas.line(20 * mm, 16 * mm, 190 * mm, 16 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#536271"))
    canvas.drawString(20 * mm, 10 * mm, "KAHLE | Interne Arbeitsanweisung | Version 2.0")
    canvas.drawRightString(190 * mm, 10 * mm, f"Seite {doc.page}")
    canvas.restoreState()


def bullet(text, styles):
    return Paragraph(f"• {text}", styles["BulletKahle"])


def numbered(number, text, styles):
    return Paragraph(f"<b>{number}.</b> {text}", styles["BodyKahle"])


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="TitleKahle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=21, leading=25, textColor=colors.HexColor("#0B213B"),
        alignment=TA_LEFT, spaceAfter=4 * mm,
    ))
    styles.add(ParagraphStyle(
        name="MetaKahle", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=9, leading=12, textColor=colors.HexColor("#0072BC"),
        spaceAfter=7 * mm,
    ))
    styles.add(ParagraphStyle(
        name="HeadingKahle", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=13, leading=16, textColor=colors.HexColor("#0B213B"),
        spaceBefore=5 * mm, spaceAfter=2 * mm,
    ))
    styles.add(ParagraphStyle(
        name="BodyKahle", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=10.2, leading=14.5, textColor=colors.HexColor("#202A33"),
        spaceAfter=2.2 * mm,
    ))
    styles.add(ParagraphStyle(
        name="BulletKahle", parent=styles["BodyKahle"], leftIndent=5 * mm,
        firstLineIndent=-3.5 * mm, spaceAfter=1.2 * mm,
    ))
    styles.add(ParagraphStyle(
        name="NoticeKahle", parent=styles["BodyKahle"], fontName="Helvetica-Bold",
        borderColor=colors.HexColor("#0072BC"), borderWidth=1,
        borderPadding=4 * mm, backColor=colors.HexColor("#EEF7FC"),
        spaceBefore=2 * mm, spaceAfter=4 * mm,
    ))

    doc = BaseDocTemplate(
        str(OUTPUT), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title="Werbewiderspruch: Werbung und Befragungen in Vaudis/DSE sperren",
        author="KAHLE Gruppe",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates(PageTemplate(id="kahle", frames=[frame], onPage=footer))

    story = [
        Paragraph("Werbewiderspruch: Werbung und Befragungen in Vaudis/DSE sperren", styles["TitleKahle"]),
        Paragraph("VERSION 2.0 &nbsp;|&nbsp; STAND 19.08.2026", styles["MetaKahle"]),
        Paragraph("1. Zweck und klare Abgrenzung", styles["HeadingKahle"]),
        Paragraph(
            "Diese Arbeitsanweisung gilt ausschließlich, wenn ein Kunde keine Werbung oder "
            "automatisierten Zufriedenheitsbefragungen mehr erhalten soll. Dafür werden die "
            "Kontaktfreigaben in den DSE-Einstellungen angepasst.", styles["BodyKahle"],
        ),
        Spacer(1, 2 * mm),
        Paragraph(
            "Diese Arbeitsanweisung beschreibt ausdrücklich <b>keine allgemeine Kundensperre</b>, "
            "keine Verkaufs-, Auftrags- oder Finanzsperre und keine Sperrung eines Benutzerkontos.",
            styles["NoticeKahle"],
        ),
        Paragraph(
            "Wenn eine allgemeine Kundensperre benötigt wird, wende dich mit "
            "<b>Kundennummer</b> und <b>Grund der gewünschten Sperre</b> an "
            "<link href='mailto:datenschutz@kahle.de' color='#0072BC'>datenschutz@kahle.de</link>.",
            styles["BodyKahle"],
        ),
        Paragraph("2. Voraussetzungen für einen Werbewiderspruch", styles["HeadingKahle"]),
        Paragraph("Die Kontaktsperre wird insbesondere gesetzt, wenn einer der folgenden Fälle vorliegt:", styles["BodyKahle"]),
        bullet("Der Kunde widerspricht Werbung oder weiteren Kontaktaufnahmen.", styles),
        bullet("Der Kunde soll aufgrund einer Beschwerde oder Unzufriedenheit keine automatisierte Zufriedenheitsbefragung erhalten.", styles),
        bullet("Eine problematische oder eskalierte Auftragsabwicklung soll nicht automatisch nachbefragt werden.", styles),
        Paragraph(
            "<b>Wichtig:</b> Die Anpassung muss vor oder spätestens am Tag der Auftragsfaktura "
            "erfolgen. Erfolgt sie zu spät, kann eine automatisierte Kundenbefragung dennoch ausgelöst werden.",
            styles["BodyKahle"],
        ),
        Paragraph("3. Zuständigkeiten", styles["HeadingKahle"]),
        bullet("Die Meldung erfolgt im Teams-Kanal <b>„HAN – LÖSCHEN &amp; SPERREN“</b> unter Angabe der Kundennummer, zum Beispiel: „Kunde 123456 – bitte Werbung und Befragungen sperren.“", styles),
        bullet("Die Anpassung wird durch die zuständigen Ansprechpartner in der Serviceassistenz durchgeführt.", styles),
        PageBreak(),
        Paragraph("4. Werbung und Befragungen sperren", styles["HeadingKahle"]),
        numbered(1, "Den Kunden in Vaudis anhand der Kundennummer aufrufen.", styles),
        numbered(2, "In den DSE-Einstellungen die Kontaktfreigaben des Kunden gemäß seinem Werbewiderspruch deaktivieren. Dazu werden die jeweils betroffenen Haken entfernt.", styles),
        numbered(3, "Den Kunden in die Sperrliste eintragen. Ablageort: <b>Allgemein &gt; Serviceassistenz &gt; Sperrliste</b>.", styles),
        numbered(4, "Die entfernten Haken genau dokumentieren, damit die ursprünglichen Einstellungen später korrekt wiederhergestellt werden können.", styles),
        Spacer(1, 2 * mm),
        Paragraph(
            "<b>Wichtig:</b> Der Kunde wird durch diesen Ablauf nicht allgemein in Vaudis gesperrt. "
            "Es werden ausschließlich die Kontaktfreigaben für Werbung und Befragungen angepasst.",
            styles["NoticeKahle"],
        ),
        KeepTogether([
            Paragraph("5. Kontaktfreigaben wiederherstellen", styles["HeadingKahle"]),
            Paragraph("Nach einer Sperrdauer von 14 Tagen erfolgt eine automatische Erinnerung per E-Mail an hannover@kahle.de.", styles["BodyKahle"]),
        ]),
        numbered(1, "Den in der E-Mail enthaltenen Link „HIER“ zur Übersicht öffnen.", styles),
        numbered(2, "Den Kunden in Vaudis aufrufen.", styles),
        numbered(3, "Die ursprünglichen DSE-Einstellungen anhand der dokumentierten Tabelle wiederherstellen.", styles),
        numbered(4, "Das Datum der Wiederherstellung beziehungsweise Entsperrung eintragen.", styles),
        Spacer(1, 3 * mm),
        Paragraph("Bei Rückfragen oder Unklarheiten steht Jan Oltmanns zur Verfügung.", styles["BodyKahle"]),
    ]
    doc.build(story)


if __name__ == "__main__":
    build()
