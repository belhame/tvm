import { test, expect } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const password = process.env.TVM_DEMO_PASSWORD;

async function login(page, username = 'admin') {
  if (!password) throw new Error('TVM_DEMO_PASSWORD requis ; utiliser bash scripts/e2e.sh.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = page.waitForResponse(result => result.url().endsWith('/api/dashboard/') && result.ok());
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  await expect(page.locator('.metric-value').first()).toContainText(/\d/);
}

async function response(page, path, method = 'GET', data) {
  const { csrfToken } = await (await page.request.get('/api/session/')).json();
  return page.request.fetch(`/api/${path}`, { method, data, headers: { 'X-CSRFToken': csrfToken } });
}

async function api(page, path, method = 'GET', data) {
  const result = await response(page, path, method, data);
  expect(result.ok(), `${method} ${path} → ${result.status()}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

async function reload(page) {
  const loaded = page.waitForResponse(result => result.url().endsWith('/api/dashboard/') && result.ok());
  await page.reload();
  await loaded;
}

async function navigate(page, text) {
  const navigation = page.getByRole('navigation', { name: 'Navigation principale' });
  if (!await navigation.isVisible()) await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await navigation.getByText(text, { exact: true }).click();
}

async function searchRequests(page, query, expected) {
  await navigate(page, 'Demandes SAV');
  const categories = page.getByRole('group', { name: 'Catégories des demandes SAV', exact: true });
  await categories.getByRole('button', { name: /^Tous/ }).click();
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(query);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  const open = page.locator('.request-workspace').getByRole('button', { name: /^Ouvrir / });
  await expect.poll(async () => open.evaluateAll(nodes => nodes.map(node => node.getAttribute('aria-label')).sort())).toEqual(
    expected.map(record => `Ouvrir ${record.reference}`).sort(),
  );
  for (const record of expected) {
    const row = page.locator('.request-workspace tbody tr').filter({ has: page.getByRole('button', { name: `Ouvrir ${record.reference}`, exact: true }) });
    await expect(row).toContainText(record.reference);
    await expect(row).toContainText(record.client_reference);
  }
}

async function globalSearch(page, query) {
  await page.getByRole('textbox', { name: 'Recherche globale', exact: true }).fill(query);
  await page.getByRole('textbox', { name: 'Recherche globale', exact: true }).press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Recherche globale', exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.loading-state')).toHaveCount(0);
  return dialog;
}

function pdfText(bytes) {
  const extracted = spawnSync('pdftotext', ['-', '-'], { input: bytes, encoding: 'utf8', timeout: 10000, maxBuffer: 4 * 1024 * 1024 });
  if (!extracted.error) {
    expect(extracted.status, extracted.stderr).toBe(0);
    return extracted.stdout;
  }
  if (extracted.error.code !== 'ENOENT') throw extracted.error;
  // The application already pins pypdf; this fallback needs no optional test dependency.
  const python = process.env.TVM_E2E_PYTHON || fileURLToPath(new URL('../../.venv/bin/python', import.meta.url));
  const fallback = spawnSync(python, ['-c', 'import io,sys; from pypdf import PdfReader; print("\\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(sys.stdin.buffer.read())).pages))'], {
    input: bytes, encoding: 'utf8', timeout: 10000, maxBuffer: 4 * 1024 * 1024,
  });
  if (fallback.error) throw fallback.error;
  expect(fallback.status, fallback.stderr).toBe(0);
  return fallback.stdout;
}

async function assertPdf(page, path, values, forbidden = []) {
  const result = await page.request.get(`/api/${path}`);
  expect(result.status()).toBe(200);
  expect(result.headers()['content-type']).toContain('application/pdf');
  expect(result.headers()['cache-control']).toContain('no-store');
  const bytes = await result.body();
  expect(bytes.subarray(0, 5).toString()).toBe('%PDF-');
  const text = pdfText(bytes);
  for (const value of values) expect(text).toContain(value);
  for (const value of forbidden) expect(text).not.toContain(value);
}

async function twoCentres(page) {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const marker = `Recherche-numero-${suffix}`;
  // This is deliberately text: zeros and dashes must survive every layer.
  const external = `000042-00-A-${suffix}`;
  const first = await api(page, 'clients/', 'POST', { name: `Centre Alpha ${marker}` });
  const second = await api(page, 'clients/', 'POST', { name: `Centre Bêta ${marker}` });
  const equipmentA = await api(page, 'equipment/', 'POST', { client: first.id, serial_number: `${marker}-A`, model: 'Onduleur fictif centre Alpha' });
  const equipmentB = await api(page, 'equipment/', 'POST', { client: second.id, serial_number: `${marker}-B`, model: 'Onduleur fictif centre Bêta' });
  const requestA = await api(page, 'requests/', 'POST', { equipment: equipmentA.id, subject: `Dossier Alpha ${marker}`, client_reference: external });
  const requestB = await api(page, 'requests/', 'POST', { equipment: equipmentB.id, subject: `Dossier Bêta ${marker}`, client_reference: external });
  const visitA = await api(page, 'interventions/', 'POST', { service_request: requestA.id, diagnosis: 'Premier diagnostic fictif Alpha.', work_done: 'Première visite de contrôle.', internal_notes: `INTERNE-ALPHA-${suffix}` });
  const visitA2 = await api(page, 'interventions/', 'POST', { service_request: requestA.id, diagnosis: 'Deuxième diagnostic fictif Alpha.', work_done: 'Deuxième visite de contrôle.' });
  const visitB = await api(page, 'interventions/', 'POST', { service_request: requestB.id, diagnosis: 'Diagnostic fictif Bêta.', work_done: 'Visite réservée au centre Bêta.', internal_notes: `INTERNE-BETA-${suffix}` });
  const usernameA = `numero-alpha-${suffix}`;
  const usernameB = `numero-beta-${suffix}`;
  await api(page, 'users/', 'POST', { username: usernameA, first_name: 'Client', last_name: 'Alpha', role: 'client', client: first.id, password });
  await api(page, 'users/', 'POST', { username: usernameB, first_name: 'Client', last_name: 'Bêta', role: 'client', client: second.id, password });
  return { marker, external, first, second, equipmentA, equipmentB, requestA, requestB, visitA, visitA2, visitB, usernameA, usernameB, suffix };
}

test('le personnel recherche les deux numéros et plusieurs visites gardent un seul appel TVM non forgeable', async ({ page }) => {
  test.setTimeout(180000);
  await login(page);
  const data = await twoCentres(page);
  const { requestA, requestB, visitA, visitA2, visitB, external } = data;
  expect(requestA.reference).toMatch(/^\d{2}-\d{5}$/);
  expect(requestB.reference).toMatch(/^\d{2}-\d{5}$/);
  expect(requestA.reference).not.toBe(requestB.reference);
  expect(requestA.call_number).toBe(requestA.reference);
  expect(requestB.call_number).toBe(requestB.reference);
  expect(requestA.client_reference).toBe(external);
  expect(requestB.client_reference).toBe(external);
  expect(visitA.call_number).toBe(requestA.reference);
  expect(visitA2.call_number).toBe(requestA.reference);
  expect(visitA.client_reference).toBe(external);
  expect(visitA.reference).toMatch(/^INT-/);
  expect(visitA2.reference).toMatch(/^INT-/);
  expect(visitA.reference).not.toBe(visitA2.reference);

  const forged = await response(page, `requests/${requestA.id}/`, 'PATCH', { reference: '99-99999', call_number: '99-99999' });
  expect([200, 400]).toContain(forged.status());
  expect((await api(page, `requests/${requestA.id}/`)).reference).toBe(requestA.reference);
  const forgedVisit = await response(page, `interventions/${visitA.id}/`, 'PATCH', { reference: 'INT-FORGED', call_number: '99-99999', client_reference: '000-OTHER' });
  expect([200, 400]).toContain(forgedVisit.status());
  const sameVisit = await api(page, `interventions/${visitA.id}/`);
  expect(sameVisit.reference).toBe(visitA.reference);
  expect(sameVisit.call_number).toBe(requestA.reference);
  expect(sameVisit.client_reference).toBe(external);
  const attemptedCreate = await response(page, 'requests/', 'POST', {
    equipment: data.equipmentA.id, subject: 'Tentative de numéro imposé', reference: '00-00000', call_number: '00-00000',
  });
  expect([201, 400]).toContain(attemptedCreate.status());
  if (attemptedCreate.status() === 201) {
    const allocated = await attemptedCreate.json();
    expect(allocated.reference).toMatch(/^\d{2}-\d{5}$/);
    expect(allocated.reference).not.toBe('00-00000');
    expect(allocated.call_number).toBe(allocated.reference);
  }

  expect((await api(page, `requests/?client_reference=${encodeURIComponent(external)}`)).map(row => row.id).sort()).toEqual([requestA.id, requestB.id].sort());
  expect((await api(page, `requests/?call_number=${requestA.reference}`)).map(row => row.id)).toEqual([requestA.id]);
  expect((await api(page, `interventions/?call_number=${requestA.reference}`)).map(row => row.id).sort()).toEqual([visitA.id, visitA2.id].sort());
  expect((await api(page, `interventions/?client_reference=${encodeURIComponent(external)}`)).map(row => row.id).sort()).toEqual([visitA.id, visitA2.id, visitB.id].sort());
  await reload(page);
  await searchRequests(page, external, [requestA, requestB]);
  await searchRequests(page, requestA.reference, [requestA]);
  let global = await globalSearch(page, external);
  await expect(global).toContainText(requestA.reference);
  await expect(global).toContainText(requestB.reference);
  await expect(global).toContainText(external);
  await global.getByRole('button', { name: 'Fermer', exact: true }).first().click();

  global = await globalSearch(page, requestA.reference);
  const interventionResults = global.locator('.search-results').filter({ has: page.getByRole('heading', { name: 'Interventions', exact: true }) });
  await expect(interventionResults.getByRole('button')).toHaveCount(2);
  await interventionResults.getByRole('button').filter({ hasText: visitA.reference }).click();
  const detail = page.getByRole('dialog', { name: 'Détail de l’intervention', exact: true });
  await expect(detail.locator('.detail-reference')).toContainText(requestA.reference);
  await expect(detail).toContainText(external);
  await expect(detail).toContainText(visitA.reference);
  await expect(detail).not.toContainText(requestB.reference);
  await assertPdf(page, `interventions/${visitA.id}/report/`, [requestA.reference, external, visitA.reference], [`INTERNE-ALPHA-${data.suffix}`, requestB.reference]);
  await assertPdf(page, `interventions/${visitA2.id}/report/`, [requestA.reference, external, visitA2.reference]);
  await assertPdf(page, `requests/${requestA.id}/report/`, [requestA.reference, external]);
});

test('deux centres partagent une référence externe sans partager leurs dossiers, recherches, visites ou PDF', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const data = await twoCentres(page);
  const contextA = await browser.newContext();
  const contextB = await browser.newContext();
  const clientA = await contextA.newPage();
  const clientB = await contextB.newPage();
  try {
    await login(clientA, data.usernameA);
    await login(clientB, data.usernameB);
    for (const entry of [
      { page: clientA, own: data.requestA, other: data.requestB, visits: [data.visitA, data.visitA2], foreignVisits: [data.visitB] },
      { page: clientB, own: data.requestB, other: data.requestA, visits: [data.visitB], foreignVisits: [data.visitA, data.visitA2] },
    ]) {
      const actor = entry.page;
      const listed = await api(actor, `requests/?q=${encodeURIComponent(data.external)}`);
      expect(listed.map(row => row.id)).toEqual([entry.own.id]);
      expect(listed[0].client_reference).toBe(data.external);
      expect((await api(actor, `requests/?call_number=${entry.other.reference}`))).toEqual([]);
      expect((await api(actor, `requests/?client_reference=${encodeURIComponent(data.external)}&call_number=${entry.other.reference}`))).toEqual([]);
      expect((await api(actor, `interventions/?q=${encodeURIComponent(data.external)}`)).map(row => row.id).sort()).toEqual(entry.visits.map(visit => visit.id).sort());
      const global = await api(actor, `search/?q=${encodeURIComponent(data.external)}`);
      expect(global.requests.map(row => row.id)).toEqual([entry.own.id]);
      expect(global.interventions.map(row => row.id).sort()).toEqual(entry.visits.map(visit => visit.id).sort());
      expect(JSON.stringify(global)).not.toContain(entry.other.reference);
      expect(JSON.stringify(global)).not.toContain('INTERNE-');
      const otherSearch = await api(actor, `search/?q=${entry.other.reference}`);
      expect(otherSearch.requests).toEqual([]);
      expect(otherSearch.interventions).toEqual([]);
      expect((await actor.request.get(`/api/requests/${entry.other.id}/`)).status()).toBe(404);
      expect((await actor.request.get(`/api/requests/${entry.other.id}/report/`)).status()).toBe(404);
      expect((await response(actor, `requests/${entry.own.id}/`, 'PATCH', { client_reference: 'NOUVELLE-REF', reference: '99-99999' })).status()).toBe(403);
      for (const foreign of entry.foreignVisits) {
        expect((await actor.request.get(`/api/interventions/${foreign.id}/`)).status()).toBe(404);
        expect((await actor.request.get(`/api/interventions/${foreign.id}/report/`)).status()).toBe(404);
      }
      await searchRequests(actor, data.external, [entry.own]);
      await searchRequests(actor, entry.own.reference, [entry.own]);
      await actor.getByRole('button', { name: `Ouvrir ${entry.own.reference}`, exact: true }).click();
      const dossier = actor.getByRole('dialog', { name: 'Dossier SAV', exact: true });
      await expect(dossier).toContainText(entry.own.reference);
      await expect(dossier).toContainText(data.external);
      await expect(dossier).not.toContainText(entry.other.reference);
      await dossier.getByRole('tab', { name: /^Maintenance/ }).click();
      for (const visit of entry.visits) await expect(dossier).toContainText(visit.reference);
      await dossier.getByRole('button', { name: 'Fermer', exact: true }).first().click();
      const found = await globalSearch(actor, entry.own.reference);
      await expect(found).toContainText(entry.own.reference);
      await expect(found).toContainText(data.external);
      await expect(found).not.toContainText(entry.other.reference);
      const visitResults = found.locator('.search-results').filter({ has: actor.getByRole('heading', { name: 'Interventions', exact: true }) });
      await expect(visitResults.getByRole('button')).toHaveCount(entry.visits.length);
      await visitResults.getByRole('button').filter({ hasText: entry.visits[0].reference }).click();
      const detail = actor.getByRole('dialog', { name: 'Détail de l’intervention', exact: true });
      await expect(detail.locator('.detail-reference')).toContainText(entry.own.reference);
      await expect(detail).toContainText(data.external);
      await expect(detail).not.toContainText(entry.other.reference);
      await expect(detail).not.toContainText('INTERNE-');
      await detail.getByRole('button', { name: 'Fermer', exact: true }).first().click();
      for (const visit of entry.visits) await assertPdf(actor, `interventions/${visit.id}/report/`, [entry.own.reference, data.external, visit.reference], [entry.other.reference, 'INTERNE-']);
      await assertPdf(actor, `requests/${entry.own.id}/report/`, [entry.own.reference, data.external], [entry.other.reference, 'INTERNE-']);
    }
  } finally {
    await contextA.close();
    await contextB.close();
  }
});
