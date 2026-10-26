from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

from .intervention_workflow import CONCLUSIONS, INTERVENTION_KINDS, report_checklists


def intervention_report(intervention):
    """PDF généré depuis la base. Les notes internes ne sont jamais incluses."""
    equipment = intervention.service_request.equipment
    client = equipment.client
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Brand', fontName='Helvetica-Bold', fontSize=24, textColor=colors.HexColor('#1262ff'), leading=28))
    styles.add(ParagraphStyle(name='BodyFR', fontName='Helvetica', fontSize=10, leading=15, spaceAfter=9))
    styles.add(ParagraphStyle(name='SectionFR', fontName='Helvetica-Bold', fontSize=12, leading=18, textColor=colors.HexColor('#17264b'), spaceBefore=13, spaceAfter=7))
    styles.add(ParagraphStyle(name='SmallFR', fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#63708a')))
    document = SimpleDocTemplate(output, pagesize=(210 * mm, 297 * mm), rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=20 * mm, title=f'Rapport {intervention.reference}', author='PowerCare — TVM')
    def p(value, style='BodyFR'):
        return Paragraph(escape(str('Non renseigné' if value is None or value == '' else value)).replace('\n', '<br/>'), styles[style])
    kind = getattr(intervention, 'kind', 'maintenance')
    kind_name = INTERVENTION_KINDS.get(kind, 'Intervention')
    report_title = {
        'exchange': 'Fiche d’échange',
        'commissioning': 'Fiche de mise en service',
        'preventive': 'Fiche de maintenance préventive',
    }.get(kind, 'Rapport de maintenance')
    story = [p('PowerCare', 'Brand'), p('TVM · MAINTENANCE & SERVICE APRÈS-VENTE', 'SmallFR'), Spacer(1, 10 * mm), p(f'{report_title} — {intervention.reference}', 'Title')]
    if intervention.status != 'completed':
        story.extend([p('RAPPORT PROVISOIRE — intervention non terminée', 'SectionFR')])
    date = timezone.localtime(intervention.scheduled_at).strftime('%d/%m/%Y à %H:%M') if intervention.scheduled_at else 'À planifier'
    technician = (intervention.technician.get_full_name() or intervention.technician.username) if intervention.technician else 'Non affecté'
    rows = [
        [p('Client', 'SmallFR'), p(client.name)],
        [p('Type de fiche', 'SmallFR'), p(kind_name)],
        [p('Contact', 'SmallFR'), p(getattr(intervention, 'contact_name', '') or client.contact_name)],
        [p('Téléphone', 'SmallFR'), p(getattr(intervention, 'contact_phone', '') or client.phone)],
        [p('Site', 'SmallFR'), p(getattr(intervention, 'site', '') or equipment.location or f'{client.address} {client.city}'.strip())],
        [p('Équipement', 'SmallFR'), p(f'{equipment.brand} {equipment.model} · {equipment.power_kva} kVA')],
        [p('Ancien numéro de série' if kind == 'exchange' else 'Numéro de série', 'SmallFR'), p(equipment.serial_number)],
        [p('Demande SAV', 'SmallFR'), p(intervention.service_request.reference)],
        [p('Date planifiée', 'SmallFR'), p(date)],
        [p('Technicien', 'SmallFR'), p(technician)],
        [p('État', 'SmallFR'), p(intervention.get_status_display())],
    ]
    if getattr(intervention, 'end_customer', ''):
        rows.insert(2, [p('Client final renseigné', 'SmallFR'), p(intervention.end_customer)])
    if getattr(intervention, 'performed_on', None):
        rows.append([p('Date de réalisation', 'SmallFR'), p(intervention.performed_on.strftime('%d/%m/%Y'))])
    if getattr(intervention, 'cabinet_serial', ''):
        rows.append([p('Série de l’armoire', 'SmallFR'), p(intervention.cabinet_serial)])
    if getattr(intervention, 'battery_count', None) is not None:
        rows.append([p('Nombre de batteries', 'SmallFR'), p(intervention.battery_count)])
    replacement = getattr(intervention, 'replacement_equipment', None)
    if kind == 'exchange':
        rows.append([p('Nouveau numéro de série', 'SmallFR'), p(replacement.serial_number if replacement else 'À renseigner')])
        if replacement is not None:
            rows.append([p('Nouveau matériel', 'SmallFR'), p(f'{replacement.brand} {replacement.model}')])
    contract = getattr(intervention, 'contract', None)
    if contract is not None:
        rows.append([p('Contrat sélectionné', 'SmallFR'), p(contract.number)])
        rows.append([p('Période du contrat', 'SmallFR'), p(f'Du {contract.starts_on:%d/%m/%Y} au {contract.ends_on:%d/%m/%Y}')])
    extension = getattr(intervention, 'extension_warranty', None)
    if extension is not None:
        rows.append([p('Extension / garantie', 'SmallFR'), p(extension.provider or 'Garantie sélectionnée')])
        rows.append([p('Période de l’extension', 'SmallFR'), p(f'Du {extension.starts_on:%d/%m/%Y} au {extension.ends_on:%d/%m/%Y}')])
        rows.append([p('Portée renseignée', 'SmallFR'), p(extension.get_scope_display())])
    info = Table(rows, colWidths=[43 * mm, 128 * mm], hAlign='LEFT')
    info.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f4f7fc')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9), ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
    story.extend([info, Spacer(1, 4 * mm)])
    if getattr(intervention, 'summary', ''):
        story.extend([p('Synthèse', 'SectionFR'), p(intervention.summary)])
    for title, value in [('Signalement', intervention.service_request.description or intervention.service_request.subject), ('Diagnostic', intervention.diagnosis), ('Travaux réalisés', intervention.work_done), ('Recommandations', intervention.recommendations)]:
        story.extend([p(title, 'SectionFR'), p(value)])
    sections = report_checklists(getattr(intervention, 'structured_data', {}))
    if sections:
        story.append(p('Cases renseignées : [X] cochée ; [ ] non cochée. Les contrôles absents du relevé ne sont pas présentés comme réalisés.', 'SmallFR'))
    for section in sections:
        story.append(p(section['title'], 'SectionFR'))
        for check in section['checks']:
            story.append(p(f'{"[X]" if check["checked"] else "[ ]"} {check["label"]}'))
        if section['battery_replaced_count'] is not None:
            story.append(p(f'Batteries remplacées : {section["battery_replaced_count"]}'))
        if section['comment']:
            story.append(p(section['comment']))
    conclusion = getattr(intervention, 'conclusion', '')
    if conclusion in CONCLUSIONS:
        story.extend([p('Conclusion renseignée', 'SectionFR'), p(CONCLUSIONS[conclusion])])
        if conclusion == 'not_applicable_billable':
            story.append(p('Appréciation saisie par l’opérateur ; elle n’a pas été déduite automatiquement des dates de garantie.', 'SmallFR'))
    if getattr(intervention, 'conclusion_notes', ''):
        story.append(p(intervention.conclusion_notes))
    movements = intervention.parts_used.filter(quantity__lt=0).select_related('part')
    if movements.exists():
        story.append(p('Pièces utilisées', 'SectionFR'))
        parts_rows = [[p('Référence', 'SmallFR'), p('Désignation', 'SmallFR'), p('Quantité', 'SmallFR')]]
        for movement in movements:
            parts_rows.append([p(movement.part.sku), p(movement.part.name), p(abs(movement.quantity))])
        parts_table = Table(parts_rows, colWidths=[38 * mm, 112 * mm, 21 * mm], repeatRows=1)
        parts_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eaf1ff')), ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#dce5f3')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 5)]))
        story.append(parts_table)
    story.extend([Spacer(1, 8 * mm), p('Document de suivi opérationnel. Ce document ne constitue ni une facture, ni une signature électronique, ni une attestation de conformité.', 'SmallFR')])
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#63708a'))
        canvas.drawString(18 * mm, 12 * mm, f'PowerCare / TVM — {intervention.reference}')
        canvas.drawRightString(192 * mm, 12 * mm, f'Page {doc.page}')
        canvas.restoreState()
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
