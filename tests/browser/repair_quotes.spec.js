import { test, expect } from '@playwright/test';
import { createHash, randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { openRequestsWorkspace } from './legacy_navigation.js';

const password = process.env.TVM_DEMO_PASSWORD;
const python = fileURLToPath(new URL('../../.venv/bin/python', import.meta.url));
const marker = () => `DEVIS-FICTIF-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

async function login(page, username = 'admin', courier = false) {
  if (!password) throw new Error('Utiliser bash scripts/e2e.sh avec le mot de passe E2E privé.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  await page.getByRole('button', { name: /Se connecter/i }).click();
  if (courier) await expect(page.getByRole('navigation', { name: 'Navigation livreur', exact: true })).toBeVisible();
  else await expect(page.getByRole('heading', { name: 'Tableau de bord', exact: true })).toBeVisible();
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

function mutation(page, path, method = 'POST') {
  return page.waitForResponse(result => new URL(result.url()).pathname === `/api/${path}` && result.request().method() === method);
}

async function saved(pending, status = 200) {
  const result = await pending;
  expect(result.status(), await result.text()).toBe(status);
  return result.json();
}

async function fixture(page, tag, clientReference = `000-CENTRE-${tag}`) {
  const company = await api(page, 'clients/', 'POST', {
    name: `Centre devis fictif ${tag}`, address: 'Adresse de laboratoire fictive', notes: `NOTE-CLIENT-PRIVEE-${tag}`,
  });
  const equipment = await api(page, 'equipment/', 'POST', {
    client: company.id, serial_number: `${tag}-SERIE`, model: 'Onduleur fictif pour devis', brand: 'Eaton',
  });
  const record = await api(page, 'requests/', 'POST', {
    equipment: equipment.id, subject: `Réparation fictive ${tag}`, client_reference: clientReference,
    description: `DESCRIPTION-INTERNE-${tag}`, warranty_status: 'quotation',
  });
  return { tag, company, equipment, record };
}

const quoteInput = () => ({
  lines: [{ description: 'Réparation de laboratoire fictive', quantity: '2.5', unit_ht: '10.125' },
    { description: 'Essais de charge fictifs', quantity: '3', unit_ht: '4.200' }],
  vat_rate: '19', currency: 'TND', discount_kind: 'percent', discount_value: '7.5',
  terms: 'Conditions publiques fictives : seules les prestations indiquées sont proposées.',
});

async function draft(page, fixture, input = {}) {
  return api(page, 'repair-quotes/', 'POST', { request_key: randomUUID(), service_request: fixture.record.id, ...quoteInput(), ...input });
}

async function issue(page, quote) {
  return api(page, `repair-quotes/${quote.id}/issue/`, 'POST', { request_key: randomUUID(), expected_revision: quote.revision });
}

async function navigateQuotes(page, client = false) {
  const navigation = page.getByRole('navigation', { name: 'Navigation principale', exact: true });
  const open = page.getByRole('button', { name: 'Ouvrir le menu', exact: true });
  if (await open.isVisible() && !await page.locator('.sidebar.open').count()) await open.click();
  await navigation.getByRole('button', { name: client ? 'Mes devis' : 'Devis', exact: true }).click();
  await expect(page.getByRole('heading', { name: client ? 'Mes devis' : 'Devis de réparation', exact: true })).toBeVisible();
  const refreshed = page.waitForResponse(result => new URL(result.url()).pathname === '/api/repair-quotes/' && result.request().method() === 'GET');
  await page.getByRole('button', { name: 'Actualiser les devis', exact: true }).click();
  expect((await refreshed).status()).toBe(200);
}

async function openQuote(page, quote, client = false) {
  await navigateQuotes(page, client);
  await page.getByLabel('Rechercher un devis', { exact: true }).fill(quote.reference);
  await page.locator('.repair-quotes-card').filter({ hasText: quote.reference }).getByRole('button', { name: 'Consulter le devis', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Devis de réparation', exact: true });
  await expect(dialog).toContainText(quote.reference);
  return dialog;
}

async function pdf(page, quote) {
  const result = await page.request.get(quote.pdf_url);
  expect(result.status()).toBe(200);
  expect(result.headers()['content-type']).toContain('application/pdf');
  expect(result.headers()['cache-control']).toContain('no-store');
  expect(result.headers()['content-disposition']).toContain('attachment;');
  const bytes = await result.body();
  expect(bytes.subarray(0, 5).toString()).toBe('%PDF-');
  expect(hash(bytes)).toBe(quote.pdf_sha256);
  const text = execFileSync(python, ['-c', 'import io,sys\nfrom pypdf import PdfReader\nr=PdfReader(io.BytesIO(sys.stdin.buffer.read()))\nprint("\\n".join(p.extract_text() or "" for p in r.pages))'], {
    input: bytes, timeout: 10000, maxBuffer: 1024 * 1024,
  }).toString('utf8');
  return { bytes, text };
}

async function decideViaUI(page, quote, choice) {
  const detail = page.getByRole('dialog', { name: 'Devis de réparation', exact: true });
  const change = detail.getByRole('button', { name: 'Changer d’avis', exact: true });
  if (await change.isVisible()) await change.click();
  const label = choice === 'accepted' ? 'Accepter le devis' : 'Refuser le devis';
  await detail.getByRole('button', { name: label, exact: true }).click();
  const confirmation = page.getByRole('dialog', { name: label, exact: true });
  await expect(confirmation).toContainText(quote.reference);
  const pending = mutation(page, `repair-quotes/${quote.id}/decision/`);
  await confirmation.getByRole('button', { name: 'Oui, confirmer', exact: true }).click();
  const result = await saved(pending);
  expect(result.decision).toBe(choice);
  await expect(confirmation).toHaveCount(0);
  await expect(page.getByRole('dialog', { name: 'Devis de réparation', exact: true })).toBeVisible();
  return result;
}

test('un responsable prépare une remise HT précise, récupère un brouillon concurrent et émet un vrai PDF TVM immuable', async ({ page }) => {
  test.setTimeout(180000);
  await login(page);
  await expect(page.locator('.metric-value').first()).toContainText(/\d/);
  const data = await fixture(page, marker());
  await openRequestsWorkspace(page);
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(data.record.reference);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  await page.getByRole('button', { name: `Ouvrir ${data.record.reference}`, exact: true }).click();
  const dossier = page.getByRole('dialog', { name: 'Dossier SAV', exact: true });
  await dossier.getByRole('tab', { name: 'Devis', exact: true }).click();
  const contextRead = page.waitForResponse(result => new URL(result.url()).pathname === `/api/requests/${data.record.id}/` && result.request().method() === 'GET');
  await dossier.getByRole('tabpanel').getByRole('button', { name: 'Créer un devis', exact: true }).click();
  expect((await contextRead).status()).toBe(200);
  let dialog = page.getByRole('dialog', { name: 'Créer un devis de réparation', exact: true });
  const selectedRequest = dialog.getByLabel('Dossier SAV concerné', { exact: true });
  await expect(selectedRequest).toHaveValue(String(data.record.id));
  const option = selectedRequest.locator('option:checked');
  for (const value of [data.record.reference, data.company.name, data.equipment.serial_number]) await expect(option).toContainText(value);
  await dialog.getByLabel('Devise du devis', { exact: true }).selectOption('TND');
  await dialog.getByLabel('Taux de TVA du devis (%)', { exact: true }).fill('19');
  const input = quoteInput();
  for (let index = 0; index < input.lines.length; index++) {
    if (index) await dialog.getByRole('button', { name: 'Ajouter une ligne', exact: true }).click();
    await dialog.getByLabel(`Description de la ligne ${index + 1}`, { exact: true }).fill(input.lines[index].description);
    await dialog.getByLabel(`Quantité de la ligne ${index + 1}`, { exact: true }).fill(input.lines[index].quantity);
    await dialog.getByLabel(`Prix unitaire HT de la ligne ${index + 1}`, { exact: true }).fill(input.lines[index].unit_ht);
  }
  await dialog.getByLabel('Type de remise', { exact: true }).selectOption('percent');
  await dialog.getByLabel('Remise (%)', { exact: true }).fill('7.5');
  await dialog.getByLabel('Conditions / notes publiques', { exact: true }).fill(input.terms);
  const created = mutation(page, 'repair-quotes/');
  await dialog.getByRole('button', { name: 'Enregistrer le brouillon', exact: true }).click();
  let quote = await saved(created, 201);
  expect(quote).toMatchObject({ service_request: data.record.id, client: { id: data.company.id } });
  expect(quote.amounts).toMatchObject({ subtotal_ht: '37.913', discount_ht: '2.843', net_ht: '35.070', vat_amount: '6.663', total_ttc: '41.733' });
  expect(quote.client_reference).toBe(data.record.client_reference);
  dialog = page.getByRole('dialog', { name: 'Devis de réparation', exact: true });
  await expect(dialog.getByRole('button', { name: 'Envoyer au client', exact: true })).toBeEnabled();

  const otherTerms = `Conditions concurrentes fictives ${data.tag}.`;
  const other = await api(page, `repair-quotes/${quote.id}/`, 'PATCH', { expected_revision: quote.revision, terms: otherTerms });
  await dialog.getByLabel('Conditions / notes publiques', { exact: true }).fill(`${input.terms} Correction locale.`);
  const stale = mutation(page, `repair-quotes/${quote.id}/`, 'PATCH');
  await dialog.getByRole('button', { name: 'Enregistrer le brouillon', exact: true }).click();
  expect((await stale).status()).toBe(409);
  await expect(dialog.getByText('Le devis a changé depuis le début de votre saisie.', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: 'Recharger le brouillon', exact: true }).click();
  const reloaded = page.waitForResponse(result => new URL(result.url()).pathname === `/api/repair-quotes/${quote.id}/` && result.request().method() === 'GET');
  await dialog.getByRole('button', { name: 'Confirmer le rechargement', exact: true }).click();
  expect((await reloaded).status()).toBe(200);
  await expect(dialog.getByLabel('Conditions / notes publiques', { exact: true })).toHaveValue(otherTerms);
  await dialog.getByLabel('Conditions / notes publiques', { exact: true }).fill(input.terms);
  const corrected = mutation(page, `repair-quotes/${quote.id}/`, 'PATCH');
  await dialog.getByRole('button', { name: 'Enregistrer le brouillon', exact: true }).click();
  quote = await saved(corrected);
  expect(quote.revision).toBe(other.revision + 1);
  const issued = mutation(page, `repair-quotes/${quote.id}/issue/`);
  await dialog.getByRole('button', { name: 'Envoyer au client', exact: true }).click();
  quote = await saved(issued, 201);
  expect(quote).toMatchObject({ state: 'issued', decision: 'pending', is_current: true });
  await expect(page.getByRole('dialog', { name: 'Devis de réparation', exact: true }).getByRole('link', { name: 'Télécharger le devis PDF', exact: true })).toHaveAttribute('href', quote.pdf_url);
  const document = await pdf(page, quote);
  for (const value of [quote.reference, data.record.reference, data.record.client_reference, data.company.name,
    data.equipment.serial_number, '37.913 TND', '-2.843 TND', '35.070 TND', '6.663 TND', '41.733 TND', input.terms])
    expect(document.text).toContain(value);
  expect(document.text).toContain('Devis de réparation');
  expect(document.text).not.toContain(data.company.notes);
  expect(document.text).not.toContain(data.record.description);
  expect(hash((await pdf(page, quote)).bytes)).toBe(hash(document.bytes));
  expect((await response(page, `repair-quotes/${quote.id}/`, 'PATCH', { expected_revision: quote.revision, discount_value: '100' })).status()).toBe(409);
  const record = await api(page, `requests/${data.record.id}/`);
  expect(record).toMatchObject({ status: 'quote_sent', closed_at: null });
  expect(record.disposition?.finance_validated_at ?? null).toBeNull();
  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = page.getByRole('dialog', { name: 'Devis de réparation', exact: true });
  await mobile.getByRole('heading', { name: quote.reference, exact: true }).scrollIntoViewIfNeeded();
  const bounds = await mobile.evaluate(element => ({ left: element.getBoundingClientRect().left,
    right: element.getBoundingClientRect().right, viewport: innerWidth,
    content: element.querySelector('.repair-quotes-detail')?.scrollWidth,
    width: element.querySelector('.repair-quotes-detail')?.clientWidth }));
  expect(bounds.left).toBeGreaterThanOrEqual(0);
  expect(bounds.right).toBeLessThanOrEqual(bounds.viewport);
  expect(bounds.content).toBeLessThanOrEqual(bounds.width + 2);
  await page.screenshot({ path: '../../.local/repair-quote-mobile-viewport.png' });
});

test('le client change d’avis sur le devis courant et une nouvelle révision de prix exige un nouvel accord sans réécrire les PDF', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const data = await fixture(page, marker());
  let first = await issue(page, await draft(page, data));
  const firstPDF = await pdf(page, first);
  const customer = await api(page, 'users/', 'POST', { username: `devis-client-${data.tag}`, first_name: 'Client fictif devis', role: 'client', client: data.company.id, password });
  const context = await browser.newContext(), portal = await context.newPage();
  try {
    await login(portal, customer.username);
    let detail = await openQuote(portal, first, true);
    await expect(detail).toContainText(data.record.client_reference);
    await detail.getByRole('button', { name: 'Accepter le devis', exact: true }).click();
    await portal.getByRole('dialog', { name: 'Accepter le devis', exact: true }).getByRole('button', { name: 'Annuler', exact: true }).click();
    expect((await api(portal, `repair-quotes/${first.id}/`)).decision).toBe('pending');
    const originalRevision = first.decision_revision;
    first = await decideViaUI(portal, first, 'accepted');
    const stale = await response(portal, `repair-quotes/${first.id}/decision/`, 'POST', { request_key: randomUUID(), expected_revision: originalRevision, decision: 'refused' });
    expect(stale.status()).toBe(409);
    first = await decideViaUI(portal, first, 'refused');
    first = await decideViaUI(portal, first, 'accepted');
    expect(first.history.map(row => row.decision)).toEqual(['accepted', 'refused', 'accepted']);
    expect((await api(page, `requests/${data.record.id}/`)).status).toBe('to_repair');
    expect(hash((await pdf(portal, first)).bytes)).toBe(hash(firstPDF.bytes));

    const adminDetail = await openQuote(page, first);
    await adminDetail.getByRole('button', { name: 'Créer une nouvelle révision', exact: true }).click();
    const revision = page.getByRole('dialog', { name: 'Créer un devis de réparation', exact: true });
    await revision.getByLabel('Prix unitaire HT de la ligne 1', { exact: true }).fill('20.000');
    await revision.getByLabel('Type de remise', { exact: true }).selectOption('fixed');
    await revision.getByLabel('Montant de remise HT (TND)', { exact: true }).fill('1.000');
    const created = mutation(page, 'repair-quotes/');
    await revision.getByRole('button', { name: 'Enregistrer le brouillon', exact: true }).click();
    let second = await saved(created, 201);
    expect((await api(portal, `repair-quotes/${first.id}/`))).toMatchObject({ decision: 'accepted', is_current: true });
    expect((await api(portal, 'repair-quotes/')).map(quote => quote.id)).toEqual([first.id]);
    const issued = mutation(page, `repair-quotes/${second.id}/issue/`);
    await page.getByRole('dialog', { name: 'Devis de réparation', exact: true }).getByRole('button', { name: 'Envoyer au client', exact: true }).click();
    second = await saved(issued, 201);
    expect(second).toMatchObject({ version: first.version + 1, decision: 'pending', history: [], is_current: true });
    expect(second.amounts).toMatchObject({ subtotal_ht: '62.600', discount_ht: '1.000', net_ht: '61.600', vat_amount: '11.704', total_ttc: '73.304' });
    expect((await api(page, `requests/${data.record.id}/`)).status).toBe('quote_sent');
    detail = portal.getByRole('dialog', { name: 'Devis de réparation', exact: true });
    await detail.getByRole('button', { name: 'Actualiser le devis', exact: true }).click();
    await expect(detail).toContainText('Cette version a été remplacée.');
    await expect(detail.getByRole('button', { name: 'Changer d’avis', exact: true })).toHaveCount(0);
    expect((await response(portal, `repair-quotes/${first.id}/decision/`, 'POST', { request_key: randomUUID(), expected_revision: second.decision_revision, decision: 'accepted' })).status()).toBe(409);
    await detail.getByRole('button', { name: 'Fermer', exact: true }).first().click();
    await openQuote(portal, second, true);
    await expect(portal.getByRole('dialog', { name: 'Devis de réparation', exact: true })).toContainText('Aucune réponse enregistrée pour cette version.');
    second = await decideViaUI(portal, second, 'accepted');
    expect(second.history).toHaveLength(1);
    expect(hash((await pdf(portal, first)).bytes)).toBe(hash(firstPDF.bytes));
    const secondPDF = await pdf(portal, second);
    expect(secondPDF.text).toContain('73.304 TND');
    expect(hash(secondPDF.bytes)).not.toBe(hash(firstPDF.bytes));
    const notices = await api(portal, 'logistics/notifications/');
    expect(notices.results.some(item => item.target === 'repair_quote' && item.target_id === second.id)).toBe(true);
  } finally { await context.close(); }
});

test('les devis de deux centres partageant la même référence restent isolés, les prix invalides sont rejetés et une remise totale ne facture rien', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker(), sharedReference = `000-PARTENAIRE-${tag}`;
  const data = await fixture(page, `${tag}-A`, sharedReference), foreign = await fixture(page, `${tag}-B`, sharedReference);
  const ownQuote = await issue(page, await draft(page, data)), foreignQuote = await issue(page, await draft(page, foreign));
  const customer = await api(page, 'users/', 'POST', { username: `devis-scope-${tag}`, role: 'client', client: data.company.id, password });
  const courier = await api(page, 'users/', 'POST', { username: `devis-courier-${tag}`, role: 'courier', password });
  const manager = await api(page, 'users/', 'POST', { username: `devis-manager-${tag}`, role: 'manager', password });
  const context = await browser.newContext(), driverContext = await browser.newContext(), managerContext = await browser.newContext();
  const portal = await context.newPage(), driver = await driverContext.newPage(), supervisor = await managerContext.newPage();
  try {
    await login(portal, customer.username);
    await navigateQuotes(portal, true);
    await portal.getByLabel('Rechercher un devis', { exact: true }).fill(sharedReference);
    await expect(portal.locator('.repair-quotes-card')).toHaveCount(1);
    await expect(portal.locator('.repair-quotes-card')).toContainText(ownQuote.reference);
    await expect(portal.locator('.repair-quotes-card')).not.toContainText(foreign.company.name);
    await expect(portal.getByRole('button', { name: 'Créer un devis', exact: true })).toHaveCount(0);
    for (const path of [`repair-quotes/${foreignQuote.id}/`, `repair-quotes/${foreignQuote.id}/pdf/`])
      expect((await response(portal, path)).status()).toBe(404);
    expect((await response(portal, `repair-quotes/${foreignQuote.id}/decision/`, 'POST', { request_key: randomUUID(), expected_revision: foreignQuote.decision_revision, decision: 'accepted' })).status()).toBe(404);
    expect((await response(portal, `repair-quotes/${ownQuote.id}/decision/`, 'POST', { request_key: randomUUID(), expected_revision: ownQuote.decision_revision, decision: 'accepted', actor: 1, discount_value: '100' })).status()).toBe(400);
    expect((await api(portal, `repair-quotes/${ownQuote.id}/`)).decision).toBe('pending');
    await login(driver, courier.username, true);
    for (const path of ['repair-quotes/', `repair-quotes/${ownQuote.id}/`, `repair-quotes/${ownQuote.id}/pdf/`])
      expect((await response(driver, path)).status()).toBe(403);
    await login(supervisor, manager.username);
    expect((await response(supervisor, `repair-quotes/${ownQuote.id}/decision/`, 'POST', { request_key: randomUUID(), expected_revision: ownQuote.decision_revision, decision: 'accepted' })).status()).toBe(403);
    const before = await api(page, `repair-quotes/?service_request=${data.record.id}`);
    for (const invalid of [
      { discount_kind: 'fixed', discount_value: '37.914' },
      { discount_kind: 'percent', discount_value: '7.555' },
      { vat_rate: 'NaN' },
      { lines: [{ description: 'Prix fictif invalide', quantity: '1', unit_ht: 1.5 }] },
      { lines: [{ description: 'Prix fictif invalide', quantity: '1', unit_ht: '1e2' }] },
    ]) {
      const rejected = await response(page, 'repair-quotes/', 'POST', { request_key: randomUUID(), service_request: data.record.id, ...quoteInput(), ...invalid });
      expect(rejected.status(), await rejected.text()).toBe(400);
    }
    expect((await api(page, `repair-quotes/?service_request=${data.record.id}`)).map(row => row.id)).toEqual(before.map(row => row.id));
    const full = await issue(supervisor, await draft(supervisor, data, { discount_kind: 'percent', discount_value: '100' }));
    expect(full.amounts).toMatchObject({ fully_discounted: true, net_ht: '0.000', vat_amount: '0.000', total_ttc: '0.000' });
    expect(full.decision).toBe('pending');
    expect((await pdf(supervisor, full)).text).toContain('REMISE TOTALE');
    const record = await api(page, `requests/${data.record.id}/`);
    expect(record).toMatchObject({ status: 'quote_sent', closed_at: null });
    expect(record.disposition?.finance_validated_at ?? null).toBeNull();
    expect(record.exchange?.billing_validated_at ?? null).toBeNull();
  } finally { await Promise.all([context.close(), driverContext.close(), managerContext.close()]); }
});

test('À facturer donne au technicien confirmé un devis envoyé au client, et une réaffectation retire immédiatement ses droits', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const data = await fixture(page, marker());
  const technician = await api(page, 'users/', 'POST', {
    username: `devis-technicien-${data.tag}`, first_name: 'Technicien devis fictif', role: 'technician', password,
  });
  const replacement = await api(page, 'users/', 'POST', {
    username: `devis-relais-${data.tag}`, first_name: 'Technicien relais fictif', role: 'technician', password,
  });
  const customer = await api(page, 'users/', 'POST', {
    username: `devis-destinataire-${data.tag}`, role: 'client', client: data.company.id, password,
  });
  const assigned = await api(page, `requests/${data.record.id}/assignment/`, 'POST', {
    technician: technician.id, expected_revision: 0,
  });
  const techContext = await browser.newContext(), clientContext = await browser.newContext();
  const tech = await techContext.newPage(), portal = await clientContext.newPage();
  try {
    await login(tech, technician.username);
    const premature = await response(tech, 'repair-quotes/', 'POST', {
      request_key: randomUUID(), service_request: data.record.id, ...quoteInput(),
    });
    expect(premature.status()).toBe(403);
    await openRequestsWorkspace(tech);
    await tech.getByLabel('Rechercher une demande', { exact: true }).fill(data.record.reference);
    await tech.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
    const row = tech.locator('tbody tr').filter({ hasText: data.record.reference });
    await expect(row).toHaveCount(1);
    await expect(row.getByRole('button', { name: `Créer un devis pour ${data.record.reference}`, exact: true })).toHaveCount(0);
    await row.getByRole('button', { name: `Ouvrir ${data.record.reference}`, exact: true }).click();
    const dossier = tech.getByRole('dialog', { name: 'Dossier SAV', exact: true });
    await expect(dossier.getByRole('button', { name: 'Créer un devis', exact: true })).toHaveCount(0);
    await dossier.getByRole('button', { name: 'Confirmer la prise en charge', exact: true }).click();
    const confirmation = tech.getByRole('alertdialog', { name: 'Confirmer la prise en charge', exact: true });
    const acceptance = mutation(tech, `requests/${data.record.id}/assignment/confirm/`);
    await confirmation.getByRole('button', { name: 'Oui', exact: true }).click();
    expect((await saved(acceptance)).assignment.accepted).toBe(true);
    const status = dossier.getByLabel('État du dossier', { exact: true });
    await expect(status.locator('option[value="quotation"]')).toHaveText('À facturer');
    await status.selectOption('quotation');
    await dossier.getByLabel('Observation', { exact: true }).fill(`Chiffrage nécessaire pour cette réparation hors garantie ${data.tag}.`);
    const followed = mutation(tech, `requests/${data.record.id}/followup/`);
    await dossier.getByRole('button', { name: 'Enregistrer le suivi', exact: true }).click();
    expect((await saved(followed, 201)).request.status).toBe('quotation');
    await expect(dossier.locator('.request-dossier-heading .badge')).toHaveText('À facturer');
    await dossier.getByRole('button', { name: 'Fermer', exact: true }).first().click();
    await expect(row).toContainText('À facturer');
    const categories = await api(tech, 'requests/categories/');
    expect(categories.categories.find(item => item.key === 'quotation')?.label).toBe('À facturer');
    const contextRead = tech.waitForResponse(result => new URL(result.url()).pathname === `/api/requests/${data.record.id}/` && result.request().method() === 'GET');
    await row.getByRole('button', { name: `Créer un devis pour ${data.record.reference}`, exact: true }).click();
    expect((await contextRead).status()).toBe(200);
    const creation = tech.getByRole('dialog', { name: 'Créer un devis de réparation', exact: true });
    await expect(creation.getByLabel('Dossier SAV concerné', { exact: true })).toHaveValue(String(data.record.id));
    await creation.getByLabel('Devise du devis', { exact: true }).selectOption('TND');
    await creation.getByLabel('Taux de TVA du devis (%)', { exact: true }).fill('19');
    await creation.getByLabel('Description de la ligne 1', { exact: true }).fill('Réparation hors garantie fictive');
    await creation.getByLabel('Quantité de la ligne 1', { exact: true }).fill('1');
    await creation.getByLabel('Prix unitaire HT de la ligne 1', { exact: true }).fill('100.000');
    const created = mutation(tech, 'repair-quotes/');
    await creation.getByRole('button', { name: 'Enregistrer le brouillon', exact: true }).click();
    let quote = await saved(created, 201);
    expect(quote).toMatchObject({ service_request: data.record.id, can_edit: true, can_issue: true, state: 'draft' });
    const detail = tech.getByRole('dialog', { name: 'Devis de réparation', exact: true });
    const issued = mutation(tech, `repair-quotes/${quote.id}/issue/`);
    await detail.getByRole('button', { name: 'Envoyer au client', exact: true }).click();
    quote = await saved(issued, 201);
    expect(quote).toMatchObject({ state: 'issued', decision: 'pending', is_current: true });
    expect(quote.amounts.total_ttc).toBe('119.000');
    expect((await pdf(tech, quote)).text).toContain(data.record.client_reference);

    await login(portal, customer.username);
    await portal.getByRole('button', { name: 'Notifications et rappels', exact: true }).click();
    const notifications = portal.getByRole('dialog', { name: 'Notifications et rappels', exact: true });
    const notice = notifications.locator('.notification-list article').filter({ hasText: quote.reference });
    await expect(notice).toHaveCount(1);
    await notice.getByRole('button', { name: 'Voir le devis', exact: true }).click();
    const customerDetail = portal.getByRole('dialog', { name: 'Devis de réparation', exact: true });
    await expect(customerDetail).toContainText(quote.reference);
    await expect(customerDetail).toContainText(data.record.client_reference);
    quote = await decideViaUI(portal, quote, 'accepted');
    quote = await decideViaUI(portal, quote, 'refused');
    expect(quote.history.map(item => item.decision)).toEqual(['accepted', 'refused']);
    expect((await api(page, `requests/${data.record.id}/`)).status).toBe('rejected');

    // An open draft never grants its former technician rights after a handoff.
    const next = await draft(tech, data);
    await api(page, `requests/${data.record.id}/assignment/`, 'POST', {
      technician: replacement.id, expected_revision: assigned.assignment.revision,
    });
    for (const action of [
      ['PATCH', `repair-quotes/${next.id}/`, { expected_revision: next.revision, terms: 'Modification devenue interdite.' }],
      ['POST', `repair-quotes/${next.id}/issue/`, { expected_revision: next.revision, request_key: randomUUID() }],
      ['POST', 'repair-quotes/', { request_key: randomUUID(), service_request: data.record.id, ...quoteInput() }],
    ]) {
      const denied = await response(tech, action[1], action[0], action[2]);
      expect([403, 404]).toContain(denied.status());
    }
    expect((await api(page, `repair-quotes/${next.id}/`))).toMatchObject({ state: 'draft', terms: quoteInput().terms });
    expect((await api(portal, 'repair-quotes/')).map(item => item.id)).toEqual([quote.id]);
  } finally { await Promise.all([techContext.close(), clientContext.close()]); }
});

test('l’accueil client présente seulement ses devis courants à confirmer puis son accord classe le dossier À réparer et prévient l’admin', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker(), clientReference = `000-ACCUEIL-${tag}`;
  const data = await fixture(page, `${tag}-ACCUEIL`, clientReference);
  const foreign = await fixture(page, `${tag}-AUTRE-CENTRE`, clientReference);
  const technician = await api(page, 'users/', 'POST', {
    username: `accueil-technicien-${tag}`, first_name: 'Technicien accueil fictif', role: 'technician', password,
  });
  const customer = await api(page, 'users/', 'POST', {
    username: `accueil-client-${tag}`, role: 'client', client: data.company.id, password,
  });
  const assigned = await api(page, `requests/${data.record.id}/assignment/`, 'POST', {
    technician: technician.id, expected_revision: 0,
  });
  const techContext = await browser.newContext(), customerContext = await browser.newContext();
  const tech = await techContext.newPage(), portal = await customerContext.newPage();
  async function homeInbox() {
    const detail = portal.getByRole('dialog', { name: 'Devis de réparation', exact: true });
    if (await detail.isVisible()) await detail.getByRole('button', { name: 'Fermer', exact: true }).first().click();
    const navigation = portal.getByRole('navigation', { name: 'Navigation principale', exact: true });
    const menu = portal.getByRole('button', { name: 'Ouvrir le menu', exact: true });
    if (await menu.isVisible() && !await portal.locator('.sidebar.open').count()) await menu.click();
    await navigation.getByRole('button', { name: 'Tableau de bord', exact: true }).click();
    await expect(portal.getByRole('heading', { name: 'Tableau de bord', exact: true })).toBeVisible();
    const inbox = portal.locator('.customer-quote-inbox');
    await expect(inbox.getByRole('heading', { name: /^Devis à confirmer(?:\s|$)/ })).toBeVisible();
    const refreshed = portal.waitForResponse(result => new URL(result.url()).pathname === '/api/dashboard/' && result.request().method() === 'GET');
    await inbox.getByRole('button', { name: 'Actualiser les devis à confirmer', exact: true }).click();
    expect((await refreshed).status()).toBe(200);
    return inbox;
  }
  try {
    await login(tech, technician.username);
    await api(tech, `requests/${data.record.id}/assignment/confirm/`, 'POST', {
      expected_revision: assigned.assignment.revision, accept: true,
    });
    const superseded = await issue(page, await draft(page, data));
    let current = await issue(page, await draft(page, data, { terms: 'Version courante fictive à confirmer.' }));
    const prepared = await draft(page, data, { terms: 'Brouillon suivant non envoyé.' });
    const foreignQuote = await issue(page, await draft(page, foreign));
    const draftEquipment = await api(page, 'equipment/', 'POST', {
      client: data.company.id, serial_number: `${tag}-BROUILLON-SEUL`, model: 'Autre onduleur fictif',
    });
    const draftRecord = await api(page, 'requests/', 'POST', {
      equipment: draftEquipment.id, subject: 'Dossier fictif sans devis envoyé', client_reference: `${clientReference}-BROUILLON`,
    });
    const unpublished = await draft(page, { record: draftRecord });
    expect((await api(page, `requests/${data.record.id}/`)).status).toBe('quote_sent');

    await login(portal, customer.username);
    let inbox = await homeInbox();
    const pending = (await api(portal, 'dashboard/')).pending_repair_quotes;
    expect(pending.count).toBe(1);
    expect(pending.results.map(item => item.id)).toEqual([current.id]);
    await expect(inbox.locator('.customer-quote-inbox-card')).toHaveCount(1);
    const card = inbox.locator('.customer-quote-inbox-card');
    for (const text of [current.reference, data.record.client_reference, data.equipment.serial_number]) await expect(card).toContainText(text);
    await expect(card).toContainText(/41,733\s*TND/);
    for (const text of [superseded.reference, foreignQuote.reference, foreign.company.name, draftEquipment.serial_number]) await expect(inbox).not.toContainText(text);
    expect((await api(portal, 'repair-quotes/')).map(item => item.id)).not.toContain(prepared.id);
    expect((await api(portal, 'repair-quotes/')).map(item => item.id)).not.toContain(unpublished.id);
    await inbox.getByRole('button', { name: 'Voir les devis à confirmer', exact: true }).click();
    await expect(portal.getByRole('heading', { name: 'Mes devis', exact: true })).toBeVisible();
    await expect(portal.getByLabel('État des devis', { exact: true })).toHaveValue('pending');
    await expect(portal.locator('.repair-quotes-card')).toHaveCount(1);
    await expect(portal.locator('.repair-quotes-card')).toContainText(current.reference);
    inbox = await homeInbox();
    const prominence = await inbox.evaluate(element => ({ top: element.getBoundingClientRect().top,
      metricsTop: document.querySelector('.metric-value')?.getBoundingClientRect().top }));
    expect(prominence.top).toBeLessThan(prominence.metricsTop);
    await portal.setViewportSize({ width: 390, height: 844 });
    const bounds = await card.evaluate(element => ({ left: element.getBoundingClientRect().left,
      right: element.getBoundingClientRect().right, viewport: innerWidth,
      width: element.clientWidth, content: element.scrollWidth }));
    expect(bounds.left).toBeGreaterThanOrEqual(0);
    expect(bounds.right).toBeLessThanOrEqual(bounds.viewport);
    expect(bounds.content).toBeLessThanOrEqual(bounds.width + 2);
    await portal.screenshot({ path: '../../.local/customer-pending-quotes-mobile.png', animations: 'disabled' });
    await inbox.screenshot({ path: '../../.local/customer-pending-quotes-mobile-section.png', animations: 'disabled' });
    await card.getByRole('button', { name: `Confirmer le devis ${current.reference}`, exact: true }).click();
    await expect(portal.getByRole('dialog', { name: 'Devis de réparation', exact: true })).toContainText(current.reference);
    current = await decideViaUI(portal, current, 'accepted');
    expect((await api(page, `requests/${data.record.id}/`)).status).toBe('to_repair');
    // A second accepted but unassigned dossier makes the global and own counts
    // deliberately different, independent of previous browser test fixtures.
    const unassignedQuote = await issue(page, unpublished);
    await api(portal, `repair-quotes/${unassignedQuote.id}/decision/`, 'POST', {
      request_key: randomUUID(), expected_revision: unassignedQuote.decision_revision, decision: 'accepted',
    });
    inbox = await homeInbox();
    await expect(inbox.locator('.customer-quote-inbox-card')).toHaveCount(0);
    expect((await api(portal, 'dashboard/')).pending_repair_quotes.count).toBe(0);

    const techHomeRead = tech.waitForResponse(result => new URL(result.url()).pathname === '/api/dashboard/' && result.request().method() === 'GET');
    await tech.getByRole('button', { name: 'Actualiser les dossiers de devis', exact: true }).click();
    const techHome = await (await techHomeRead).json();
    expect(techHome.metrics.to_repair_requests).toBe(1);
    const ownQueueRead = tech.waitForResponse(result => {
      const url = new URL(result.url());
      return url.pathname === '/api/requests/' && result.request().method() === 'GET'
        && url.searchParams.get('assigned_technician') === String(technician.id)
        && url.searchParams.get('category') === 'to_repair';
    });
    await tech.getByRole('button', { name: 'Voir mes dossiers à réparer', exact: true }).click();
    const ownQueue = await (await ownQueueRead).json();
    expect(ownQueue.map(record => record.id)).toEqual([data.record.id]);
    await expect(tech.getByRole('heading', { name: 'Demandes SAV', exact: true })).toBeVisible();
    expect(new URL(tech.url()).hash).toBe('#requests/to_repair/mine');
    await expect(tech.getByRole('group', { name: 'Catégories des demandes SAV', exact: true }).getByRole('button', { name: /^À réparer / })).toHaveAttribute('aria-pressed', 'true');
    await tech.getByLabel('Rechercher une demande', { exact: true }).fill(data.record.reference);
    await tech.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
    const repairRow = tech.locator('tbody tr').filter({ hasText: data.record.reference });
    await expect(repairRow).toHaveCount(1);
    await expect(repairRow).toContainText('À réparer');
    const ownSidebarCount = tech.getByRole('button', { name: 'Demandes : À réparer', exact: true }).locator('.nav-subcount');
    await expect(ownSidebarCount).toHaveText('1');
    const globalCount = (await api(tech, 'requests/categories/')).categories.find(item => item.key === 'to_repair').count;
    expect(globalCount).toBeGreaterThanOrEqual(2);
    await tech.getByRole('navigation', { name: 'Navigation principale', exact: true }).getByRole('button', { name: 'Tableau de bord', exact: true }).click();
    let releaseGlobalCount, reportGlobalCount;
    const countHeld = new Promise(resolve => { releaseGlobalCount = resolve; });
    const countStarted = new Promise(resolve => { reportGlobalCount = resolve; });
    const countPattern = '**/api/requests/categories/**';
    const holdGlobalCount = async route => {
      const url = new URL(route.request().url());
      if (!url.searchParams.has('assigned_technician')) {
        reportGlobalCount();
        await countHeld;
      }
      await route.continue();
    };
    await tech.route(countPattern, holdGlobalCount);
    try {
      await openRequestsWorkspace(tech);
      await countStarted;
      const globalSidebarCount = tech.getByRole('button', { name: 'Demandes : À réparer', exact: true }).locator('.nav-subcount');
      await expect(globalSidebarCount).toHaveText('—');
      releaseGlobalCount();
      await expect(globalSidebarCount).toHaveText(String(globalCount));
      expect(new URL(tech.url()).hash).toBe('#requests');
    } finally {
      releaseGlobalCount();
      await tech.unroute(countPattern, holdGlobalCount);
    }
    const notices = await api(page, 'logistics/notifications/');
    const acceptedNotice = notices.results.find(item => item.target === 'repair_quote' && item.target_id === current.id && item.title === 'Devis accepté');
    expect(acceptedNotice).toBeTruthy();
    expect(acceptedNotice.body).toContain('accepté par le client');
    await page.getByRole('button', { name: 'Notifications et rappels', exact: true }).click();
    const notifications = page.getByRole('dialog', { name: 'Notifications et rappels', exact: true });
    const adminNotice = notifications.locator('.notification-list article').filter({ hasText: current.reference }).filter({ hasText: 'Devis accepté' });
    await expect(adminNotice).toHaveCount(1);
    await expect(adminNotice).toContainText('accepté par le client');

    await portal.setViewportSize({ width: 1440, height: 1000 });
    await openQuote(portal, current, true);
    current = await decideViaUI(portal, current, 'refused');
    expect((await api(page, `requests/${data.record.id}/`)).status).toBe('rejected');
    inbox = await homeInbox();
    await expect(inbox.locator('.customer-quote-inbox-card')).toHaveCount(0);
    const next = await issue(page, prepared);
    expect((await api(page, `requests/${data.record.id}/`)).status).toBe('quote_sent');
    inbox = await homeInbox();
    await expect(inbox.locator('.customer-quote-inbox-card')).toHaveCount(1);
    await expect(inbox).toContainText(next.reference);
    await expect(inbox).not.toContainText(current.reference);
    expect((await api(portal, 'dashboard/')).pending_repair_quotes.results.map(item => item.id)).toEqual([next.id]);
    const oldOpinion = (await api(page, 'logistics/notifications/')).results.find(item => item.id === acceptedNotice.id);
    expect(oldOpinion).toMatchObject({ title: 'Devis accepté', body: acceptedNotice.body });
  } finally { await Promise.all([techContext.close(), customerContext.close()]); }
});
