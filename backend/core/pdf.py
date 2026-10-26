"""Database-generated TVM forms; never embed uploaded forms or private notes."""
from io import BytesIO
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from django.db.models import Q
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from .intervention_workflow import CHECKLISTS, CONCLUSIONS, INTERVENTION_KINDS, report_checklists

BLUE = colors.HexColor('#117cbb')
INK = colors.HexColor('#182c40')
PALE = colors.HexColor('#eef5fa')
WIDTH = 186 * mm


def _styles():
    if 'TVM' not in pdfmetrics.getRegisteredFontNames():
        folder = Path(reportlab.__file__).parent / 'fonts'
        pdfmetrics.registerFont(TTFont('TVM', str(folder / 'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('TVM-Bold', str(folder / 'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('TVM', normal='TVM', bold='TVM-Bold', italic='TVM', boldItalic='TVM-Bold')
    return {
        'body': ParagraphStyle('TVMBody', fontName='TVM', fontSize=8, leading=10.2, textColor=INK, splitLongWords=True),
        'small': ParagraphStyle('TVMSmall', fontName='TVM', fontSize=7, leading=9, textColor=colors.HexColor('#465461')),
        'white': ParagraphStyle('TVMWhite', fontName='TVM', fontSize=8, leading=10, textColor=colors.white),
        'head': ParagraphStyle('TVMHead', fontName='TVM-Bold', fontSize=15, leading=19, alignment=1, textColor=colors.black),
        'section': ParagraphStyle('TVMSection', fontName='TVM-Bold', fontSize=8, leading=10, alignment=1, textColor=colors.white),
        'danger': ParagraphStyle('TVMDanger', fontName='TVM-Bold', fontSize=8, leading=10.2, textColor=colors.HexColor('#ad172e')),
    }


def _p(value, styles, style='body'):
    text = 'Non renseigné' if value is None or value == '' else str(value)
    return Paragraph(escape(text).replace('\n', '<br/>'), styles[style])


def _date(value, with_time=False):
    if not value:
        return 'Non renseignée'
    if hasattr(value, 'hour') and timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime('%d/%m/%Y à %H:%M' if with_time else '%d/%m/%Y')


def _table(rows, widths, grid=True, padding=3, repeat=0):
    table = LongTable(rows, colWidths=widths, repeatRows=repeat, splitByRow=1, splitInRow=1, hAlign='LEFT')
    rules = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), padding),
             ('RIGHTPADDING', (0, 0), (-1, -1), padding), ('TOPPADDING', (0, 0), (-1, -1), padding),
             ('BOTTOMPADDING', (0, 0), (-1, -1), padding)]
    if grid:
        rules.append(('GRID', (0, 0), (-1, -1), .45, colors.HexColor('#465461')))
    table.setStyle(TableStyle(rules))
    return table


def _bar(title, styles, width=WIDTH):
    table = _table([[_p(title, styles, 'section')]], [width], grid=False, padding=4)
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), BLUE)]))
    return table


def _fields(rows, styles, widths=None, highlight=()):
    table = _table([[_p(label, styles, 'white'), _p(value, styles, 'danger' if label in highlight else 'body')] for label, value in rows], widths or [38 * mm, WIDTH - 38 * mm])
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, -1), BLUE)]))
    return table


class TVMMark(Flowable):
    """Original typographic mark; no private logo or company footer copied."""
    def __init__(self):
        super().__init__()
        self.width, self.height = 130, 45

    def draw(self):
        canvas = self.canv
        canvas.setStrokeColor(BLUE)
        canvas.rect(1, 4, 13, 36)
        canvas.line(5, 4, 5, 40)
        canvas.rect(8, 27, 4, 4)
        canvas.rect(8, 9, 4, 12)
        canvas.setFillColor(INK)
        canvas.setFont('TVM-Bold', 28)
        canvas.drawString(21, 15, 'TVM')
        canvas.setFont('TVM', 5.5)
        canvas.drawString(21, 5, 'MAINTENANCE & SERVICE SAV')


def _document(output, title, reference):
    document = SimpleDocTemplate(output, pagesize=(210 * mm, 297 * mm), leftMargin=12 * mm, rightMargin=12 * mm,
                                 topMargin=9 * mm, bottomMargin=15 * mm, title=f'{title} {reference}', author='TVM / PowerCare')
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(BLUE)
        canvas.line(12 * mm, 12 * mm, 198 * mm, 12 * mm)
        canvas.setFillColor(INK)
        canvas.setFont('TVM', 6.5)
        canvas.drawString(12 * mm, 8 * mm, f'TVM · {reference} · Données enregistrées')
        canvas.drawRightString(198 * mm, 8 * mm, f'Page {doc.page}')
        canvas.restoreState()
    return document, footer


def _header(title, reference, date, styles):
    header = _table([[TVMMark(), _p(title, styles, 'head')]], [140, WIDTH - 140], grid=False, padding=0)
    call = _table([[_p('Appel', styles, 'white'), _p(reference, styles), _p('Date', styles, 'white'), _p(_date(date), styles)]], [22 * mm, 71 * mm, 22 * mm, 71 * mm])
    call.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, 0), BLUE), ('BACKGROUND', (2, 0), (2, 0), BLUE)]))
    return [header, Spacer(1, 4), call, Spacer(1, 6)]


def _check(label, value, styles):
    mark = '[X]' if value is True else '[ ]' if value is False else '[-]'
    return _p(f'{mark} {label}', styles)


def _section(intervention, key):
    data = intervention.structured_data
    result = data.get(key, {}) if isinstance(data, dict) else {}
    return result if isinstance(result, dict) else {}


def _brief(value, limit=400):
    return value if len(value or '') <= limit else 'Texte intégral dans les informations complémentaires.'


def intervention_report(intervention):
    """TVM reference form rebuilt from public database fields."""
    styles = _styles()
    request = intervention.service_request
    equipment, client = request.equipment, request.equipment.client
    output = BytesIO()
    document, footer = _document(output, 'Rapport d’intervention', intervention.reference)
    story = _header('Rapport d’intervention', request.reference, intervention.performed_on, styles)
    company = _table([
        [_p('SOCIÉTÉ', styles, 'white'), _p(client.name, styles), _p('Contact', styles, 'white'), _p(intervention.contact_name or request.contact_name or client.contact_name, styles)],
        [_p('Client final', styles, 'white'), _p(intervention.end_customer or request.end_customer, styles), _p('Ville', styles, 'white'), _p(client.city, styles)],
    ], [24 * mm, 75 * mm, 27 * mm, 60 * mm])
    company.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, -1), BLUE), ('BACKGROUND', (2, 0), (2, -1), BLUE)]))
    story += [company, Spacer(1, 6)]
    types = _table([
        [_check('Extension de garantie', bool(intervention.extension_warranty_id), styles), _check('Maintenance', intervention.kind == 'maintenance', styles)],
        [_check('Mise en service', intervention.kind == 'commissioning', styles), _check('Préventive', intervention.kind == 'preventive', styles)],
        [_check('Contrat', bool(intervention.contract_id), styles), _check('Échange', intervention.kind == 'exchange', styles)],
    ], [39 * mm, 38 * mm], grid=False, padding=2)
    replacement = intervention.replacement_equipment
    serials = _fields([('SN / Modèle', f'{equipment.serial_number} / {equipment.model}'), ('Armoire SN', intervention.cabinet_serial), ('Nouveau SN', replacement.serial_number if replacement else None)], styles, [28 * mm, 57 * mm])
    type_box = _table([[_p('TYPE\nINTERVENTION', styles, 'white'), types, serials]], [24 * mm, 77 * mm, 85 * mm], padding=0)
    type_box.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, 0), BLUE), ('VALIGN', (0, 0), (0, 0), 'MIDDLE'), ('LEFTPADDING', (0, 0), (0, 0), 4)]))
    contract, extension = intervention.contract, intervention.extension_warranty
    period = lambda item: f'Du {_date(item.starts_on)} au {_date(item.ends_on)}' if item else 'Non renseignée'
    story += [type_box, Spacer(1, 6), _fields([('Contrat N°', contract.number if contract else None), ('Durée du contrat', period(contract)), ('Durée d’extension', f'{extension.provider} · {period(extension)} · {extension.get_scope_display()}' if extension else None)], styles), Spacer(1, 7), _bar('TRAVAUX PRÉVENTIFS', styles)]
    preventive = _section(intervention, 'preventive')
    preventive_checks = [_check(label, preventive.get(key), styles) for key, label in CHECKLISTS['preventive']['checks'].items()]
    story += [_table([[_p('Contrôle effectué', styles), _p('Commentaire', styles)], [preventive_checks, _p(_brief(preventive.get('comment', ''), 200), styles)]], [WIDTH / 2, WIDTH / 2]), Spacer(1, 6)]
    maintenance = _section(intervention, 'maintenance')
    keys = list(CHECKLISTS['maintenance']['checks'])
    failures = [_check(CHECKLISTS['maintenance']['checks'][key], maintenance.get(key), styles) for key in keys[:5]]
    actions = [_check(CHECKLISTS['maintenance']['checks'][key] + (f' : {maintenance["battery_replaced_count"]}' if key == 'replace_batteries' and type(maintenance.get('battery_replaced_count')) is int else ''), maintenance.get(key), styles) for key in keys[5:]]
    maintenance_box = _table([[_p('Nature de la panne', styles), _p('Action', styles)], [failures, actions]], [53 * mm, 53 * mm])
    commissioning = _section(intervention, 'commissioning')
    commissioning_checks = [_check(label, commissioning.get(key), styles) for key, label in CHECKLISTS['commissioning']['checks'].items()]
    columns = _table([[_bar('Maintenance', styles, 106 * mm), _bar('MISE EN SERVICE', styles, 76 * mm)], [maintenance_box, _table([[commissioning_checks]], [76 * mm])]], [110 * mm, 76 * mm], grid=False, padding=0)
    synthesis = intervention.summary or intervention.work_done or intervention.diagnosis
    conclusions = [_check(label, intervention.conclusion == key if intervention.conclusion else None, styles) for key, label in CONCLUSIONS.items()]
    summary_box = _table([[_bar('SYNTHÈSE', styles, 142 * mm), _bar('CONCLUSION', styles, 44 * mm)], [_p(_brief(synthesis), styles), conclusions]], [142 * mm, 44 * mm])
    summary_box.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, 0), 0), ('RIGHTPADDING', (0, 0), (-1, 0), 0), ('TOPPADDING', (0, 0), (-1, 0), 0), ('BOTTOMPADDING', (0, 0), (-1, 0), 0)]))
    technician = (intervention.technician.get_full_name() or intervention.technician.username) if intervention.technician else 'Non affecté'
    validation = _table([[_p('Nom et visa technicien', styles), _p('Partenaire', styles), _p('Nom client et cachet', styles)], [_p(f'{technician}\nVisa non recueilli', styles), _p('Non renseigné', styles), _p(f'{client.name}\nSignature / cachet non recueilli', styles)]], [WIDTH / 3] * 3)
    story += [columns, Spacer(1, 6), summary_box, Spacer(1, 6), _bar('VALIDATION', styles), validation, Spacer(1, 5), _p('Cases : [X] cochée ; [ ] non cochée ; [-] non renseignée. Aucun contrôle absent n’est présumé réalisé.', styles, 'small')]
    if intervention.status != 'completed':
        story.append(_p('RAPPORT PROVISOIRE — intervention non terminée.', styles, 'small'))
    story.append(_p(f'{INTERVENTION_KINDS.get(intervention.kind, "Intervention")} · {intervention.reference} · État : {intervention.get_status_display()}', styles, 'small'))
    details = [('Référence client', request.client_reference), ('Arrivée du matériel', _date(request.arrived_at, True) if request.arrived_at else ''), ('Clôture du dossier', _date(request.closed_at, True) if request.closed_at else ''), ('Signalement', request.description or request.subject), ('Date planifiée', _date(intervention.scheduled_at, True) if intervention.scheduled_at else ''), ('Diagnostic', intervention.diagnosis), ('Travaux réalisés', intervention.work_done), ('Recommandations', intervention.recommendations), ('Synthèse intégrale', synthesis if len(synthesis or '') > 400 else ''), ('Précisions de conclusion', intervention.conclusion_notes), ('Site de l’opération', intervention.site or equipment.location), ('Téléphone du contact', intervention.contact_phone or request.contact_phone or client.phone)]
    for section in report_checklists(intervention.structured_data):
        if section['comment']:
            details.append((section['title'] + ' — commentaire', section['comment']))
    details.append(('Matériel', f'{equipment.brand} {equipment.model} · {equipment.power_kva} kVA · Batteries : {intervention.battery_count if intervention.battery_count is not None else "non renseignées"}'))
    if intervention.kind == 'exchange':
        details.insert(0, ('Fiche d’échange', f'Ancien numéro de série : {equipment.serial_number}\nNouveau numéro de série : {replacement.serial_number if replacement else "non renseigné"}'))
    story += [Spacer(1, 8), _bar('INFORMATIONS COMPLÉMENTAIRES', styles)]
    for title, value in details:
        if value:
            story += [_p(title, styles), _p(value, styles), Spacer(1, 5)]
    movements = intervention.parts_used.filter(quantity__lt=0).select_related('part')
    if movements.exists():
        story += [_bar('PIÈCES UTILISÉES', styles), _table([[_p('Référence', styles), _p('Désignation', styles), _p('Quantité', styles)]] + [[_p(item.part.sku, styles), _p(item.part.name, styles), _p(abs(item.quantity), styles)] for item in movements], [40 * mm, 126 * mm, 20 * mm], repeat=1)]
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def service_request_report(request, *, now=None):
    """Public follow-up; the HTTP caller must scope the request beforehand."""
    from .request_timing import request_timing
    styles = _styles()
    output = BytesIO()
    document, footer = _document(output, 'Fiche de suivi SAV', request.reference)
    client, equipment = request.equipment.client, request.equipment
    story = _header('Fiche de suivi SAV', request.reference, request.created_at, styles)
    timing = request_timing(request.arrived_at, request.closed_at, request.status, now=now)
    elapsed = 'Inconnu' if timing['elapsed_hours'] is None else f'{timing["elapsed_hours"]:.2f} heures ouvrées · {timing["elapsed_days"]} jour(s) ouvré(s)'
    state = {'unknown': 'Arrivée / clôture non suffisamment renseignée', 'running': 'En cours', 'closed': 'Arrêté à la clôture'}[timing['timer_state']]
    story += [_bar('DOSSIER ET COMPTEUR DE TRAITEMENT', styles), _fields([
        ('Dossier / état', f'{request.reference} · {request.get_status_display()}'), ('Société', client.name), ('Référence client', request.client_reference), ('Client final', request.end_customer),
        ('Arrivée', _date(request.arrived_at, True)), ('Clôture', _date(request.closed_at, True)), ('Temps écoulé', elapsed), ('Compteur', state),
        ('Seuil de 2 jours ouvrés', 'Dépassé' if timing['is_overdue_48h'] else 'Non dépassé' if timing['elapsed_hours'] is not None else 'Inconnu'),
        ('Base de calcul', '48 heures ouvrées ; samedi et dimanche exclus. Sans exclusion des jours fériés ni horaires de bureau.'),
        ('Fuseau du compteur', timing['timezone']), ('Calcul au', _date(datetime.fromisoformat(timing['as_of']), True)),
    ], styles, highlight=('Temps écoulé', 'Seuil de 2 jours ouvrés') if timing['is_overdue_48h'] else ()), Spacer(1, 7), _bar('MATÉRIEL ET RÉCEPTION', styles)]
    site_labels = {'workshop': 'Atelier', 'depot': 'Dépôt', 'onsite': 'Sur site'}
    delivery_labels = {'courier': 'Transporteur', 'client': 'Client'}
    warranty_labels = {'unspecified': 'Non précisé', 'warranty': 'Garantie', 'quotation': 'Devis', 'contract': 'Contrat', 'billable': 'Facturable'}
    story.append(_fields([
        ('Numéro de série', equipment.serial_number), ('Marque / modèle', f'{equipment.brand} {equipment.model}'), ('Puissance', f'{equipment.power_kva} kVA'), ('Site / emplacement', equipment.location),
        ('Retour', 'Oui' if request.return_flag else 'Non'), ('Emballage', request.packaging), ('Lieu de traitement', site_labels.get(request.service_location, 'Non renseigné')),
        ('Livré par', delivery_labels.get(request.delivered_by, 'Non renseigné')), ('Transporteur', request.courier_name), ('Accessoires', request.accessories),
        ('Traitement déclaré', warranty_labels.get(request.warranty_status, 'Non précisé')), ('Contact', request.contact_name or client.contact_name), ('Téléphone', request.contact_phone or client.phone), ('E-mail', request.contact_email or client.email),
    ], styles))
    story += [Spacer(1, 7), _bar('SIGNALEMENT', styles), _p(request.subject, styles), _p(request.description, styles)]
    if timing['warning']:
        story += [_p('Information sur le compteur', styles), _p(timing['warning'], styles)]
    story += [Spacer(1, 7), _bar('SUIVI CHRONOLOGIQUE PUBLIC', styles)]
    events = request.operation_events.filter(is_internal=False, equipment__client_id=equipment.client_id).filter(Q(related_equipment__isnull=True) | Q(related_equipment__client_id=equipment.client_id)).order_by('created_at', 'id')
    if not events.exists():
        story.append(_p('Aucune opération publique enregistrée.', styles))
    for event in events:
        title = f'{_date(event.created_at, True)} · Équipe SAV'
        if event.source == 'baseline':
            title += ' · État repris lors de l’activation ; opérations antérieures non reconstituées'
        story.append(_p(title, styles))
        if event.status_before or event.status_after:
            from .models import Intervention
            choices = dict(Intervention.Status.choices if event.kind.startswith('intervention_') or event.kind == 'baseline' and event.intervention_id else request.Status.choices)
            before = choices.get(event.status_before, event.status_before)
            after = choices.get(event.status_after, event.status_after)
            if before and after:
                state_text = f'État : {before} -> {after}'
            elif after:
                label = 'État constaté' if event.source == 'baseline' or event.kind == 'baseline' else 'État initial'
                state_text = f'{label} : {after}'
            else:
                state_text = f'État précédent : {before}'
            story.append(_p(state_text, styles))
        for value in (event.summary, event.observation):
            if value:
                story.append(_p(value, styles))
        story.append(Spacer(1, 6))
    interventions = request.interventions.select_related('replacement_equipment', 'technician').order_by('created_at', 'id')
    if interventions.exists():
        story += [Spacer(1, 7), _bar('INTERVENTIONS ET RAPPORTS ASSOCIÉS', styles)]
        for intervention in interventions:
            story += [_p(f'{intervention.reference} · {INTERVENTION_KINDS.get(intervention.kind, intervention.kind)} · {intervention.get_status_display()}', styles), _p(f'Rapport détaillé : /api/interventions/{intervention.pk}/report/', styles, 'small')]
            for title, value in [('Diagnostic', intervention.diagnosis), ('Travaux réalisés', intervention.work_done), ('Recommandations', intervention.recommendations), ('Synthèse', intervention.summary), ('Conclusion', intervention.conclusion_notes)]:
                if value:
                    story += [_p(title, styles), _p(value, styles)]
            story.append(Spacer(1, 6))
    story.append(_p('Situation au moment de la génération. Notes internes exclues ; anciennes opérations non importées non reconstituées. Aucun visa ni cachet présumé recueilli.', styles, 'small'))
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
