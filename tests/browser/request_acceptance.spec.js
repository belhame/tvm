import { test, expect } from '@playwright/test';

const password = process.env.TVM_DEMO_PASSWORD;
const marker = () => `SAV-PRISE-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

async function login(page, username = 'admin', client = false) {
  if (!password) throw new Error('Utiliser bash scripts/e2e.sh avec le mot de passe local privé.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await expect(page.getByRole('heading', { name: client ? /Tableau de bord|Mon espace/ : 'Demandes SAV', exact: !client }).first()).toBeVisible();
}

async function response(page, path, method = 'GET', data) {
  const { csrfToken } = await (await page.request.get('/api/session/')).json();
  return page.request.fetch(`/api/${path}`, { method, data, headers: { 'X-CSRFToken': csrfToken } });
}

async function api(page, path, method = 'GET', data) {
  const result = await response(page, path, method, data);
  expect(result.ok(), `${method} ${path}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

async function laboratory(page) {
  const tag = marker();
  const company = await api(page, 'clients/', 'POST', { name: `Centre de prise en charge fictif ${tag}`, email: 'centre-prise@example.invalid' });
  const unit = await api(page, 'equipment/', 'POST', { client: company.id, serial_number: `SN-${tag}`, model: 'Onduleur fictif de suivi' });
  const techA = await api(page, 'users/', 'POST', { username: `tech-a-${tag}`, first_name: 'Technicien A fictif', role: 'technician', password });
  const techB = await api(page, 'users/', 'POST', { username: `tech-b-${tag}`, first_name: 'Technicien B fictif', role: 'technician', password });
  const portal = await api(page, 'users/', 'POST', { username: `portail-${tag}`, role: 'client', client: company.id, password });
  const record = await api(page, 'requests/', 'POST', { equipment: unit.id, subject: tag, client_reference: `000-CLIENT-${tag}` });
  return { tag, company, unit, techA, techB, portal, record };
}

async function rowFor(page, lab) {
  await expect(page.getByRole('heading', { name: 'Demandes SAV', exact: true })).toBeVisible();
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(lab.tag);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  const row = page.locator('tbody tr').filter({ hasText: lab.record.reference });
  await expect(row).toHaveCount(1);
  return row;
}

async function dossier(page, lab) {
  const row = await rowFor(page, lab);
  await row.getByRole('button', { name: `Ouvrir ${lab.record.reference}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Dossier SAV', exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function assignViaUI(page, lab, technician) {
  const row = await rowFor(page, lab);
  await row.getByRole('button', { name: 'Affecter', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Affecter la demande', exact: true });
  await panel.getByLabel('Technicien de la demande', { exact: true }).selectOption(String(technician.id));
  const saved = page.waitForResponse(r => new URL(r.url()).pathname === `/api/requests/${lab.record.id}/assignment/` && r.request().method() === 'POST');
  await panel.getByRole('button', { name: 'Affecter', exact: true }).click();
  const result = await saved;
  expect(result.status()).toBe(200);
  await expect(panel).toHaveCount(0);
  return result.json();
}

async function confirmViaUI(page, dialog, record) {
  await dialog.getByRole('button', { name: 'Confirmer la prise en charge', exact: true }).click();
  const panel = page.getByRole('alertdialog', { name: 'Confirmer la prise en charge', exact: true });
  await expect(panel).toContainText(record.reference);
  const saved = page.waitForResponse(r => new URL(r.url()).pathname === `/api/requests/${record.id}/assignment/confirm/` && r.request().method() === 'POST');
  await panel.getByRole('button', { name: 'Oui', exact: true }).click();
  const result = await saved;
  expect(result.status()).toBe(200);
  await expect(panel).toHaveCount(0);
  await expect(dialog.getByLabel('État du dossier', { exact: true })).toBeVisible();
  return result.json();
}

async function followup(page, dialog, record, { status, observation, summary = '' }) {
  if (status) await dialog.getByLabel('État du dossier', { exact: true }).selectOption(status);
  await dialog.getByLabel('Observation', { exact: true }).fill(observation);
  await dialog.getByLabel('Observation finale / synthèse', { exact: true }).fill(summary);
  const saved = page.waitForResponse(r => new URL(r.url()).pathname === `/api/requests/${record.id}/followup/` && r.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Enregistrer le suivi', exact: true }).click();
  const result = await saved;
  expect(result.status(), await result.text()).toBe(201);
  await expect(dialog.getByRole('region', { name: 'Historique des opérations', exact: true })).toContainText(observation);
  return result.json();
}

test('le SAV ouvre en premier et le technicien confirme explicitement avant le suivi commenté sans intervention', async ({ page, browser }) => {
  await login(page);
  const nav = page.getByRole('navigation', { name: 'Navigation principale', exact: true });
  const labels = await nav.getByRole('button').allTextContents();
  expect(labels[0]).toContain('Demandes SAV');
  expect(labels.findIndex(x => x.includes('Demandes SAV'))).toBeLessThan(labels.findIndex(x => x === 'Interventions'));
  const lab = await laboratory(page);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Demandes SAV', exact: true })).toBeVisible();
  const assigned = await assignViaUI(page, lab, lab.techA);
  expect(assigned).toMatchObject({ status: 'pending', assignment: { accepted: false, technician: lab.techA.id } });

  const context = await browser.newContext();
  const tech = await context.newPage();
  try {
    await login(tech, lab.techA.username);
    const dialog = await dossier(tech, lab);
    await expect(dialog.locator('.sav-followup-readonly')).toContainText('Confirmez votre prise en charge');
    expect((await response(tech, `requests/${lab.record.id}/followup/`, 'POST', { status: 'maintenance', expected_status: 'pending', assignment_revision: assigned.assignment.revision, observation: 'Tentative avant confirmation' })).status()).toBe(403);
    await dialog.getByRole('button', { name: 'Confirmer la prise en charge', exact: true }).click();
    const cancelled = tech.getByRole('alertdialog', { name: 'Confirmer la prise en charge', exact: true });
    await cancelled.getByRole('button', { name: 'Annuler', exact: true }).click();
    expect((await api(tech, `requests/${lab.record.id}/`)).assignment.accepted).toBe(false);
    const accepted = await confirmViaUI(tech, dialog, lab.record);
    expect(accepted.assignment).toMatchObject({ accepted: true, accepted_by: lab.techA.id, technician: lab.techA.id });
    expect(accepted.assignment.accepted_at).toBeTruthy();
    const note = `${lab.tag} batterie contrôlée et entretien commencé`;
    const result = await followup(tech, dialog, lab.record, { status: 'maintenance', observation: note, summary: 'Contrôle technique fictif à poursuivre' });
    expect(result.request.status).toBe('maintenance');
    expect(result.events.some(event => event.observation === note && event.is_internal)).toBe(true);
    expect((await api(page, 'interventions/')).filter(visit => visit.service_request === lab.record.id)).toEqual([]);
    await expect(dialog.locator('.sav-followup-layout')).toBeVisible();
    const timeline = dialog.getByRole('region', { name: 'Historique des opérations', exact: true });
    await expect(timeline.locator('.operation-timeline-item').first()).toContainText(note);
    await tech.setViewportSize({ width: 390, height: 844 });
    expect(await tech.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await tech.screenshot({ path: '../../.local/sav-followup-technician-mobile.png', fullPage: true });
  } finally {
    await context.close();
  }
});

test('réaffecter retire les droits de l’ancien intervenant et le portail ne reçoit que les états et notes partagés', async ({ page, browser }) => {
  await login(page);
  const lab = await laboratory(page);
  const assigned = await api(page, `requests/${lab.record.id}/assignment/`, 'POST', { technician: lab.techA.id, expected_revision: 0 });
  const visit = await api(page, 'interventions/', 'POST', { service_request: lab.record.id, technician: lab.techA.id, work_done: 'Constat fictif', status: 'in_progress' });
  const contextA = await browser.newContext();
  const contextB = await browser.newContext();
  const contextClient = await browser.newContext();
  const techA = await contextA.newPage(), techB = await contextB.newPage(), client = await contextClient.newPage();
  try {
    await login(techA, lab.techA.username);
    const aDialog = await dossier(techA, lab);
    await confirmViaUI(techA, aDialog, lab.record);
    const lostNote = `${lab.tag} brouillon de l’ancien technicien à ne pas enregistrer`;
    await aDialog.getByLabel('Observation', { exact: true }).fill(lostNote);
    const reassigned = await api(page, `requests/${lab.record.id}/assignment/`, 'POST', { technician: lab.techB.id, expected_revision: assigned.assignment.revision });
    expect(reassigned.assignment).toMatchObject({ accepted: false, technician: lab.techB.id });
    const rejected = techA.waitForResponse(r => new URL(r.url()).pathname === `/api/requests/${lab.record.id}/followup/` && r.request().method() === 'POST');
    await aDialog.getByRole('button', { name: 'Enregistrer le suivi', exact: true }).click();
    expect([403, 409]).toContain((await rejected).status());
    expect((await response(techA, `interventions/${visit.id}/`, 'PATCH', { work_done: 'Modification désormais interdite' })).status()).toBe(403);
    expect(JSON.stringify(await api(page, `requests/${lab.record.id}/timeline/`))).not.toContain(lostNote);
    await techA.reload();
    const readOnly = await dossier(techA, lab);
    await expect(readOnly.locator('.sav-followup-readonly')).toBeVisible();
    await expect(readOnly.getByRole('button', { name: 'Confirmer la prise en charge', exact: true })).toHaveCount(0);

    await login(techB, lab.techB.username);
    const bDialog = await dossier(techB, lab);
    await confirmViaUI(techB, bDialog, lab.record);
    const privateNote = `${lab.tag} observation interne du technicien B`;
    await followup(techB, bDialog, lab.record, { status: 'testing', observation: privateNote, summary: 'Synthèse interne de test' });
    await login(client, lab.portal.username, true);
    await client.getByRole('navigation', { name: 'Navigation principale', exact: true }).getByText('Demandes SAV', { exact: true }).click();
    const clientDialog = await dossier(client, lab);
    await expect(clientDialog).toContainText('En test');
    await expect(clientDialog).not.toContainText(privateNote);
    await expect(clientDialog).not.toContainText('Synthèse interne de test');
    await expect(clientDialog.getByRole('button', { name: 'Enregistrer le suivi', exact: true })).toHaveCount(0);
    await expect(clientDialog.getByRole('button', { name: 'Confirmer la prise en charge', exact: true })).toHaveCount(0);
    const events = await api(client, `requests/${lab.record.id}/timeline/`);
    expect(events.every(event => !event.is_internal)).toBe(true);
    expect(events.some(event => event.kind === 'status_changed' && event.status_after === 'testing')).toBe(true);
  } finally {
    await Promise.all([contextA.close(), contextB.close(), contextClient.close()]);
  }
});

test('l’administrateur suit une demande sans acceptation et peut confirmer au nom du technicien avec un motif privé', async ({ page }) => {
  await login(page);
  const lab = await laboratory(page);
  await page.reload();
  const dialog = await dossier(page, lab);
  const result = await followup(page, dialog, lab.record, { status: 'pending', observation: 'Qualification administrative fictive avant affectation' });
  expect(result.request.status).toBe('pending');
  await dialog.getByRole('button', { name: 'Modifier l’affectation', exact: true }).click();
  const assignment = page.getByRole('region', { name: 'Affecter la demande', exact: true });
  await assignment.getByLabel('Technicien de la demande', { exact: true }).selectOption(String(lab.techA.id));
  const assigned = page.waitForResponse(r => new URL(r.url()).pathname === `/api/requests/${lab.record.id}/assignment/` && r.request().method() === 'POST');
  await assignment.getByRole('button', { name: 'Affecter', exact: true }).click();
  expect((await assigned).status()).toBe(200);
  await dialog.getByRole('button', { name: 'Confirmer au nom du technicien', exact: true }).click();
  const proxy = page.getByRole('alertdialog', { name: 'Confirmation administrative', exact: true });
  await expect(proxy.getByRole('button', { name: 'Oui', exact: true })).toBeDisabled();
  const reason = `${lab.tag} validation administrative explicitement justifiée`;
  await proxy.getByLabel('Motif de confirmation au nom du technicien', { exact: true }).fill(reason);
  const confirmed = page.waitForResponse(r => new URL(r.url()).pathname === `/api/requests/${lab.record.id}/assignment/confirm/` && r.request().method() === 'POST');
  await proxy.getByRole('button', { name: 'Oui', exact: true }).click();
  const answer = await (await confirmed).json();
  expect(answer.assignment.accepted).toBe(true);
  const session = await api(page, 'session/');
  expect(answer.assignment.accepted_by).toBe(session.user.id);
  const events = await api(page, `requests/${lab.record.id}/timeline/`);
  expect(events.some(event => event.kind === 'assignment_override' && event.observation === reason && event.is_internal)).toBe(true);
});
