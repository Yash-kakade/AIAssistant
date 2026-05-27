"""Generate machine operation manuals as PDFs for the RAG pipeline."""
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

MANUALS_DIR = Path(__file__).resolve().parent.parent / "app" / "manuals"

MANUALS = {
    "CNC_Alpha-1_Manual.pdf": {
        "title": "CNC Alpha-1 — Operation & Maintenance Manual",
        "machine": "CNC Alpha-1",
        "sections": [
            ("Overview", "The CNC Alpha-1 is a 3-axis vertical machining center for precision milling. Max spindle speed: 12000 RPM. Work envelope: 500 x 400 x 300 mm."),
            ("Safety", "Always wear safety glasses. Lock out/tag out before maintenance. Never open the enclosure while spindle is running. Emergency stop (E-STOP) is located on the front panel."),
            ("Startup Procedure", "1. Verify coolant level. 2. Power on main breaker. 3. Home all axes (G28). 4. Load program and verify tool offsets. 5. Run dry cycle at reduced feed."),
            ("Maintenance Schedule", "Daily: clean chips, check coolant. Weekly: lubricate ways, inspect tool holder. Monthly: spindle runout check, backup parameters. Quarterly: ball screw inspection."),
            ("Troubleshooting", "Alarm 101 (door open): close safety door. Alarm 205 (tool break): replace tool, recalibrate length offset. Poor surface finish: reduce feed, check tool wear."),
            ("Specifications", "Power: 15 kW. Tool capacity: 24 stations. Control: Fanuc-compatible. Coolant: water-soluble, 6-8% concentration."),
        ],
    },
    "CNC_Bravo-2_Manual.pdf": {
        "title": "CNC Bravo-2 — Operation & Maintenance Manual",
        "machine": "CNC Bravo-2",
        "sections": [
            ("Overview", "CNC Bravo-2 is a horizontal machining center for batch production. Currently under scheduled maintenance for spindle bearing replacement."),
            ("Safety", "Two-hand start required for automatic cycle. Interlock doors must be closed. Hearing protection recommended above 85 dB."),
            ("Maintenance Mode", "Machine is in MAINTENANCE status. Do not attempt production runs until maintenance lead clears the unit."),
            ("Spindle Bearing Replacement", "Order part SKF-7014. Torque spindle nut to 180 Nm. Run break-in program at 50% RPM for 30 minutes."),
            ("Calibration", "After bearing replacement, perform spindle warm-up (15 min), then tool length probe calibration on all active tools."),
        ],
    },
    "VMC_Pro-5_Manual.pdf": {
        "title": "VMC Pro-5 — Operation & Maintenance Manual",
        "machine": "VMC Pro-5",
        "sections": [
            ("Overview", "VMC Pro-5 vertical machining center. High-speed machining up to 18000 RPM. Ideal for aluminum and steel components."),
            ("Safety", "Chip conveyor must be clear before start. Fire suppression optional module installed in Zone B."),
            ("Coolant System", "Maintain 7% coolant concentration. Replace filter every 500 operating hours. Tank capacity: 200 liters."),
            ("Tool Change", "Automatic tool changer (ATC) cycle time: 2.1 seconds. Max tool diameter: 80 mm, length 300 mm."),
            ("Efficiency Tips", "Use high-pressure coolant for deep cavity work. Optimal efficiency reported at 88% when running 2-shift operation."),
        ],
    },
    "VMC_Lite-1_Manual.pdf": {
        "title": "VMC Lite-1 — Operation & Maintenance Manual",
        "machine": "VMC Lite-1",
        "sections": [
            ("Overview", "Compact VMC for prototyping and small batch runs. Status IDLE when not in production schedule."),
            ("Safety", "Single-operator station. Maximum workpiece weight: 50 kg."),
            ("Startup", "Warm spindle for 5 minutes before full-speed cutting. Verify workholding before each job."),
            ("Idle Mode", "When idle, run weekly spindle rotation (10 min at 1000 RPM) to prevent bearing brinelling."),
        ],
    },
    "Lathe_X-90_Manual.pdf": {
        "title": "Lathe X-90 — Operation & Maintenance Manual",
        "machine": "Lathe X-90",
        "sections": [
            ("Overview", "CNC lathe with 2-axis control plus live tooling. Chuck size: 200 mm. Max turning diameter: 320 mm."),
            ("Safety", "Never reach into chuck while powered. Use chuck guard at all times."),
            ("Tool Post", "Corrective maintenance note: tool post alignment should be checked after any collision. Run test bar at 500 RPM."),
            ("Maintenance", "Grease tailstock every 250 hours. Check belt tension monthly. Current efficiency target: 75%+."),
            ("Programming", "Use G96 constant surface speed for finishing passes. Recommended insert grade: CNMG 120408."),
        ],
    },
}


def build_pdf(filename: str, data: dict) -> None:
    path = MANUALS_DIR / filename
    MANUALS_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=16, spaceAfter=12)
    heading_style = ParagraphStyle("Heading", parent=styles["Heading2"], fontSize=12, spaceAfter=6)
    body_style = styles["BodyText"]

    story = [Paragraph(data["title"], title_style), Spacer(1, 12)]
    for heading, body in data["sections"]:
        story.append(Paragraph(heading, heading_style))
        story.append(Paragraph(body, body_style))
        story.append(Spacer(1, 10))

    story.append(Paragraph("Emergency Contacts", heading_style))
    story.append(ListFlowable([
        ListItem(Paragraph("Maintenance Lead: ext. 204", body_style)),
        ListItem(Paragraph("Plant Manager: ext. 101", body_style)),
        ListItem(Paragraph("Safety Officer: ext. 999", body_style)),
    ]))
    doc.build(story)
    print(f"Created {path}")


if __name__ == "__main__":
    for fname, content in MANUALS.items():
        build_pdf(fname, content)
    print(f"Done. {len(MANUALS)} manuals in {MANUALS_DIR}")
