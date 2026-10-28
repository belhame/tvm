import { test, expect } from '@playwright/test';
import { openLegacyDashboard } from './legacy_navigation.js';
import { fileURLToPath } from 'node:url';

const catalogueFixture = fileURLToPath(new URL('../../backend/core/tests/fixtures/catalogue_synthetic.xls', import.meta.url));
const intakeFixture = fileURLToPath(new URL('../../backend/core/tests/fixtures/request_intake_synthetic.xls', import.meta.url));

const password = process.env.TVM_DEMO_PASSWORD;
test.beforeAll(() => {
  if (!password) throw new Error('TVM_DEMO_PASSWORD requis ; utiliser bash scripts/e2e.sh.');
});

async function login(page, username = 'admin', waitForData = true) {
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = waitForData ? page.waitForResponse(response => response.url().endsWith('/api/dashboard/') && response.status() === 200) : null;
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await expect(page.getByRole('heading', { name: /Demandes SAV|Tableau de bord|Mon espace/i }).first()).toBeVisible();
  if (loaded) {
    await loaded;
    await openLegacyDashboard(page);
  }
}

async function api(page, path, method = 'GET', data) {
  const session = await page.request.get('/api/session/');
  const { csrfToken } = await session.json();
  const response = await page.request.fetch(`/api/${path}`, {
    method, data, headers: { 'X-CSRFToken': csrfToken },
  });
  expect(response.ok(), `${method} ${path} → ${response.status()}: ${await response.text()}`).toBeTruthy();
  return response.headers()['content-type']?.includes('application/json') ? response.json() : response.body();
}

test('les formulaires réalisent le parcours SAV complet', async ({ page }) => {
  await login(page);
  const marker = `Formulaire-${Date.now()}`;
  const navigate = async label => {
    await page.getByRole('navigation', { name: 'Navigation principale' }).getByText(label, { exact: true }).click();
  };
  const save = async () => {
    await page.getByRole('dialog').getByRole('button', { name: 'Enregistrer', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  };
  await navigate('Clients');
  await page.getByRole('button', { name: 'Nouveau client', exact: true }).first().click();
  await page.getByLabel(/Raison sociale/).fill(marker);
  await page.getByLabel('Contact principal', { exact: true }).fill('Contact de validation');
  await save();
  await expect(page.getByRole('cell', { name: new RegExp(marker) }).first()).toBeVisible();
  await navigate('Équipements');
  await page.getByRole('button', { name: 'Nouvel équipement', exact: true }).first().click();
  await page.getByRole('dialog').getByLabel(/^Client/).selectOption({ label: marker });
  await page.getByLabel(/Numéro de série/).fill(marker);
  await page.getByLabel(/^Modèle/).fill('93PM');
  await page.getByLabel('Puissance (kVA)', { exact: true }).fill('100');
  await save();
  await navigate('Demandes SAV');
  await page.getByRole('button', { name: 'Nouvelle demande', exact: true }).first().click();
  const equipmentSelect = page.getByLabel(/Équipement concerné/);
  const equipmentValue = await equipmentSelect.getByRole('option').filter({ hasText: marker }).getAttribute('value');
  await equipmentSelect.selectOption(equipmentValue);
  await page.getByLabel(/Objet du signalement/).fill(marker);
  await page.getByLabel(/Description de la panne/).fill('Alarme batterie à traiter sur site.');
  await save();
  await navigate('Interventions');
  await page.getByRole('button', { name: 'Nouvelle intervention', exact: true }).first().click();
  const requestSelect = page.getByLabel(/^Demande SAV/);
  const requestValue = await requestSelect.getByRole('option').filter({ hasText: marker }).getAttribute('value');
  await requestSelect.selectOption(requestValue);
  await page.getByLabel('Diagnostic et observations', { exact: true }).fill('Batterie défectueuse détectée.');
  await page.getByLabel('Travaux réalisés', { exact: true }).fill('Batterie remplacée et test fonctionnel réussi.');
  await page.getByRole('dialog').getByRole('combobox', { name: 'Statut', exact: true }).selectOption('completed');
  await save();
  const interventions = await api(page, 'interventions/');
  const result = interventions.find(item => item.equipment_serial === marker);
  expect(result.status).toBe('completed');
  await page.getByRole('button', { name: `Voir ${result.reference}`, exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Batterie remplacée');
  const pdf = await page.request.get(`/api/interventions/${result.id}/report/`);
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
});

test('parcours persistant client → onduleur → demande → intervention → PDF', async ({ page, browser }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page);
  const marker = `E2E-${Date.now()}`;
  const client = await api(page, 'clients/', 'POST', { name: marker, email: 'contact@example.invalid', city: 'Lyon' });
  const equipment = await api(page, 'equipment/', 'POST', { client: client.id, serial_number: marker, model: '93PM', brand: 'Eaton', power_kva: '100.00', location: 'Salle serveur' });
  const request = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: 'Alarme batterie', description: 'Validation navigateur du parcours SAV.', priority: 'high' });
  const users = await api(page, 'users/');
  const tech = users.find(user => user.username === 'technicien');
  const intervention = await api(page, 'interventions/', 'POST', { service_request: request.id, technician: tech.id, scheduled_at: new Date().toISOString(), diagnosis: 'Batterie à remplacer', internal_notes: 'CONFIDENTIEL-E2E' });
  await api(page, `interventions/${intervention.id}/`, 'PATCH', { status: 'completed', work_done: 'Remplacement de la batterie et test de charge.', recommendations: 'Vérification dans six mois.' });
  const pdf = await api(page, `interventions/${intervention.id}/report/`);
  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  expect(pdf.length).toBeGreaterThan(1500);

  // A separate browser session proves that the data lives on the server.
  const second = await browser.newContext();
  const other = await second.newPage();
  await login(other, 'responsable');
  const recovered = await api(other, `equipment/${equipment.id}/`);
  expect(recovered.serial_number).toBe(marker);
  const recoveredIntervention = await api(other, `interventions/${intervention.id}/`);
  expect(recoveredIntervention.status).toBe('completed');
  await second.close();
  await page.screenshot({ path: '../../.local/powercare-dashboard-desktop.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('le portail client filtre les listes, recherche et PDF côté serveur', async ({ page, browser }) => {
  await login(page, 'client');
  const session = await (await page.request.get('/api/session/')).json();
  const myClient = session.user.client;
  const clients = await api(page, 'clients/');
  expect(clients.length).toBe(1);
  expect(clients[0].id).toBe(myClient);
  const equipment = await api(page, 'equipment/');
  expect(equipment.length).toBeGreaterThan(0);
  expect(equipment.every(item => item.client === myClient)).toBeTruthy();
  const interventions = await api(page, 'interventions/');
  expect(interventions.every(item => !Object.hasOwn(item, 'internal_notes'))).toBeTruthy();

  const adminContext = await browser.newContext();
  const admin = await adminContext.newPage();
  await login(admin);
  const allEquipment = await api(admin, 'equipment/');
  const foreign = allEquipment.find(item => item.client !== myClient);
  expect(foreign).toBeTruthy();
  expect((await page.request.get(`/api/equipment/${foreign.id}/`)).status()).toBe(404);
  const search = await api(page, `search/?q=${encodeURIComponent(foreign.serial_number)}`);
  expect(search.equipment).toEqual([]);
  const allInterventions = await api(admin, 'interventions/');
  const foreignIntervention = allInterventions.find(item => item.equipment_serial === foreign.serial_number);
  if (foreignIntervention) expect((await page.request.get(`/api/interventions/${foreignIntervention.id}/report/`)).status()).toBe(404);
  expect((await page.request.get('/api/parts/')).status()).toBe(403);
  expect((await page.request.get('/api/users/')).status()).toBe(403);
  await adminContext.close();
});

test('la navigation reste utilisable sur téléphone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, 'technicien');
  await expect(page.getByRole('heading').first()).toBeVisible();
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
  expect(overflows).toBeFalsy();
  await page.screenshot({ path: '../../.local/powercare-mobile.png', fullPage: true });
});

test('analyse Eaton consultative dans la fiche et le scanner, sans modifier les données', async ({ page }) => {
  await login(page);
  const navigate = async label => {
    await page.getByRole('navigation', { name: 'Navigation principale' }).getByText(label, { exact: true }).click();
  };
  await navigate('Équipements');
  await page.getByRole('button', { name: 'Nouvel équipement', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  const serialInput = dialog.getByLabel(/Numéro de série/);
  await serialInput.fill('1ABCW01007');
  await dialog.getByRole('button', { name: 'Analyser le format Eaton', exact: true }).click();
  await expect(dialog.locator('.serial-analysis')).toContainText('ABC');
  await expect(dialog.locator('.serial-analysis')).toContainText('007');
  await expect(dialog.getByLabel(/^Modèle/)).toHaveValue('');
  await expect(dialog.getByLabel(/Mise en service/)).toHaveValue('');
  await expect(dialog.getByLabel(/Fin de garantie/)).toHaveValue('');

  const marker = `LIBRE-${Date.now()}`;
  await serialInput.fill(marker);
  await expect(dialog.locator('.serial-analysis')).not.toContainText('007');
  await dialog.getByRole('button', { name: 'Analyser le format Eaton', exact: true }).click();
  await expect(dialog.locator('.serial-analysis')).toContainText('Ce numéro peut être conservé');
  const clients = await api(page, 'clients/');
  await dialog.getByLabel(/^Client/).selectOption(String(clients[0].id));
  await dialog.getByLabel(/^Modèle/).fill('Modèle saisi manuellement');
  await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const equipment = await api(page, `equipment/?serial=${encodeURIComponent(marker)}`);
  expect(equipment).toHaveLength(1);
  expect(equipment[0].serial_number).toBe(marker);
  expect(equipment[0].model).toBe('Modèle saisi manuellement');
  expect(equipment[0].commissioned_on).toBeNull();
  expect(equipment[0].warranty_until).toBeNull();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await navigate('Scanner un équipement');
  await page.getByLabel('Ou saisir le numéro de série', { exact: true }).fill('1ABCW01007');
  await page.getByRole('button', { name: 'Analyser le format Eaton', exact: true }).click();
  await expect(page.locator('.serial-analysis')).toContainText('ABC');
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)).toBeFalsy();
  await page.getByLabel('Ou saisir le numéro de série', { exact: true }).fill(marker);
  await page.getByRole('button', { name: /Rechercher l’équipement/ }).click();
  await expect(page.locator('main')).toContainText('Modèle saisi manuellement');
});

test('un changement de compte ignore les anciennes réponses et efface les données privées', async ({ page }) => {
  let delayed = false;
  let release;
  let finished;
  const gate = new Promise(resolve => { release = resolve; });
  const completed = new Promise(resolve => { finished = resolve; });
  await page.route('**/api/equipment/', async route => {
    const response = await route.fetch();
    if (!delayed) {
      delayed = true;
      await gate;
      await route.fulfill({ response });
      finished();
    } else {
      await route.fulfill({ response });
    }
  });
  await login(page, 'admin', false);
  await expect.poll(() => delayed).toBeTruthy();
  await page.getByRole('button', { name: 'Se déconnecter', exact: true }).click();
  await page.getByLabel('Identifiant', { exact: true }).fill('client');
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = page.waitForResponse(response => response.url().endsWith('/api/dashboard/') && response.status() === 200);
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  const ownEquipment = await api(page, 'equipment/');
  release();
  await completed;
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.getByRole('navigation').getByText('Équipements', { exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(ownEquipment.length);
  for (const equipment of ownEquipment) await expect(page.getByRole('cell', { name: new RegExp(equipment.serial_number) }).first()).toBeVisible();
  await expect(page.getByRole('navigation')).not.toContainText('Comptes & accès');
});

test('import XLS du catalogue partagé, garanties et années conservées sans doublon', async ({ page }) => {
  await login(page);
  const before = await api(page, 'equipment/');
  await page.getByRole('navigation', { name: 'Navigation principale' }).getByText('Catalogue Eaton', { exact: true }).click();
  await page.getByLabel('Fichier catalogue XLS', { exact: true }).setInputFiles(catalogueFixture);
  const uploaded = page.waitForResponse(response => response.url().endsWith('/api/catalogue/import/') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Importer le catalogue', exact: true }).click();
  const response = await uploaded;
  expect(response.ok()).toBeTruthy();
  const first = await api(page, 'catalogue/');
  expect(first.counts).toMatchObject({ products: 4, warranties: 6, year_mappings: 9, na_codes: 1, duplicate_code_groups: 1 });
  await expect(page.locator('.catalogue-current')).toContainText('ZZ');
  await expect(page.getByRole('region', { name: 'Produits du catalogue', exact: true })).toContainText('Onduleur laboratoire Alpha');
  await page.getByLabel('Structure des produits', { exact: true }).selectOption('Eaton');
  await page.getByLabel('Rechercher dans le catalogue', { exact: true }).fill('QX1');
  await page.getByRole('region', { name: 'Produits du catalogue', exact: true }).getByRole('button', { name: 'Rechercher', exact: true }).click();
  const products = page.getByRole('region', { name: 'Produits du catalogue', exact: true });
  await expect(products.locator('tbody tr')).toHaveCount(2);
  await expect(products).toContainText('Plusieurs correspondances');
  await page.getByRole('tab', { name: /^Garanties/ }).click();
  const warranties = page.getByRole('region', { name: 'Informations de garantie du catalogue', exact: true });
  await expect(warranties).toContainText('36 mois');
  await expect(warranties).toContainText('24 mois');
  await expect(warranties).toContainText('selon contrat');
  await page.getByRole('tab', { name: /^Années/ }).click();
  await expect(page.getByRole('region', { name: 'Tables des années du catalogue', exact: true })).toContainText('2041');

  await page.getByLabel('Fichier catalogue XLS', { exact: true }).setInputFiles(catalogueFixture);
  const repeated = page.waitForResponse(result => result.url().endsWith('/api/catalogue/import/') && result.request().method() === 'POST');
  await page.getByRole('button', { name: 'Importer le catalogue', exact: true }).click();
  expect((await repeated).status()).toBe(200);
  const second = await api(page, 'catalogue/');
  expect(second.active_import.id).toBe(first.active_import.id);
  expect(second.counts).toEqual(first.counts);
  const after = await api(page, 'equipment/');
  expect(after).toEqual(before);

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)).toBeFalsy();
});

test('un modèle du catalogue est choisi explicitement et le catalogue reste réservé aux internes', async ({ page, browser }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'Navigation principale' }).getByText('Équipements', { exact: true }).click();
  await page.getByRole('button', { name: 'Nouvel équipement', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel(/Numéro de série/).fill('CHOIX-CATALOGUE-TEST');
  await dialog.getByRole('button', { name: 'Choisir dans le catalogue Eaton', exact: true }).click();
  await dialog.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Choisir Onduleur laboratoire Alpha variante', exact: true })).toBeVisible();
  await expect(dialog.getByLabel(/^Modèle/)).toHaveValue('');
  await dialog.getByRole('button', { name: 'Choisir Onduleur laboratoire Alpha variante', exact: true }).click();
  await expect(dialog.getByLabel(/^Modèle/)).toHaveValue('Onduleur laboratoire Alpha variante');
  await expect(dialog.getByLabel(/Numéro de série/)).toHaveValue('CHOIX-CATALOGUE-TEST');
  await expect(dialog.getByLabel('Mise en service', { exact: true })).toHaveValue('');
  await expect(dialog.getByLabel('Fin de garantie', { exact: true })).toHaveValue('');
  await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
  expect(await api(page, 'equipment/?serial=CHOIX-CATALOGUE-TEST')).toEqual([]);

  const staffContext = await browser.newContext();
  const staff = await staffContext.newPage();
  await login(staff, 'technicien');
  await staff.getByRole('navigation', { name: 'Navigation principale' }).getByText('Catalogue Eaton', { exact: true }).click();
  await expect(staff.getByRole('heading', { name: 'Catalogue Eaton', exact: true })).toBeVisible();
  await expect(staff.getByRole('button', { name: 'Importer le catalogue', exact: true })).toHaveCount(0);
  await expect(staff.locator('.catalogue-current')).toContainText('ZZ');
  await staffContext.close();

  const clientContext = await browser.newContext();
  const customer = await clientContext.newPage();
  await login(customer, 'client');
  await expect(customer.getByRole('navigation')).not.toContainText('Catalogue Eaton');
  for (const path of ['catalogue/', 'catalogue/products/', 'catalogue/warranties/']) {
    expect((await customer.request.get(`/api/${path}`)).status()).toBe(403);
  }
  await clientContext.close();
});

test('nouvelle demande depuis une série : modèle court, garantie plus six mois et sauvegarde atomique', async ({ page }) => {
  await login(page);
  const navigation = page.getByRole('navigation', { name: 'Navigation principale' });
  await navigation.getByText('Catalogue Eaton', { exact: true }).click();
  await page.getByLabel('Fichier catalogue XLS', { exact: true }).setInputFiles(intakeFixture);
  const imported = page.waitForResponse(response => response.url().endsWith('/api/catalogue/import/') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Importer le catalogue', exact: true }).click();
  expect((await imported).ok()).toBeTruthy();

  let serial;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    serial = `GAB2A49${String((Date.now() + attempt) % 1000).padStart(3, '0')}`;
    if ((await api(page, `equipment/?serial=${serial}`)).length === 0) break;
  }
  expect(await api(page, `equipment/?serial=${serial}`)).toEqual([]);
  await navigation.getByText('Demandes SAV', { exact: true }).click();
  await page.getByRole('button', { name: 'Nouvelle demande', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel(/^Numéro de série/).fill(serial);
  const lookupResponse = page.waitForResponse(response => response.url().endsWith('/api/serial-lookup/') && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Rechercher le modèle et la garantie', exact: true }).click();
  const lookup = await (await lookupResponse).json();
  expect(lookup.selected_product.catalogue_number).toBe('LAB850F');
  expect(lookup.manufactured_on).toBe('2023-12-04');
  expect(lookup.computed_warranty).toMatchObject({ starts_on: '2024-06-04', ends_on: '2026-06-04', duration_months: 24 });
  await expect(dialog).toContainText('LAB850F');
  await expect(dialog).toContainText('04/06/2024');
  await expect(dialog).toContainText('04/06/2026');
  expect(await api(page, `equipment/?serial=${serial}`)).toEqual([]);
  const clients = await api(page, 'clients/');
  await dialog.getByRole('combobox', { name: /^Client\s/ }).selectOption(String(clients[0].id));
  const subject = `Série complète ${Date.now()}`;
  await dialog.getByLabel(/Objet du signalement/).fill(subject);
  await dialog.getByLabel(/Description de la panne/).fill('Alarme de test du parcours numéro de série et garantie.');
  const intakeResponse = page.waitForResponse(response => response.url().endsWith('/api/requests/intake/') && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
  const response = await intakeResponse;
  expect(response.status()).toBe(201);
  const payload = response.request().postDataJSON();
  const saved = await response.json();
  expect(saved.equipment.model).toBe('LAB850F');
  expect(saved.equipment.manufactured_on).toBe('2023-12-04');
  expect(saved.warranty).toMatchObject({ starts_on: '2024-06-04', ends_on: '2026-06-04' });
  expect(saved.request.equipment).toBe(saved.equipment.id);
  await expect(dialog).toHaveCount(0);
  const replay = await api(page, 'requests/intake/', 'POST', payload);
  expect(replay.created).toBe(false);
  expect(replay.request.id).toBe(saved.request.id);
  const equipment = await api(page, `equipment/?serial=${serial}`);
  expect(equipment).toHaveLength(1);
  const requests = await api(page, 'requests/');
  expect(requests.filter(row => row.subject === subject)).toHaveLength(1);
});

test('modifier une série efface les anciennes propositions et annuler ne crée aucun équipement', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await page.getByRole('navigation', { name: 'Navigation principale' }).getByText('Demandes SAV', { exact: true }).click();
  await page.getByRole('button', { name: 'Nouvelle demande', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel(/^Numéro de série/).fill('GAB2A49999');
  await dialog.getByRole('button', { name: 'Rechercher le modèle et la garantie', exact: true }).click();
  await expect(dialog).toContainText('LAB850F');
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)).toBeFalsy();
  const marker = `INCONNU-${Date.now()}`;
  await dialog.getByLabel(/^Numéro de série/).fill(marker);
  await expect(dialog.locator('.serial-lookup-summary')).toHaveCount(0);
  await expect(dialog.getByLabel('Modèle identifié', { exact: true })).toHaveValue('');
  await expect(dialog.getByRole('button', { name: 'Enregistrer', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
  expect(await api(page, `equipment/?serial=${marker}`)).toEqual([]);
});
