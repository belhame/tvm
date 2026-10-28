import { test, expect } from '@playwright/test';
import { confirmCurrentAssignment, openLegacyDashboard } from './legacy_navigation.js';

const password = process.env.TVM_DEMO_PASSWORD;

async function login(page, username = 'admin') {
  if (!password) throw new Error('TVM_DEMO_PASSWORD requis ; utiliser bash scripts/e2e.sh.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = page.waitForResponse(result => result.url().endsWith('/api/dashboard/') && result.ok());
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  await openLegacyDashboard(page);
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

async function navigate(page, label) {
  const navigation = page.getByRole('navigation', { name: 'Navigation principale' });
  if (!await navigation.isVisible()) await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await navigation.getByText(label, { exact: true }).click();
}

async function reload(page) {
  const loaded = page.waitForResponse(result => result.url().endsWith('/api/dashboard/') && result.ok());
  await page.reload();
  await loaded;
  await openLegacyDashboard(page);
}

function marker(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}


function exchangePath(record, action = '') {
  return `requests/${record.id}/exchange/${action ? `${action}/` : ''}`;
}

async function fixture(page, tag, assignedTechnician = null) {
  const company = await api(page, 'clients/', 'POST', { name: `Laboratoire échange fictif ${tag}` });
  const equipment = await api(page, 'equipment/', 'POST', {
    client: company.id, serial_number: `${tag}-ORIGINE`, model: 'Onduleur d’origine fictif', brand: 'Eaton',
  });
  const request = await api(page, 'requests/', 'POST', {
    equipment: equipment.id, subject: `Échange de validation fictif ${tag}`,
    client_reference: `000-CLIENT-${tag}`, status: 'exchange',
    ...(assignedTechnician ? { assigned_technician: assignedTechnician } : {}),
  });
  return { company, equipment, request };
}

async function openExchange(page, record, billing = false) {
  await navigate(page, billing ? 'Échanges à facturer' : 'Échange');
  await expect(page.getByRole('heading', { name: billing ? 'Échanges à facturer' : 'Échanges d’onduleurs', exact: true })).toBeVisible();
  await page.getByLabel(billing ? 'Rechercher un échange à facturer' : 'Rechercher un échange', { exact: true }).fill(record.reference);
  const action = billing
    ? page.getByRole('button', { name: `Ouvrir l’échange ${record.reference}`, exact: true })
    : page.getByRole('button', { name: `Préparer ${record.reference}`, exact: true })
      .or(page.getByRole('button', { name: `Ouvrir l’échange ${record.reference}`, exact: true }));
  await action.click();
  const dialog = page.getByRole('dialog', { name: 'Préparer et suivre l’échange', exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function openRequestExchange(page, record) {
  await navigate(page, 'Demandes SAV');
  await page.getByRole('group', { name: 'Catégories des demandes SAV', exact: true }).getByRole('button', { name: /^Tous/ }).click();
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(record.reference);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  await page.getByRole('button', { name: `Ouvrir ${record.reference}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Dossier SAV', exact: true });
  await dialog.getByRole('tab', { name: /^Échange/ }).click();
  return dialog;
}

function mutationResponse(page, record, action, method = 'POST') {
  return page.waitForResponse(result => result.url().endsWith(`/api/${exchangePath(record, action)}`) && result.request().method() === method);
}

async function expectMutation(pending) {
  const result = await pending;
  expect(result.status(), await result.text()).toBe(200);
  return result.json();
}

test('un dossier Échange sans visite combine validation et prêt à livrer puis distingue facturation et clôture', async ({ page }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('Echange-parcours-fictif');
  const data = await fixture(page, tag);
  const record = data.request;
  const initial = await api(page, exchangePath(record));
  expect(initial).toMatchObject({ status: 'exchange', exchange: { state: 'awaiting_preparation', is_validated: false, is_ready: false, is_invoiced: false } });
  expect(await api(page, `interventions/?call_number=${encodeURIComponent(record.reference)}`)).toEqual([]);
  await reload(page);
  await navigate(page, 'Échange');
  await page.getByLabel('Rechercher un échange', { exact: true }).fill(record.reference);
  await expect(page.getByRole('button', { name: `Préparer ${record.reference}`, exact: true })).toBeVisible();

  // A draft is allowed to be incomplete. Validation, not its mere existence,
  // must reject a missing replacement serial and leave equipment untouched.
  const incomplete = await api(page, exchangePath(record), 'PATCH', { replacement_serial_number: '', replacement_model: 'Modèle fictif à préciser' });
  expect(incomplete.exchange.state).toBe('pending_validation');
  expect((await response(page, exchangePath(record, 'validate'), 'POST', {})).status()).toBe(400);
  expect((await api(page, exchangePath(record))).exchange.is_validated).toBe(false);
  expect((await api(page, `equipment/?client=${data.company.id}`)).map(item => item.id)).toEqual([data.equipment.id]);

  await reload(page);
  let dialog = await openExchange(page, record);
  await dialog.getByRole('button', { name: 'Préparer l’échange', exact: true }).click();
  await dialog.getByRole('textbox', { name: 'Numéro de série du remplacement', exact: true }).fill(`${tag}-REMPLACEMENT`);
  await dialog.getByRole('textbox', { name: 'Modèle du remplacement', exact: true }).fill('Modèle de remplacement fictif');
  await dialog.getByLabel('Marque du remplacement', { exact: true }).fill('Eaton');
  const preparedResponse = mutationResponse(page, record, '', 'PATCH');
  await dialog.getByRole('button', { name: 'Enregistrer la préparation', exact: true }).click();
  const prepared = await expectMutation(preparedResponse);
  expect(prepared.exchange).toMatchObject({ state: 'pending_validation', replacement_serial_number: `${tag}-REMPLACEMENT`, is_validated: false, is_ready: false, is_invoiced: false });
  expect((await api(page, `equipment/?client=${data.company.id}`))).toHaveLength(1);

  await dialog.getByRole('checkbox', { name: 'Je confirme le numéro de série et le modèle du matériel de remplacement.', exact: true }).check();
  const validatedResponse = mutationResponse(page, record, 'validate');
  await dialog.getByRole('button', { name: 'Valider et mettre prêt à livrer', exact: true }).click();
  const validated = await expectMutation(validatedResponse);
  expect(validated).toMatchObject({ status: 'ready_for_delivery', equipment: data.equipment.id, exchange: { state: 'ready_for_delivery', is_validated: true, is_ready: true, is_invoiced: false } });
  expect(validated.exchange.validated_at).not.toBeNull();
  expect(validated.exchange.ready_at).not.toBeNull();
  expect(validated.exchange.replacement_equipment).toEqual(expect.any(Number));
  expect(await api(page, `equipment/${validated.exchange.replacement_equipment}/`)).toMatchObject({ client: data.company.id, serial_number: `${tag}-REMPLACEMENT` });
  expect(await api(page, `equipment/${data.equipment.id}/`)).toMatchObject({ serial_number: `${tag}-ORIGINE` });
  const prematureClose = await response(page, `requests/${record.id}/`, 'PATCH', { status: 'closed' });
  expect([400, 403]).toContain(prematureClose.status());
  expect((await api(page, exchangePath(record))).exchange.state).toBe('ready_for_delivery');

  // The old explicit ready endpoint remains an idempotent replay after the
  // combined action; neither timestamp is regenerated by the replay.
  const ready = await api(page, exchangePath(record, 'ready'), 'POST', {});
  expect(ready).toMatchObject({ status: 'ready_for_delivery', closed_at: null, exchange: { state: 'ready_for_delivery', is_validated: true, is_ready: true, is_invoiced: false } });
  expect(ready.exchange.ready_at).toBe(validated.exchange.ready_at);
  expect(ready.exchange.validated_at).toBe(validated.exchange.validated_at);
  const earlyTimelineClose = await response(page, `requests/${record.id}/timeline/`, 'POST', { kind: 'status_changed', status_after: 'closed', observation: 'Tentative de clôture sans facturation confirmée.' });
  expect([400, 403]).toContain(earlyTimelineClose.status());
  const { as_of: today } = await api(page, 'requests/categories/');
  expect((await response(page, exchangePath(record, 'billing'), 'POST', { invoice_reference: '', invoiced_on: today })).status()).toBe(400);
  expect((await api(page, exchangePath(record))).exchange.is_invoiced).toBe(false);

  await dialog.getByRole('button', { name: 'Fermer', exact: true }).first().click();
  dialog = await openExchange(page, record, true);
  await dialog.getByRole('textbox', { name: 'Référence de facture', exact: true }).fill(`FACTURE-FICTIVE-${tag}`);
  await dialog.getByLabel(/^Date de facture/).fill(today);
  await dialog.getByLabel('Notes internes de facturation', { exact: true }).fill(`NOTE-FINANCE-FICTIVE-${tag}`);
  const invoicedResponse = mutationResponse(page, record, 'billing');
  await dialog.getByRole('button', { name: 'Confirmer la facturation', exact: true }).click();
  const invoiced = await expectMutation(invoicedResponse);
  expect(invoiced).toMatchObject({ status: 'ready_for_delivery', closed_at: null, exchange: { state: 'invoiced', is_invoiced: true, invoice_reference: `FACTURE-FICTIVE-${tag}`, invoiced_on: today } });
  const closedResponse = mutationResponse(page, record, 'close');
  await dialog.getByRole('button', { name: 'Clôturer le dossier', exact: true }).click();
  const closed = await expectMutation(closedResponse);
  expect(closed).toMatchObject({ reference: record.reference, call_number: record.reference, equipment: data.equipment.id, status: 'closed', exchange: { state: 'closed', is_invoiced: true } });
  expect(closed.closed_at).not.toBeNull();
});

test('le technicien prépare sans valider, la finance est habilitée séparément et le portail exclut brouillon et données de facturation', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('Echange-droits-fictif');
  const users = await api(page, 'users/');
  const technician = users.find(user => user.username === 'technicien');
  expect(technician).toBeTruthy();
  const data = await fixture(page, tag, technician.id);
  const other = await fixture(page, `${tag}-AUTRE`);
  const record = data.request;
  const managerUsername = `echange-manager-${Date.now()}`;
  const financeUsername = `echange-finance-${Date.now()}`;
  const clientUsername = `echange-client-${Date.now()}`;
  await api(page, 'users/', 'POST', { username: managerUsername, role: 'manager', can_validate_billing: false, password });
  await api(page, 'users/', 'POST', { username: financeUsername, role: 'manager', can_validate_billing: true, password });
  await api(page, 'users/', 'POST', { username: clientUsername, role: 'client', client: data.company.id, password });
  const technicianContext = await browser.newContext();
  const managerContext = await browser.newContext();
  const financeContext = await browser.newContext();
  const clientContext = await browser.newContext();
  try {
    const worker = await technicianContext.newPage();
    const manager = await managerContext.newPage();
    const finance = await financeContext.newPage();
    const customer = await clientContext.newPage();
    await login(worker, 'technicien');
    await confirmCurrentAssignment(worker, record.id);
    await login(manager, managerUsername);
    await login(finance, financeUsername);
    await login(customer, clientUsername);
    await expect(manager.getByRole('navigation', { name: 'Navigation principale' }).getByText('Échanges à facturer', { exact: true })).toHaveCount(0);
    const replacementSerial = `${tag}-DRAFT-PRIVE`;
    const replacementModel = `Modèle confidentiel fictif ${tag}`;
    const draft = await api(worker, exchangePath(record), 'PATCH', { replacement_serial_number: replacementSerial, replacement_model: replacementModel, replacement_brand: 'Eaton' });
    expect(draft.exchange).toMatchObject({ state: 'pending_validation', can_prepare: true, can_validate: false, can_mark_ready: false, can_validate_billing: false, can_close: false });
    for (const action of ['validate', 'ready', 'billing', 'close']) {
      const result = await response(worker, exchangePath(record, action), 'POST', action === 'billing' ? { invoice_reference: 'INTERDIT-FICTIF', invoiced_on: '2026-01-01' } : {});
      expect(result.status(), `Le technicien ne doit pas exécuter ${action}`).toBe(403);
    }
    expect((await response(worker, exchangePath(other.request), 'PATCH', { replacement_model: 'Tentative hors affectation' })).status()).toBe(403);

    const clientDraft = await api(customer, exchangePath(record));
    expect(clientDraft.exchange).toMatchObject({ state: 'pending_validation', replacement_serial_number: '', replacement_model: '', replacement_brand: '', replacement_equipment: null, validated_at: null, ready_at: null, billing_validated_at: null, is_validated: false, is_ready: false, is_invoiced: false });
    expect(JSON.stringify(clientDraft)).not.toContain(replacementSerial);
    expect(JSON.stringify(clientDraft)).not.toContain(replacementModel);
    for (const key of ['invoice_reference', 'invoiced_on', 'billing_notes', 'validated_by_name', 'ready_by_name', 'billing_validated_by_name'])
      expect(Object.hasOwn(clientDraft.exchange, key)).toBe(false);
    for (const key of ['can_prepare', 'can_validate', 'can_mark_ready', 'can_validate_billing', 'can_close', 'can_reset'])
      expect(clientDraft.exchange[key]).toBe(false);
    expect((await response(customer, exchangePath(other.request))).status()).toBe(404);
    expect((await response(customer, exchangePath(record), 'PATCH', { replacement_serial_number: 'CLIENT-FORGE-FICTIF' })).status()).toBe(403);
    let clientDialog = await openRequestExchange(customer, record);
    await expect(clientDialog.locator('.exchange-public-pending')).toContainText('après validation de l’échange');
    await expect(clientDialog).not.toContainText(replacementSerial);
    await expect(clientDialog).not.toContainText(replacementModel);
    await expect(clientDialog.getByRole('button', { name: 'Valider l’échange', exact: true })).toHaveCount(0);
    await clientDialog.getByRole('button', { name: 'Fermer', exact: true }).first().click();

    const validated = await api(manager, exchangePath(record, 'validate'), 'POST', {});
    expect(validated.exchange).toMatchObject({ state: 'validated', is_validated: true, is_ready: false });
    expect((await api(customer, exchangePath(record))).exchange).toMatchObject({ replacement_serial_number: replacementSerial, replacement_model: replacementModel, is_validated: true, is_ready: false });
    await reload(customer);
    clientDialog = await openRequestExchange(customer, record);
    await expect(clientDialog).toContainText(replacementSerial);
    await expect(clientDialog).toContainText(replacementModel);
    await expect(clientDialog.getByRole('button', { name: 'Prêt à être livré', exact: true })).toHaveCount(0);
    await clientDialog.getByRole('button', { name: 'Fermer', exact: true }).first().click();
    await api(manager, exchangePath(record, 'ready'), 'POST', {});
    const { as_of: today } = await api(page, 'requests/categories/');
    const noFinance = await response(manager, exchangePath(record, 'billing'), 'POST', { invoice_reference: 'INTERDIT-MANAGER-FICTIF', invoiced_on: today });
    expect(noFinance.status()).toBe(403);
    expect((await api(page, exchangePath(record))).exchange).toMatchObject({ state: 'ready_for_delivery', is_invoiced: false });
    const managerSession = await (await manager.request.get('/api/session/')).json();
    const financeSession = await (await finance.request.get('/api/session/')).json();
    expect(managerSession.user.can_validate_billing).toBe(false);
    expect(financeSession.user.can_validate_billing).toBe(true);

    const dialog = await openExchange(finance, record, true);
    const invoice = `FACTURE-PRIVEE-FICTIVE-${tag}`;
    const privateNote = `NOTE-PRIVEE-FICTIVE-${tag}`;
    await dialog.getByRole('textbox', { name: 'Référence de facture', exact: true }).fill(invoice);
    await dialog.getByLabel(/^Date de facture/).fill(today);
    await dialog.getByLabel('Notes internes de facturation', { exact: true }).fill(privateNote);
    const invoicedResponse = mutationResponse(finance, record, 'billing');
    await dialog.getByRole('button', { name: 'Confirmer la facturation', exact: true }).click();
    expect((await expectMutation(invoicedResponse)).exchange.is_invoiced).toBe(true);
    const clientInvoiced = await api(customer, exchangePath(record));
    expect(clientInvoiced.exchange).toMatchObject({ state: 'invoiced', replacement_serial_number: replacementSerial, is_invoiced: true });
    expect(JSON.stringify(clientInvoiced)).not.toContain(invoice);
    expect(JSON.stringify(clientInvoiced)).not.toContain(privateNote);
    for (const key of ['invoice_reference', 'invoiced_on', 'billing_notes'])
      expect(Object.hasOwn(clientInvoiced.exchange, key)).toBe(false);
    expect((await response(customer, exchangePath(record, 'close'), 'POST', {})).status()).toBe(403);
    const closed = await api(manager, exchangePath(record, 'close'), 'POST', {});
    expect(closed).toMatchObject({ status: 'closed', equipment: data.equipment.id, exchange: { state: 'closed' } });
  } finally {
    await technicianContext.close();
    await managerContext.close();
    await financeContext.close();
    await clientContext.close();
  }
});
