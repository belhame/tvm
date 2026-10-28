import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { openRequestsWorkspace } from './legacy_navigation.js';

const password = process.env.TVM_DEMO_PASSWORD;
const intakePath = 'logistics/sav-intake/';
const marker = () => `SIMPLE-${Date.now()}-${Math.random().toString(36).slice(2, 7).toUpperCase()}`;

async function login(page, username = 'admin', role = 'internal') {
  if (!password) throw new Error('Utiliser bash scripts/e2e.sh avec le mot de passe local privé.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  await page.getByRole('button', { name: /Se connecter/i }).click();
  if (role === 'courier') {
    await expect(page.getByRole('navigation', { name: 'Navigation livreur', exact: true })).toBeVisible();
  } else {
    await expect(page.getByRole('heading', { name: 'Tableau de bord', exact: true })).toBeVisible();
  }
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
  const company = await api(page, 'clients/', 'POST', { name: `001 Laboratoire SAV fictif ${tag}` });
  const other = await api(page, 'clients/', 'POST', { name: `001 Autre centre fictif ${tag}` });
  const technician = await api(page, 'users/', 'POST', {
    username: `simple-tech-${tag}`, first_name: 'Technicien de laboratoire', role: 'technician', password,
  });
  const driver = await api(page, 'users/', 'POST', {
    username: `simple-driver-${tag}`, first_name: '001 Livreur de laboratoire', role: 'courier', password,
  });
  const portal = await api(page, 'users/', 'POST', {
    username: `simple-portal-${tag}`, role: 'client', client: company.id, password,
  });
  return { tag, company, other, technician, driver, portal };
}

async function openIntake(page) {
  await page.getByRole('button', { name: 'Nouvelle demande SAV', exact: true }).first().click();
  const dialog = page.getByRole('dialog', { name: 'Nouvelle demande SAV', exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel('Client', { exact: true })).toBeEnabled();
  return dialog;
}

async function fillMinimum(dialog, lab, serial, { courier = false } = {}) {
  await dialog.getByLabel('Client', { exact: true }).selectOption(String(lab.company.id));
  await dialog.getByLabel('Numéro de série', { exact: true }).fill(serial);
  if (!courier) await dialog.getByLabel('Livreur', { exact: true }).selectOption(String(lab.driver.id));
}

async function lookup(page, dialog) {
  const loaded = page.waitForResponse(result =>
    new URL(result.url()).pathname === `/api/${intakePath}lookup/` && result.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Rechercher le modèle et la garantie', exact: true }).click();
  const result = await loaded;
  expect(result.status(), await result.text()).toBe(200);
  return result.json();
}

async function save(page, dialog) {
  const saved = page.waitForResponse(result =>
    new URL(result.url()).pathname === `/api/${intakePath}create/` && result.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
  const result = await saved;
  expect(result.status(), await result.text()).toBe(201);
  const data = await result.json();
  await expect(dialog.getByRole('group', { name: 'Demande SAV enregistrée', exact: true })).toContainText(data.request.call_number);
  await expect(dialog.getByRole('button', { name: 'Terminer', exact: true })).toBeVisible();
  return { result, data, payload: result.request().postDataJSON() };
}

function assertServerTimestamp(value, before, after = Date.now()) {
  const recorded = Date.parse(value);
  expect(Number.isNaN(recorded)).toBe(false);
  expect(recorded).toBeGreaterThanOrEqual(before - 1000);
  expect(recorded).toBeLessThanOrEqual(after + 1000);
}

function dateOffset(days) {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

function durableRequest(record) {
  // The elapsed-time display is recomputed on every read; the stored dossier
  // fields, including its original arrival and update timestamp, must remain.
  const { timing, ...stored } = record;
  return stored;
}

test('le tableau de bord ouvre en premier et le technicien reçoit un modèle inconnu avec seulement client, série et livreur', async ({ page, browser }) => {
  await login(page);
  const navigation = page.getByRole('navigation', { name: 'Navigation principale', exact: true });
  expect((await navigation.getByRole('button').allTextContents())[0]).toContain('Tableau de bord');
  await expect(page.locator('.metric-value').first()).toContainText(/\d/);
  const lab = await laboratory(page);
  const context = await browser.newContext();
  const tech = await context.newPage();
  try {
    await login(tech, lab.technician.username);
    await expect(tech.getByRole('heading', { name: 'Tableau de bord', exact: true })).toBeVisible();
    const dialog = await openIntake(tech);
    await expect(dialog.getByRole('button', { name: 'Options avancées', exact: true })).toHaveCount(0);
    const serial = `SN-${lab.tag}-INCONNU`;
    await fillMinimum(dialog, lab, serial);
    const forged = await response(tech, `${intakePath}create/`, 'POST', {
      request_key: randomUUID(), client: lab.company.id, serial_number: serial,
      arrival_courier: lab.driver.id, arrived_at: '2000-01-01T00:00:00Z', status: 'closed', warranty_status: 'warranty',
    });
    expect(forged.status()).toBe(400);
    expect(await api(page, `equipment/?serial=${encodeURIComponent(serial)}`)).toEqual([]);
    await dialog.getByLabel('N° d’appel client (facultatif)', { exact: true }).fill('');
    await dialog.getByLabel('Description (facultative)', { exact: true }).fill('');
    await expect(dialog.getByRole('button', { name: 'Enregistrer', exact: true })).toBeEnabled();
    let searches = 0;
    const observeLookup = request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === `/api/${intakePath}lookup/`) searches += 1;
    };
    tech.on('request', observeLookup);
    const before = Date.now();
    const saved = await save(tech, dialog);
    tech.off('request', observeLookup);
    expect(searches).toBe(0);
    expect(saved.data).toMatchObject({ created: true, request: {
      status: 'new', client_reference: '', return_flag: false, arrival_courier: { id: lab.driver.id },
    }, coverage: { status: 'unknown', warranty_status: 'quotation', provisional: true } });
    const coverage = dialog.getByRole('region', { name: 'Garantie et orientation du dossier', exact: true });
    await expect(coverage).toContainText('Garantie à vérifier');
    await expect(coverage).toContainText('Devis / facturable provisoire');
    await expect(dialog.getByRole('region', { name: 'Équipement retrouvé', exact: true })).toContainText('Modèle non identifié');
    assertServerTimestamp(saved.data.request.arrived_at, before);
    const record = await api(page, `requests/${saved.data.request.id}/`);
    expect(record).toMatchObject({ equipment: saved.data.equipment.id, status: 'new', assigned_technician: null, warranty_status: 'quotation' });
    expect(record.assignment).toMatchObject({ revision: 0, accepted: false });
    expect(Date.parse(record.arrived_at)).toBe(Date.parse(saved.data.request.arrived_at));
    expect(record.disposition).toMatchObject({ outcome: 'pending', quote: null, price_ht: null, vat_rate: null,
      requires_diagnostic_billing: false, finance_validated_at: null, invoice_reference: '', invoiced_on: null });
    const replay = await response(tech, `${intakePath}create/`, 'POST', saved.payload);
    expect(replay.status()).toBe(200);
    expect(await replay.json()).toMatchObject({ created: false, request: {
      id: saved.data.request.id, arrived_at: saved.data.request.arrived_at,
    } });
    const rows = await api(page, `requests/?q=${encodeURIComponent(serial)}`);
    expect(rows.filter(row => row.equipment === saved.data.equipment.id)).toHaveLength(1);
    const changed = await response(tech, `${intakePath}create/`, 'POST', { ...saved.payload, description: 'Contenu différent avec la même clé' });
    expect([400, 409]).toContain(changed.status());
    const duplicate = await response(tech, `${intakePath}create/`, 'POST', { ...saved.payload, request_key: randomUUID() });
    expect(duplicate.status()).toBe(409);
    expect((await duplicate.json()).open_request.id).toBe(saved.data.request.id);
    expect(durableRequest(await api(page, `requests/${saved.data.request.id}/`))).toEqual(durableRequest(record));
    await dialog.getByRole('button', { name: 'Terminer', exact: true }).click();
    await expect(dialog).toHaveCount(0);
  } finally {
    await context.close();
  }
});

test('un retour connu affiche la garantie active et les anciennes références exactes sans confondre un autre centre', async ({ page }) => {
  await login(page);
  const lab = await laboratory(page);
  const serial = `SN-${lab.tag}-RETOUR`;
  const unit = await api(page, 'equipment/', 'POST', { client: lab.company.id, serial_number: serial, model: 'Modèle fictif déjà identifié' });
  await api(page, 'warranties/', 'POST', {
    equipment: unit.id, starts_on: dateOffset(-60), ends_on: dateOffset(365), scope: 'electronics_and_batteries', provider: 'Laboratoire fictif',
  });
  const old = await api(page, 'requests/', 'POST', {
    equipment: unit.id, subject: `Ancien appel fictif ${lab.tag}`, status: 'closed', client_reference: `000-RETOUR-${lab.tag}`,
  });
  const foreignUnit = await api(page, 'equipment/', 'POST', {
    client: lab.other.id, serial_number: `SN-${lab.tag}-AUTRE`, model: 'Modèle fictif étranger',
  });
  const foreign = await api(page, 'requests/', 'POST', {
    equipment: foreignUnit.id, subject: `Appel étranger fictif ${lab.tag}`, status: 'closed', client_reference: old.client_reference,
  });
  await page.reload();
  const dialog = await openIntake(page);
  await fillMinimum(dialog, lab, serial);
  const found = await lookup(page, dialog);
  expect(found.equipment).toMatchObject({ id: unit.id, known: true, model: unit.model });
  expect(found.coverage).toMatchObject({ status: 'active', warranty_status: 'warranty', provisional: false });
  expect(found.return_history.is_return).toBe(true);
  expect(found.return_history.matches).toEqual([expect.objectContaining({
    id: old.id, call_number: old.reference, client_reference: old.client_reference, serial_number: serial, relation: 'same_equipment',
  })]);
  await expect(dialog.getByRole('region', { name: 'Garantie et orientation du dossier', exact: true })).toContainText('Garantie en cours');
  await expect(dialog.getByRole('region', { name: 'Retour SAV identifié', exact: true })).toContainText('RETOUR');
  const history = dialog.getByRole('region', { name: 'Dossiers SAV antérieurs', exact: true });
  await expect(history).toContainText(old.reference);
  await expect(history).toContainText(old.client_reference);
  await expect(history).toContainText(serial);
  await expect(history).not.toContainText(foreign.reference);
  await dialog.getByLabel('N° d’appel client (facultatif)', { exact: true }).fill(`000-NOUVEAU-${lab.tag}`);
  const saved = await save(page, dialog);
  expect(saved.data.request).toMatchObject({ return_flag: true, status: 'new' });
  const record = await api(page, `requests/${saved.data.request.id}/`);
  expect(record).toMatchObject({ equipment: unit.id, assigned_technician: null, warranty_status: 'warranty', return_flag: true });
  expect(durableRequest(await api(page, `requests/${old.id}/`))).toEqual(durableRequest(old));
  expect(durableRequest(await api(page, `requests/${foreign.id}/`))).toEqual(durableRequest(foreign));
  await dialog.getByRole('button', { name: 'Terminer', exact: true }).click();
  await openRequestsWorkspace(page);
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(serial);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  const row = page.locator('tbody tr').filter({ hasText: saved.data.request.call_number });
  await expect(row).toContainText('Retour SAV');
  await expect(row).toContainText('Garantie');
  await row.getByRole('button', { name: `Ouvrir ${saved.data.request.call_number}`, exact: true }).click();
  const details = page.getByRole('dialog', { name: 'Dossier SAV', exact: true });
  await expect(details).toContainText('Retour SAV');
  await expect(details).toContainText(old.reference);
  await expect(details).toContainText(old.client_reference);
  await expect(details).not.toContainText(foreign.reference);
});

test('une garantie expirée oriente vers un devis facturable sans créer de devis PDF ni de facture', async ({ page }) => {
  await login(page);
  const lab = await laboratory(page);
  const serial = `SN-${lab.tag}-EXPIRE`;
  const unit = await api(page, 'equipment/', 'POST', { client: lab.company.id, serial_number: serial, model: 'Modèle fictif hors couverture' });
  await api(page, 'warranties/', 'POST', {
    equipment: unit.id, starts_on: dateOffset(-500), ends_on: dateOffset(-30), scope: 'electronics_and_batteries',
  });
  await page.reload();
  const dialog = await openIntake(page);
  await fillMinimum(dialog, lab, serial);
  const found = await lookup(page, dialog);
  expect(found.coverage).toMatchObject({ status: 'expired', warranty_status: 'quotation', provisional: false });
  const coverage = dialog.getByRole('region', { name: 'Garantie et orientation du dossier', exact: true });
  await expect(coverage).toContainText(/Devis.*facturable/i);
  await expect(coverage).toContainText('ne crée aucun devis PDF ni aucune facture');
  const saved = await save(page, dialog);
  const record = await api(page, `requests/${saved.data.request.id}/`);
  expect(record).toMatchObject({ status: 'new', assigned_technician: null, warranty_status: 'quotation' });
  expect(record.disposition).toMatchObject({ outcome: 'pending', quote: null, price_ht: null, vat_rate: null,
    requires_diagnostic_billing: false, finance_validated_at: null, invoice_reference: '', invoiced_on: null });
  expect(record.exchange).toBeNull();
  expect(record.closed_at).toBeNull();
  const history = await api(page, `requests/${record.id}/timeline/`);
  expect(history.some(event => /billed|invoice|quote_issued|free_approved/.test(event.kind))).toBe(false);
});

test('le livreur TVM est enregistré automatiquement et les séries d’un autre client restent isolées', async ({ page, browser }) => {
  await login(page);
  const lab = await laboratory(page);
  const foreignSerial = `SN-${lab.tag}-PROPRIETAIRE`;
  const unit = await api(page, 'equipment/', 'POST', { client: lab.other.id, serial_number: foreignSerial, model: 'Matériel fictif du second centre' });
  const foreign = await api(page, 'requests/', 'POST', {
    equipment: unit.id, subject: `Dossier privé du second centre ${lab.tag}`, description: `DESCRIPTION-PRIVEE-${lab.tag}`,
  });
  const courierContext = await browser.newContext(), clientContext = await browser.newContext();
  const courier = await courierContext.newPage(), client = await clientContext.newPage();
  try {
    await login(courier, lab.driver.username, 'courier');
    const dialog = await openIntake(courier);
    await expect(dialog.getByLabel('Livreur', { exact: true })).toHaveCount(0);
    await expect(dialog).toContainText('Livreur enregistré');
    await expect(dialog).toContainText('001 Livreur de laboratoire');
    const serial = `SN-${lab.tag}-LIVREUR`;
    await fillMinimum(dialog, lab, serial, { courier: true });
    const before = Date.now();
    const saved = await save(courier, dialog);
    expect(saved.data.request).toMatchObject({ status: 'new', arrival_courier: { id: lab.driver.id } });
    assertServerTimestamp(saved.data.request.arrived_at, before);
    expect(saved.payload).not.toHaveProperty('arrival_courier');
    expect((await api(page, `requests/${saved.data.request.id}/`)).assigned_technician).toBeNull();
    expect((await courier.request.get('/api/requests/')).status()).toBe(403);

    const mismatch = await response(courier, `${intakePath}lookup/`, 'POST', { client: lab.company.id, serial_number: foreignSerial });
    expect(mismatch.status()).toBe(409);
    const mismatchBody = await mismatch.text();
    expect(mismatchBody).not.toContain(foreign.reference);
    expect(mismatchBody).not.toContain(foreign.description);
    expect(mismatchBody).not.toContain(lab.other.name);
    const forged = await response(courier, `${intakePath}create/`, 'POST', {
      request_key: randomUUID(), client: lab.company.id, serial_number: foreignSerial,
    });
    expect(forged.status()).toBe(409);
    expect(durableRequest(await api(page, `requests/${foreign.id}/`))).toEqual(durableRequest(foreign));

    await login(client, lab.portal.username, 'client');
    await expect(client.getByRole('button', { name: 'Nouvelle demande SAV', exact: true })).toHaveCount(0);
    for (const [path, method, body] of [
      [`${intakePath}options/`, 'GET'],
      [`${intakePath}lookup/`, 'POST', { client: lab.other.id, serial_number: foreignSerial }],
      [`${intakePath}create/`, 'POST', { request_key: randomUUID(), client: lab.other.id, serial_number: foreignSerial }],
    ]) {
      expect((await response(client, path, method, body)).status()).toBe(403);
    }
    expect((await client.request.get(`/api/requests/${foreign.id}/`)).status()).toBe(404);
  } finally {
    await Promise.all([courierContext.close(), clientContext.close()]);
  }
});
