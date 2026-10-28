import { test, expect } from '@playwright/test';
import { openRequestsWorkspace } from './legacy_navigation.js';

const password = process.env.TVM_DEMO_PASSWORD;
const marker = () => `RELAIS-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

async function login(page, username = 'admin', client = false) {
  if (!password) throw new Error('Utiliser bash scripts/e2e.sh avec le mot de passe local privé.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await expect(page.getByRole('heading', {
    name: client ? /Tableau de bord|Mon espace/ : 'Tableau de bord', exact: !client,
  }).first()).toBeVisible();
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
  const company = await api(page, 'clients/', 'POST', { name: `Centre de relais fictif ${tag}` });
  const unit = await api(page, 'equipment/', 'POST', {
    client: company.id, serial_number: `SN-${tag}`, model: 'Onduleur fictif de relais',
  });
  const techA = await api(page, 'users/', 'POST', {
    username: `relais-a-${tag}`, first_name: 'Alice', last_name: 'Laboratoire', role: 'technician', password,
  });
  const techB = await api(page, 'users/', 'POST', {
    username: `relais-b-${tag}`, first_name: 'Benoît', last_name: 'Laboratoire', role: 'technician', password,
  });
  const portal = await api(page, 'users/', 'POST', {
    username: `relais-client-${tag}`, role: 'client', client: company.id, password,
  });
  const record = await api(page, 'requests/', 'POST', {
    equipment: unit.id, subject: tag, client_reference: `000-RELAIS-${tag}`,
  });
  return { tag, company, unit, techA, techB, portal, record };
}

async function rowFor(page, lab) {
  await openRequestsWorkspace(page);
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

async function openAction(page, scope, lab, mode) {
  const title = mode === 'claim' ? 'Prendre en charge' : 'Prendre le relais';
  await scope.getByRole('button', { name: title, exact: true }).click();
  const panel = page.getByRole('alertdialog', { name: title, exact: true });
  await expect(panel).toBeVisible();
  await expect(panel).toContainText(lab.record.reference);
  await expect(panel).toContainText('Technicien actuel');
  await expect(panel).toContainText('Nouveau technicien');
  return panel;
}

async function saveAction(page, panel, lab, mode) {
  const saved = page.waitForResponse(result =>
    new URL(result.url()).pathname === `/api/requests/${lab.record.id}/assignment/${mode}/`
    && result.request().method() === 'POST');
  await panel.getByRole('button', { name: 'Oui', exact: true }).click();
  const result = await saved;
  expect(result.status(), await result.text()).toBe(200);
  await expect(panel).toHaveCount(0);
  return result.json();
}

async function followup(page, dialog, lab, status, observation, summary = '') {
  await dialog.getByLabel('État du dossier', { exact: true }).selectOption(status);
  await dialog.getByLabel('Observation', { exact: true }).fill(observation);
  await dialog.getByLabel('Observation finale / synthèse', { exact: true }).fill(summary);
  await expect(dialog.getByRole('checkbox', { name: /Notes internes/ })).toBeChecked();
  const saved = page.waitForResponse(result =>
    new URL(result.url()).pathname === `/api/requests/${lab.record.id}/followup/`
    && result.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Enregistrer le suivi', exact: true }).click();
  const result = await saved;
  expect(result.status(), await result.text()).toBe(201);
  await expect(dialog.getByRole('region', { name: 'Historique des opérations', exact: true })).toContainText(observation);
  return result.json();
}

test('le technicien prend un dossier non affecté en un geste confirmé, puis le responsable garde son pouvoir d’affectation', async ({ page, browser }) => {
  await login(page);
  const lab = await laboratory(page);
  const techContext = await browser.newContext();
  const clientContext = await browser.newContext();
  const tech = await techContext.newPage(), client = await clientContext.newPage();
  try {
    await login(tech, lab.techA.username);
    const row = await rowFor(tech, lab);
    expect((await api(tech, `requests/${lab.record.id}/`)).assignment).toMatchObject({
      technician: null, revision: 0, accepted: false, can_claim: true, can_takeover: false,
    });
    let posts = 0;
    const observeClaim = request => {
      if (request.method() === 'POST'
          && new URL(request.url()).pathname === `/api/requests/${lab.record.id}/assignment/claim/`) posts += 1;
    };
    tech.on('request', observeClaim);
    const cancelled = await openAction(tech, row, lab, 'claim');
    await expect(cancelled).toContainText('Aucun technicien affecté');
    await expect(cancelled.locator('.request-assignment-handover')).toContainText('Alice Laboratoire');
    await cancelled.getByRole('button', { name: 'Annuler', exact: true }).click();
    await expect(cancelled).toHaveCount(0);
    expect((await api(page, `requests/${lab.record.id}/`))).toMatchObject({
      status: 'new', assigned_technician: null, assignment: { revision: 0, accepted: false },
    });
    expect(posts).toBe(0);

    const panel = await openAction(tech, row, lab, 'claim');
    const claimed = await saveAction(tech, panel, lab, 'claim');
    tech.off('request', observeClaim);
    expect(posts).toBe(1);
    expect(claimed).toMatchObject({ status: 'pending', assigned_technician: lab.techA.id, assignment: {
      revision: 1, accepted: true, accepted_by: lab.techA.id, can_write_followup: true,
      can_claim: false, can_takeover: false,
    } });
    expect(claimed.assignment.accepted_at).toBeTruthy();
    await expect(row.locator('.request-assignment')).toContainText('Prise en charge confirmée');
    const dialog = await dossier(tech, lab);
    await expect(dialog.getByRole('button', { name: 'Confirmer la prise en charge', exact: true })).toHaveCount(0);
    const note = `${lab.tag} contrôle des batteries commencé par Alice`;
    await followup(tech, dialog, lab, 'maintenance', note);
    expect((await api(page, 'interventions/')).filter(visit => visit.service_request === lab.record.id)).toEqual([]);
    const history = await api(page, `requests/${lab.record.id}/timeline/`);
    expect(history.some(event => event.kind === 'assignment_claimed' && event.actor_name === 'Alice Laboratoire' && event.is_internal)).toBe(true);
    expect(history.some(event => event.observation === note && event.actor_name === 'Alice Laboratoire' && event.is_internal)).toBe(true);

    // Self-service does not remove the administrator's separate assignment action.
    await page.reload();
    const adminRow = await rowFor(page, lab);
    await expect(adminRow.getByRole('button', { name: 'Prendre en charge', exact: true })).toHaveCount(0);
    await expect(adminRow.getByRole('button', { name: 'Prendre le relais', exact: true })).toHaveCount(0);
    await adminRow.getByRole('button', { name: 'Affecter', exact: true }).click();
    const assignment = page.getByRole('region', { name: 'Affecter la demande', exact: true });
    await assignment.getByLabel('Technicien de la demande', { exact: true }).selectOption(String(lab.techB.id));
    const assigned = page.waitForResponse(result =>
      new URL(result.url()).pathname === `/api/requests/${lab.record.id}/assignment/` && result.request().method() === 'POST');
    await assignment.getByRole('button', { name: 'Affecter', exact: true }).click();
    const answer = await assigned;
    expect(answer.status()).toBe(200);
    const managed = await answer.json();
    expect(managed).toMatchObject({ status: 'maintenance', assignment: {
      revision: 2, technician: lab.techB.id, accepted: false, accepted_at: null, accepted_by: null,
    } });
    expect((await response(page, `requests/${lab.record.id}/assignment/claim/`, 'POST', { expected_revision: 2 })).status()).toBe(403);

    await login(client, lab.portal.username, true);
    await client.getByRole('navigation', { name: 'Navigation principale', exact: true }).getByText('Demandes SAV', { exact: true }).click();
    const publicDialog = await dossier(client, lab);
    await expect(publicDialog).toContainText('En entretien');
    for (const label of ['Prendre en charge', 'Prendre le relais', 'Confirmer la prise en charge', 'Modifier l’affectation', 'Enregistrer le suivi']) {
      await expect(publicDialog.getByRole('button', { name: label, exact: true })).toHaveCount(0);
    }
    const publicRecord = await api(client, `requests/${lab.record.id}/`);
    for (const key of ['assignment', 'assignment_revision', 'assigned_at', 'assignment_accepted_at', 'assignment_accepted_by', 'assignment_accepted_revision']) {
      expect(publicRecord).not.toHaveProperty(key);
    }
    const publicHistory = await api(client, `requests/${lab.record.id}/timeline/`);
    expect(JSON.stringify(publicHistory)).not.toContain(note);
    expect(publicHistory.every(event => !event.is_internal && event.actor_name === 'Équipe SAV')).toBe(true);
    expect(publicHistory.some(event => event.kind === 'status_changed' && event.status_after === 'maintenance')).toBe(true);
    expect((await response(client, `requests/${lab.record.id}/assignment/takeover/`, 'POST', {
      expected_revision: 2, reason: 'Tentative du portail fictif',
    })).status()).toBe(403);
  } finally {
    await Promise.all([techContext.close(), clientContext.close()]);
  }
});

test('le relais motivé conserve les auteurs et retire immédiatement les droits de l’ancien technicien et de ses anciennes visites', async ({ page, browser }) => {
  await login(page);
  const lab = await laboratory(page);
  const contextA = await browser.newContext(), contextB = await browser.newContext(), clientContext = await browser.newContext();
  const techA = await contextA.newPage(), techB = await contextB.newPage(), client = await clientContext.newPage();
  try {
    await login(techA, lab.techA.username);
    const aDialog = await dossier(techA, lab);
    const claim = await openAction(techA, aDialog, lab, 'claim');
    const claimed = await saveAction(techA, claim, lab, 'claim');
    const noteA = `${lab.tag} constat initial conservé d’Alice`;
    await followup(techA, aDialog, lab, 'maintenance', noteA);
    const visit = await api(page, 'interventions/', 'POST', {
      service_request: lab.record.id, technician: lab.techA.id, status: 'in_progress',
      diagnosis: 'Diagnostic fictif initial', work_done: 'Contrôles fictifs réalisés par Alice',
      internal_notes: `${lab.tag} note privée de la visite initiale`,
    });
    const earlier = await api(page, `requests/${lab.record.id}/timeline/`);
    const earlierNote = earlier.find(event => event.observation === noteA);
    expect(earlierNote).toMatchObject({ actor_name: 'Alice Laboratoire', is_internal: true });
    const lostDraft = `${lab.tag} brouillon périmé de l’ancien responsable`;
    await aDialog.getByLabel('Observation', { exact: true }).fill(lostDraft);

    await login(techB, lab.techB.username);
    const bDialog = await dossier(techB, lab);
    const initial = await api(techB, `requests/${lab.record.id}/`);
    expect(initial.assignment).toMatchObject({ technician: lab.techA.id, can_claim: false, can_takeover: true });
    const cancelled = await openAction(techB, bDialog, lab, 'takeover');
    const handover = cancelled.locator('.request-assignment-handover');
    await expect(handover.locator('dl > div').filter({ has: techB.locator('dt', { hasText: 'Technicien actuel' }) }).locator('dd')).toHaveText('Alice Laboratoire');
    await expect(handover.locator('dl > div').filter({ has: techB.locator('dt', { hasText: 'Nouveau technicien' }) }).locator('dd')).toHaveText('Benoît Laboratoire');
    await expect(cancelled.getByRole('button', { name: 'Oui', exact: true })).toBeDisabled();
    await cancelled.getByLabel('Motif de la prise de relais', { exact: true }).fill('   ');
    await expect(cancelled.getByRole('button', { name: 'Oui', exact: true })).toBeDisabled();
    await cancelled.getByRole('button', { name: 'Annuler', exact: true }).click();
    await expect(cancelled).toHaveCount(0);
    expect((await api(page, `requests/${lab.record.id}/`)).assignment).toMatchObject({
      revision: claimed.assignment.revision, technician: lab.techA.id, accepted: true,
      accepted_at: claimed.assignment.accepted_at,
    });

    const reason = `${lab.tag} relais interne motivé pour continuité du contrôle`;
    const takeover = await openAction(techB, bDialog, lab, 'takeover');
    await expect(takeover.getByLabel('Motif de la prise de relais', { exact: true })).toHaveValue('');
    await takeover.getByLabel('Motif de la prise de relais', { exact: true }).fill(reason);
    const taken = await saveAction(techB, takeover, lab, 'takeover');
    expect(taken).toMatchObject({ status: 'maintenance', assignment: {
      revision: claimed.assignment.revision + 1, technician: lab.techB.id,
      accepted: true, accepted_by: lab.techB.id, can_write_followup: true,
      can_claim: false, can_takeover: false,
    } });
    await expect(bDialog.locator('.request-assignment-summary')).toContainText('Benoît Laboratoire');
    await expect(bDialog.locator('.request-assignment-summary')).toContainText('Prise en charge confirmée');

    // A still has an open form and an older visit. Neither authorizes a stale write.
    const refused = techA.waitForResponse(result =>
      new URL(result.url()).pathname === `/api/requests/${lab.record.id}/followup/` && result.request().method() === 'POST');
    await aDialog.getByRole('button', { name: 'Enregistrer le suivi', exact: true }).click();
    expect([403, 409]).toContain((await refused).status());
    expect((await response(techA, `interventions/${visit.id}/`, 'PATCH', { work_done: lostDraft })).status()).toBe(403);
    expect((await response(techA, `requests/${lab.record.id}/timeline/`, 'POST', { kind: 'observation', observation: lostDraft })).status()).toBe(403);
    expect((await response(techA, `requests/${lab.record.id}/assignment/claim/`, 'POST', {
      expected_revision: claimed.assignment.revision,
    })).status()).toBe(409);
    // B owns the dossier, while A remains the author of A's visit.
    expect((await response(techB, `interventions/${visit.id}/`, 'PATCH', { work_done: 'Écrasement de l’ancien auteur' })).status()).toBe(403);
    const noteB = `${lab.tag} essais repris et consignés par Benoît`;
    await followup(techB, bDialog, lab, 'testing', noteB, `${lab.tag} synthèse interne de Benoît`);
    const preservedVisit = await api(page, `interventions/${visit.id}/`);
    expect(preservedVisit).toEqual(visit);
    const history = await api(page, `requests/${lab.record.id}/timeline/`);
    expect(history.find(event => event.id === earlierNote.id)).toEqual(earlierNote);
    expect(history.some(event => event.kind === 'assignment_changed' && event.observation === reason && event.is_internal)).toBe(true);
    expect(history.some(event => event.kind === 'assignment_taken_over' && event.actor_name === 'Benoît Laboratoire' && event.is_internal)).toBe(true);
    expect(history.some(event => event.observation === noteB && event.actor_name === 'Benoît Laboratoire' && event.is_internal)).toBe(true);
    expect(JSON.stringify(history)).not.toContain(lostDraft);
    await techA.reload();
    const readOnly = await dossier(techA, lab);
    await expect(readOnly.locator('.sav-followup-readonly')).toBeVisible();
    await expect(readOnly.getByRole('button', { name: 'Enregistrer le suivi', exact: true })).toHaveCount(0);

    await login(client, lab.portal.username, true);
    await client.getByRole('navigation', { name: 'Navigation principale', exact: true }).getByText('Demandes SAV', { exact: true }).click();
    const publicDialog = await dossier(client, lab);
    await expect(publicDialog).toContainText('En test');
    await expect(publicDialog.getByRole('button', { name: 'Prendre le relais', exact: true })).toHaveCount(0);
    const publicRecord = await api(client, `requests/${lab.record.id}/`);
    expect(publicRecord).not.toHaveProperty('assignment');
    const publicHistory = await api(client, `requests/${lab.record.id}/timeline/`);
    for (const privateText of [reason, noteA, noteB, lostDraft]) {
      await expect(publicDialog).not.toContainText(privateText);
      expect(JSON.stringify(publicHistory)).not.toContain(privateText);
    }
    expect(publicHistory.every(event => !event.is_internal && !event.kind.startsWith('assignment_'))).toBe(true);
    expect(publicHistory.some(event => event.kind === 'status_changed' && event.status_after === 'testing')).toBe(true);
  } finally {
    await Promise.all([contextA.close(), contextB.close(), clientContext.close()]);
  }
});
