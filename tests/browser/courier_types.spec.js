import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';

const password = process.env.TVM_DEMO_PASSWORD;

async function login(page, username = 'admin', courier = false) {
  if (!password) throw new Error('TVM_DEMO_PASSWORD requis ; utiliser bash scripts/e2e.sh.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const path = courier ? '/api/logistics/bootstrap/' : '/api/dashboard/';
  const loaded = page.waitForResponse(result => new URL(result.url()).pathname === path && result.ok());
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  if (courier) await expect(page.getByRole('navigation', { name: 'Navigation livreur', exact: true })).toBeVisible();
  else await expect(page.locator('.metric-value').first()).toContainText(/\d/);
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

async function mutation(pending) {
  const result = await pending;
  expect(result.ok(), `${result.status()}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

function mutationResponse(page, path, method = 'POST') {
  return page.waitForResponse(result => new URL(result.url()).pathname === `/api/${path}` && result.request().method() === method);
}

async function navigate(page, label) {
  const navigation = page.getByRole('navigation', { name: 'Navigation principale' });
  if (!await navigation.isVisible()) await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await navigation.getByText(label, { exact: true }).click();
}

async function courierNavigate(page, label) {
  await page.getByRole('navigation', { name: 'Navigation livreur', exact: true }).getByRole('button', { name: label, exact: true }).click();
}

async function reload(page) {
  const loaded = page.waitForResponse(result => new URL(result.url()).pathname === '/api/dashboard/' && result.ok());
  await page.reload();
  await loaded;
}

function marker(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

async function company(page, tag) {
  return api(page, 'clients/', 'POST', {
    name: `Laboratoire livreurs typés fictif ${tag}`, contact_name: 'Contact fictif du laboratoire',
    address: '27 voie du laboratoire fictif', city: 'Cotonou', phone: '0000000027',
    notes: `NOTE-INTERNE-FICTIVE-${tag}`, tax_id: `000-FISC-${tag}`,
  });
}

async function equipment(page, owner, serial) {
  return api(page, 'equipment/', 'POST', { client: owner.id, serial_number: serial, model: 'Onduleur fictif de contrôle logistique', brand: 'Eaton' });
}

async function courierAccount(page, tag, kind = 'internal', client = null) {
  return api(page, 'users/', 'POST', {
    username: `livreur-type-${tag}`, first_name: kind === 'client' ? 'Livreur client fictif' : 'Livreur TVM fictif',
    role: 'courier', courier_kind: kind, client, password,
  });
}

async function clientAccount(page, owner, tag) {
  return api(page, 'users/', 'POST', { username: `portail-type-${tag}`, role: 'client', client: owner.id, password });
}

async function repairFixture(page, owner, tag) {
  const unit = await equipment(page, owner, `TYPES-REPARATION-${tag}`);
  const request = await api(page, 'requests/', 'POST', {
    equipment: unit.id, subject: `Réparation logistique fictive ${tag}`, status: 'testing', client_reference: `000-CLIENT-${tag}`,
  });
  return { unit, request };
}

async function makeReady(page, request) {
  const { as_of: today } = await api(page, 'requests/categories/');
  return api(page, `requests/${request.id}/disposition/repair/`, 'POST', {
    diagnosis: 'Tests fictifs de fonctionnement réalisés avec succès.', tests_passed: true, tested_on: today,
  });
}

test('le livreur client est rattaché à sa société, reçoit ses missions automatiques et ne peut jamais réceptionner au SAV', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('externe-fictif');
  const owner = await company(page, `${tag}-A`);
  const foreignOwner = await company(page, `${tag}-B`);
  const internal = await courierAccount(page, `${tag}-TVM`);
  const external = await courierAccount(page, `${tag}-CLIENT`, 'client', owner.id);
  const sameCompanyOther = await courierAccount(page, `${tag}-AUTRE`, 'client', owner.id);
  const foreignExternal = await courierAccount(page, `${tag}-ETRANGER`, 'client', foreignOwner.id);
  expect(external).toMatchObject({ role: 'courier', courier_kind: 'client', client: owner.id });
  expect(internal).toMatchObject({ role: 'courier', courier_kind: 'internal', client: null });
  expect((await response(page, 'users/', 'POST', { username: `sans-societe-${tag}`, role: 'courier', courier_kind: 'client', password })).status()).toBe(400);
  expect((await response(page, 'users/', 'POST', { username: `interne-lie-${tag}`, role: 'courier', courier_kind: 'internal', client: owner.id, password })).status()).toBe(400);
  expect((await response(page, `clients/${owner.id}/`, 'PATCH', { default_courier: foreignExternal.id })).status()).toBe(400);
  expect((await response(page, `clients/${owner.id}/`, 'PATCH', { internal_courier: external.id })).status()).toBe(400);
  await reload(page);
  await navigate(page, 'Clients');
  await page.getByRole('textbox', { name: 'Rechercher un client', exact: true }).fill(owner.name);
  await page.getByRole('button', { name: `Modifier ${owner.name}`, exact: true }).click();
  const clientForm = page.getByRole('dialog', { name: 'Modifier client', exact: true });
  const defaultCourier = clientForm.getByRole('combobox', { name: 'Livreur client par défaut', exact: true });
  const internalCourier = clientForm.getByRole('combobox', { name: 'Référent livreur TVM', exact: true });
  await expect(defaultCourier.locator(`option[value="${external.id}"]`)).toHaveCount(1);
  await expect(defaultCourier.locator(`option[value="${foreignExternal.id}"]`)).toHaveCount(0);
  await expect(defaultCourier.locator(`option[value="${internal.id}"]`)).toHaveCount(0);
  await expect(internalCourier.locator(`option[value="${internal.id}"]`)).toHaveCount(1);
  await expect(internalCourier.locator(`option[value="${external.id}"]`)).toHaveCount(0);
  await defaultCourier.selectOption(String(external.id));
  await internalCourier.selectOption(String(internal.id));
  const savedDefaults = mutationResponse(page, `clients/${owner.id}/`, 'PATCH');
  await clientForm.getByRole('button', { name: 'Enregistrer les modifications', exact: true }).click();
  expect(await mutation(savedDefaults)).toMatchObject({ default_courier: external.id, internal_courier: internal.id });
  await expect(clientForm).toHaveCount(0);
  await api(page, `clients/${foreignOwner.id}/`, 'PATCH', { default_courier: foreignExternal.id });
  const data = await repairFixture(page, owner, `${tag}-A`);
  const foreignData = await repairFixture(page, foreignOwner, `${tag}-B`);
  await makeReady(page, data.request);
  await makeReady(page, foreignData.request);
  const missions = await api(page, 'logistics/outbound/');
  const job = missions.find(item => item.service_request === data.request.id);
  const foreignJob = missions.find(item => item.service_request === foreignData.request.id);
  expect(job).toMatchObject({ status: 'assigned', equipment: data.unit.id, assigned_courier: external.id, assigned_courier_kind: 'client', assignment_mode: 'automatic', routing_source: 'default_courier' });
  expect(job.assignment_revision).toBeGreaterThanOrEqual(1);
  expect(foreignJob).toMatchObject({ assigned_courier: foreignExternal.id, assignment_mode: 'automatic', routing_source: 'default_courier' });

  const externalContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const otherContext = await browser.newContext();
  const driver = await externalContext.newPage();
  const otherDriver = await otherContext.newPage();
  try {
    await login(driver, external.username, true);
    const bootstrap = await api(driver, 'logistics/bootstrap/');
    expect(bootstrap.user).toMatchObject({ role: 'courier', courier_kind: 'client', client: owner.id });
    expect(bootstrap.capabilities).toMatchObject({ can_receive: false, can_lookup: false, can_pickups: false });
    expect(bootstrap.clients).toEqual([{ id: owner.id, name: owner.name }]);
    expect(bootstrap.couriers).toEqual([]);
    expect(JSON.stringify(bootstrap)).not.toContain(foreignOwner.name);
    expect(JSON.stringify(bootstrap)).not.toContain(owner.notes);
    expect(JSON.stringify(bootstrap)).not.toContain(owner.tax_id);
    expect((await response(driver, 'logistics/clients/')).status()).toBe(403);
    expect(await api(driver, 'logistics/pickups/')).toEqual([]);
    expect((await response(driver, 'logistics/pickups/', 'POST', {})).status()).toBe(403);
    const allowed = await api(driver, 'logistics/outbound/');
    expect(allowed.map(item => item.id)).toEqual([job.id]);
    expect((await response(driver, `logistics/outbound/${foreignJob.id}/`)).status()).toBe(404);
    expect((await response(driver, 'logistics/lookup/', 'POST', { serial_number: data.unit.serial_number })).status()).toBe(403);
    expect((await response(driver, 'logistics/receive/', 'POST', { request_key: randomUUID(), serial_number: data.unit.serial_number, client: owner.id, source: 'manual' })).status()).toBe(403);
    const { csrfToken } = await (await driver.request.get('/api/session/')).json();
    const photo = await driver.request.post('/api/logistics/recognize-serial/', {
      headers: { 'X-CSRFToken': csrfToken },
      multipart: { file: { name: 'etiquette-fictive.png', mimeType: 'image/png',
        buffer: readFileSync(new URL('../../backend/core/tests/fixtures/serial_barcode_fictif.png', import.meta.url)) } },
    });
    expect(photo.status()).toBe(403);
    expect((await response(driver, 'logistics/dispatch-candidates/')).status()).toBe(403);
    expect((await response(driver, 'dashboard/')).status()).toBe(403);
    await expect(driver.getByRole('navigation', { name: 'Navigation livreur', exact: true }).getByRole('button', { name: 'Réception', exact: true })).toHaveCount(0);
    await expect(driver.getByRole('button', { name: 'Réception atelier', exact: true })).toHaveCount(0);
    await courierNavigate(driver, 'Prêts');
    await expect(driver.locator('.courier-job-card')).toHaveCount(1);
    await expect(driver.locator('.courier-job-card')).toContainText(data.unit.serial_number);
    await expect(driver.locator('.courier-app')).not.toContainText(foreignData.unit.serial_number);
    expect(await driver.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)).toBe(false);
    await driver.getByRole('button', { name: `Confirmer la remise ${job.call_number}`, exact: true }).click();
    const handoff = driver.getByRole('dialog', { name: 'Confirmer la remise au client', exact: true });
    await handoff.getByRole('textbox', { name: 'Nom du destinataire', exact: true }).fill('Destinataire fictif de la société du livreur externe');
    await handoff.getByRole('checkbox', { name: 'Je confirme avoir remis physiquement cet onduleur au destinataire indiqué.', exact: true }).check();
    const recorded = mutationResponse(driver, `logistics/outbound/${job.id}/handoff/`);
    const beforeHandoff = Date.now();
    await handoff.getByRole('button', { name: 'Enregistrer la remise', exact: true }).click();
    const proof = await mutation(recorded);
    expect(proof).toMatchObject({ status: 'completed', assigned_courier: external.id, assigned_courier_kind: 'client', handed_over_by_role: 'courier', recipient_name: 'Destinataire fictif de la société du livreur externe' });
    expect(Date.parse(proof.handed_over_at)).toBeGreaterThanOrEqual(beforeHandoff - 1000);
    expect(Date.parse(proof.handed_over_at)).toBeLessThanOrEqual(Date.now() + 1000);
    await handoff.getByRole('button', { name: 'Fermer', exact: true }).last().click();
    const loaded = driver.waitForResponse(result => new URL(result.url()).pathname === '/api/logistics/bootstrap/' && result.ok());
    await driver.goto('/?verification-livreur=client#courier/receive');
    await loaded;
    await expect(driver.getByRole('region', { name: 'Réception physique d’un onduleur', exact: true })).toHaveCount(0);
    await expect(driver.getByRole('textbox', { name: 'Numéro de série à réceptionner', exact: true })).toHaveCount(0);
    await login(otherDriver, sameCompanyOther.username, true);
    expect(await api(otherDriver, 'logistics/outbound/')).toEqual([]);
    expect((await response(otherDriver, `logistics/outbound/${job.id}/`)).status()).toBe(404);
    expect(await api(page, `requests/${data.request.id}/`)).toMatchObject({ status: 'ready_for_delivery', closed_at: null });
  } finally {
    await Promise.all([externalContext.close(), otherContext.close()]);
  }
});

test('le routage prêt à livrer choisit le référent actif, signale le livreur manquant et préserve les missions existantes lors de la réconciliation explicite', async ({ page }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('routage-fictif');
  const fallbackOwner = await company(page, `${tag}-REFERENT`);
  const missingOwner = await company(page, `${tag}-MANQUANT`);
  const manualOwner = await company(page, `${tag}-MANUEL`);
  const firstInternal = await courierAccount(page, `${tag}-TVM1`);
  const nextInternal = await courierAccount(page, `${tag}-TVM2`);
  const inactiveDefault = await courierAccount(page, `${tag}-INACTIF`, 'client', fallbackOwner.id);
  const manualDefault = await courierAccount(page, `${tag}-MANUEL-EXTERNE`, 'client', manualOwner.id);
  await api(page, `clients/${fallbackOwner.id}/`, 'PATCH', { default_courier: inactiveDefault.id, internal_courier: firstInternal.id });
  await api(page, `users/${inactiveDefault.id}/`, 'PATCH', { is_active: false });
  const fallback = await repairFixture(page, fallbackOwner, `${tag}-REFERENT`);
  const missing = await repairFixture(page, missingOwner, `${tag}-MANQUANT`);
  const manual = await repairFixture(page, manualOwner, `${tag}-MANUEL`);
  await makeReady(page, fallback.request);
  await makeReady(page, missing.request);
  await makeReady(page, manual.request);
  let jobs = await api(page, 'logistics/outbound/');
  const fallbackJob = jobs.find(job => job.service_request === fallback.request.id);
  expect(fallbackJob).toMatchObject({ assignment_mode: 'automatic', routing_source: 'internal_courier', assigned_courier: firstInternal.id, assigned_courier_kind: 'internal', equipment: fallback.unit.id });
  expect(jobs.some(job => job.service_request === missing.request.id)).toBe(false);
  expect(jobs.some(job => job.service_request === manual.request.id)).toBe(false);
  const candidate = (await api(page, 'logistics/dispatch-candidates/')).find(row => row.id === missing.request.id || row.service_request === missing.request.id);
  expect(candidate).toMatchObject({ routing_status: 'unassigned', recommended_courier: null, routing_source: '' });

  await navigate(page, 'Logistique');
  await page.getByRole('group', { name: 'Files logistiques', exact: true }).getByRole('button', { name: /^Livraisons et retours à affecter/ }).click();
  const row = page.locator('.logistics-candidates-table tbody tr').filter({ hasText: manual.request.call_number || manual.request.reference });
  await expect(row).toHaveCount(1);
  await row.getByRole('combobox', { name: `Livreur pour le dossier ${manual.request.call_number || manual.request.reference}`, exact: true }).selectOption(String(firstInternal.id));
  await row.getByRole('textbox', { name: 'Adresse de livraison', exact: true }).fill('27 voie du laboratoire manuel fictif');
  await row.getByRole('textbox', { name: 'Contact de livraison', exact: true }).fill('Destinataire fictif du laboratoire');
  await row.getByRole('textbox', { name: 'Téléphone de livraison', exact: true }).fill('0000000027');
  const assignedResponse = mutationResponse(page, 'logistics/outbound/');
  await row.getByRole('button', { name: 'Affecter le transport', exact: true }).click();
  const manualJob = await mutation(assignedResponse);
  expect(manualJob).toMatchObject({ assignment_mode: 'manual', routing_source: 'manual', assigned_courier: firstInternal.id });

  // Changing a routing preference does not make a GET mutate the mission list.
  await api(page, `clients/${missingOwner.id}/`, 'PATCH', { internal_courier: nextInternal.id });
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await api(page, 'logistics/dispatch-candidates/');
    await api(page, 'logistics/bootstrap/');
    expect((await api(page, 'logistics/outbound/')).some(job => job.service_request === missing.request.id)).toBe(false);
  }
  await api(page, 'logistics/reconcile/', 'POST', { client: missingOwner.id, reassign_automatic: false });
  const reconciled = (await api(page, 'logistics/outbound/')).find(job => job.service_request === missing.request.id);
  expect(reconciled).toMatchObject({ assignment_mode: 'automatic', routing_source: 'internal_courier', assigned_courier: nextInternal.id });

  await api(page, `clients/${manualOwner.id}/`, 'PATCH', { default_courier: manualDefault.id, internal_courier: nextInternal.id });
  await api(page, `clients/${fallbackOwner.id}/`, 'PATCH', { default_courier: null, internal_courier: nextInternal.id });
  await api(page, 'logistics/reconcile/', 'POST', { reassign_automatic: false });
  jobs = await api(page, 'logistics/outbound/');
  const preservedManual = jobs.find(job => job.id === manualJob.id);
  const preservedAutomatic = jobs.find(job => job.id === fallbackJob.id);
  expect(preservedManual).toMatchObject({ assigned_courier: firstInternal.id, assignment_mode: 'manual', routing_source: 'manual', assignment_revision: manualJob.assignment_revision });
  expect(preservedAutomatic).toMatchObject({ assigned_courier: firstInternal.id, assignment_mode: 'automatic', routing_source: 'internal_courier', assignment_revision: fallbackJob.assignment_revision });
  expect(jobs.filter(job => job.service_request === missing.request.id)).toHaveLength(1);

  const exchangeUnit = await equipment(page, fallbackOwner, `ROUTAGE-ORIGINE-${tag}`);
  const exchange = await api(page, 'requests/', 'POST', { equipment: exchangeUnit.id, subject: `Échange routé fictif ${tag}`, status: 'exchange' });
  const replacementSerial = `ROUTAGE-REMPLACEMENT-${tag}`;
  await api(page, `requests/${exchange.id}/exchange/`, 'PATCH', { replacement_serial_number: replacementSerial, replacement_model: 'Remplacement fictif destiné au transport', replacement_brand: 'Eaton' });
  const validated = await api(page, `requests/${exchange.id}/exchange/validate/`, 'POST', { mark_ready: true });
  const exchangeJob = (await api(page, 'logistics/outbound/')).find(job => job.service_request === exchange.id);
  expect(exchangeJob).toMatchObject({ equipment: validated.exchange.replacement_equipment, serial_number: replacementSerial, assigned_courier: nextInternal.id, assignment_mode: 'automatic', routing_source: 'internal_courier' });
  expect(exchangeJob.equipment).not.toBe(exchangeUnit.id);

  // Nonrepairable returns require a deliberate assignment, even with defaults.
  const returnData = await repairFixture(page, fallbackOwner, `${tag}-RETOUR`);
  await api(page, `requests/${returnData.request.id}/disposition/nonrepairable/`, 'POST', { diagnosis: 'Retour fictif : onduleur non réparable.', fee_mode: 'billable' });
  expect((await api(page, 'logistics/outbound/')).some(job => job.service_request === returnData.request.id)).toBe(false);
  const returnCandidate = (await api(page, 'logistics/dispatch-candidates/')).find(candidate => candidate.id === returnData.request.id || candidate.service_request === returnData.request.id);
  expect(returnCandidate).toMatchObject({ kind: 'return', equipment: returnData.unit.id });
});

test('une collecte chez le client final conserve le centre demandeur, exige son identité et reste réservée aux livreurs TVM jusqu’à la réception physique', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('client-final-fictif');
  const owner = await company(page, `${tag}-CENTRE-A`);
  const foreignOwner = await company(page, `${tag}-CENTRE-B`);
  const unit = await equipment(page, owner, `FINAL-CENTRE-A-${tag}`);
  const foreignUnit = await equipment(page, foreignOwner, `FINAL-CENTRE-B-${tag}`);
  const customerAccount = await clientAccount(page, owner, tag);
  const internal = await courierAccount(page, `${tag}-TVM`);
  const external = await courierAccount(page, `${tag}-EXTERNE`, 'client', owner.id);
  const foreignExternal = await courierAccount(page, `${tag}-ETRANGER`, 'client', foreignOwner.id);
  const customerContext = await browser.newContext();
  const externalContext = await browser.newContext();
  const internalContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const customer = await customerContext.newPage();
  const externalDriver = await externalContext.newPage();
  const internalDriver = await internalContext.newPage();
  const finalName = `Site final fictif du centre A ${tag}`;
  const finalAddress = '127 voie du client final fictif, Cotonou';
  try {
    await login(customer, customerAccount.username);
    await navigate(customer, 'Mes enlèvements');
    await customer.getByRole('button', { name: 'Demander un enlèvement', exact: true }).first().click();
    const form = customer.getByRole('dialog', { name: 'Demander un enlèvement', exact: true });
    await expect(form.getByRole('combobox', { name: 'Centre client demandeur', exact: true })).toHaveCount(0);
    const ownUnits = form.getByRole('combobox', { name: 'Équipement à envoyer', exact: true });
    await expect(ownUnits.locator(`option[value="${foreignUnit.id}"]`)).toHaveCount(0);
    await ownUnits.selectOption(String(unit.id));
    await form.getByRole('combobox', { name: 'Lieu de collecte', exact: true }).selectOption('end_customer');
    const finalField = form.getByRole('textbox', { name: 'Nom du client final', exact: true });
    await expect(finalField).toHaveJSProperty('required', true);
    await finalField.fill(finalName);
    await form.getByRole('textbox', { name: 'Votre n° d’appel client', exact: true }).fill(`000-FINAL-${tag}`);
    await form.getByRole('textbox', { name: 'Problème signalé', exact: true }).fill('Défaut fictif signalé sur le site final, collecte demandée par le centre propriétaire.');
    await form.getByRole('textbox', { name: 'Adresse d’enlèvement', exact: true }).fill(finalAddress);
    await form.getByRole('textbox', { name: 'Contact pour l’enlèvement', exact: true }).fill('Contact fictif du site final A');
    await form.getByRole('textbox', { name: 'Téléphone du contact', exact: true }).fill('0000000127');
    const submitted = mutationResponse(customer, 'logistics/pickups/');
    await form.getByRole('button', { name: 'Enregistrer la demande d’enlèvement', exact: true }).click();
    const submittedResponse = await submitted;
    expect(submittedResponse.ok(), await submittedResponse.text()).toBe(true);
    const posted = submittedResponse.request().postDataJSON();
    expect(Object.hasOwn(posted, 'client')).toBe(false);
    expect(posted).toMatchObject({ equipment: unit.id, pickup_scope: 'end_customer', end_customer_name: finalName, pickup_address: finalAddress });
    const pickup = await submittedResponse.json();
    expect(pickup).toMatchObject({ status: 'requested', client: { id: owner.id, name: owner.name }, equipment: unit.id, pickup_scope: 'end_customer', end_customer_name: finalName, service_request: null, received_at: null, assigned_courier: null });
    expect(await api(page, `requests/?q=${encodeURIComponent(unit.serial_number)}`)).toEqual([]);
    await expect(customer.locator('.pickup-card').filter({ hasText: unit.serial_number })).toContainText(finalName);
    expect((await response(customer, 'logistics/pickups/', 'POST', { ...posted, request_key: randomUUID(), client: foreignOwner.id })).status()).toBe(400);
    expect((await response(customer, 'logistics/pickups/', 'POST', { ...posted, request_key: randomUUID(), equipment: foreignUnit.id })).status()).toBe(404);
    expect((await response(customer, 'logistics/pickups/', 'POST', { ...posted, request_key: randomUUID(), end_customer_name: '' })).status()).toBe(400);
    expect((await response(page, `logistics/pickups/${pickup.id}/assign/`, 'POST', { courier: external.id })).status()).toBe(400);

    await reload(page);
    await navigate(page, 'Logistique');
    await page.getByRole('button', { name: 'Créer une collecte', exact: true }).click();
    const managerForm = page.getByRole('dialog', { name: 'Créer une collecte pour un centre', exact: true });
    const centre = managerForm.getByRole('combobox', { name: 'Centre client demandeur', exact: true });
    await expect(centre).toHaveJSProperty('required', true);
    await centre.selectOption(String(foreignOwner.id));
    const managerUnits = managerForm.getByRole('combobox', { name: 'Équipement à envoyer', exact: true });
    await expect(managerUnits.locator(`option[value="${unit.id}"]`)).toHaveCount(0);
    await managerUnits.selectOption(String(foreignUnit.id));
    await managerForm.getByRole('combobox', { name: 'Lieu de collecte', exact: true }).selectOption('end_customer');
    await managerForm.getByRole('textbox', { name: 'Nom du client final', exact: true }).fill(`Site final fictif du centre B ${tag}`);
    await managerForm.getByRole('textbox', { name: 'Problème signalé', exact: true }).fill('Collecte fictive enregistrée par le responsable pour le centre B.');
    await managerForm.getByRole('textbox', { name: 'Adresse d’enlèvement', exact: true }).fill('227 voie du client final fictif B');
    await managerForm.getByRole('textbox', { name: 'Contact pour l’enlèvement', exact: true }).fill('Contact fictif du site final B');
    await managerForm.getByRole('textbox', { name: 'Téléphone du contact', exact: true }).fill('0000000227');
    const managerSubmitted = mutationResponse(page, 'logistics/pickups/');
    await managerForm.getByRole('button', { name: 'Enregistrer la demande d’enlèvement', exact: true }).click();
    const managerResponse = await managerSubmitted;
    expect(managerResponse.ok(), await managerResponse.text()).toBe(true);
    expect(managerResponse.request().postDataJSON().client).toBe(foreignOwner.id);
    const managerPickup = await managerResponse.json();
    expect(managerPickup).toMatchObject({ client: { id: foreignOwner.id }, equipment: foreignUnit.id, pickup_scope: 'end_customer', service_request: null, assigned_courier: null });
    expect((await response(page, 'logistics/pickups/', 'POST', { ...posted, request_key: randomUUID() })).status()).toBe(400);
    expect((await response(customer, `logistics/pickups/${managerPickup.id}/`)).status()).toBe(404);
    expect((await api(customer, 'logistics/pickups/')).map(item => item.id)).toEqual([pickup.id]);
    const row = page.locator('.logistics-pickups-table tbody tr').filter({ hasText: unit.serial_number });
    const courierChoice = row.getByRole('combobox', { name: `Livreur pour l’enlèvement ${pickup.id}`, exact: true });
    await expect(courierChoice.locator(`option[value="${external.id}"]`)).toHaveCount(0);
    await expect(courierChoice.locator(`option[value="${foreignExternal.id}"]`)).toHaveCount(0);
    await courierChoice.selectOption(String(internal.id));
    const assigned = mutationResponse(page, `logistics/pickups/${pickup.id}/assign/`);
    await row.getByRole('button', { name: 'Enregistrer l’affectation', exact: true }).click();
    expect(await mutation(assigned)).toMatchObject({ assigned_courier: internal.id, status: 'assigned', end_customer_name: finalName });

    await login(externalDriver, external.username, true);
    expect(await api(externalDriver, 'logistics/pickups/')).toEqual([]);
    expect((await response(externalDriver, `logistics/pickups/${pickup.id}/`)).status()).toBe(404);
    expect((await response(externalDriver, `logistics/pickups/${pickup.id}/collect/`, 'POST', {})).status()).toBe(403);
    await login(internalDriver, internal.username, true);
    const internalBootstrap = await api(internalDriver, 'logistics/bootstrap/');
    expect(internalBootstrap.capabilities).toMatchObject({ can_receive: true, can_lookup: true, can_pickups: true });
    await courierNavigate(internalDriver, 'Tournées');
    const card = internalDriver.locator('.courier-job-card').filter({ hasText: unit.serial_number });
    await expect(card).toContainText(owner.name);
    await expect(card).toContainText(finalName);
    await expect(card).toContainText(finalAddress);
    await expect(card).toContainText('Contact fictif du site final A');
    const collected = mutationResponse(internalDriver, `logistics/pickups/${pickup.id}/collect/`);
    await card.getByRole('button', { name: 'Prendre en charge l’enlèvement', exact: true }).click();
    expect(await mutation(collected)).toMatchObject({ status: 'collected', received_at: null, service_request: null });
    expect(await api(page, `requests/?q=${encodeURIComponent(unit.serial_number)}`)).toEqual([]);
    const lookedUp = mutationResponse(internalDriver, 'logistics/lookup/');
    await card.getByRole('button', { name: 'Réceptionner à l’atelier', exact: true }).click();
    await mutation(lookedUp);
    const reception = internalDriver.getByRole('region', { name: 'Réception physique d’un onduleur', exact: true });
    const receive = reception.getByRole('button', { name: 'Confirmer la réception', exact: true });
    await expect(receive).toBeDisabled();
    await reception.getByRole('checkbox', { name: 'Je confirme avoir reçu physiquement cet onduleur.', exact: true }).check();
    const received = mutationResponse(internalDriver, 'logistics/receive/');
    const before = Date.now();
    await receive.click();
    const receipt = await mutation(received);
    expect(receipt).toMatchObject({ created_request: true, created_equipment: false, request: { client: { id: owner.id }, serial_number: unit.serial_number, status: 'new' } });
    expect(Date.parse(receipt.request.arrived_at)).toBeGreaterThanOrEqual(before - 1000);
    expect(Date.parse(receipt.request.arrived_at)).toBeLessThanOrEqual(Date.now() + 1000);
    const request = await api(page, `requests/${receipt.request.id}/`);
    expect(request).toMatchObject({ equipment: unit.id, status: 'new', assigned_technician: null, end_customer: finalName, contact_name: 'Contact fictif du site final A', contact_phone: '0000000127', client_reference: `000-FINAL-${tag}` });
    expect(Date.parse(request.arrived_at)).toBe(Date.parse(receipt.request.arrived_at));
    expect((await api(page, `equipment/${unit.id}/`)).client).toBe(owner.id);
    expect((await api(page, `logistics/pickups/${pickup.id}/`))).toMatchObject({ status: 'received', client: { id: owner.id }, end_customer_name: finalName, service_request: request.id });
    expect(await api(page, `requests/?q=${encodeURIComponent(foreignUnit.serial_number)}`)).toEqual([]);
  } finally {
    await Promise.all([customerContext.close(), externalContext.close(), internalContext.close()]);
  }
});
