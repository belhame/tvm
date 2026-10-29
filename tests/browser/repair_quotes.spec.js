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
  await expect(dialog.getByRole('button', { name: 'Émettre le devis', exact: true })).toBeEnabled();

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
  await dialog.getByRole('button', { name: 'Émettre le devis', exact: true }).click();
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
  expect(record).toMatchObject({ status: 'quotation', closed_at: null });
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
    expect((await api(page, `requests/${data.record.id}/`)).status).toBe('approved');
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
    await page.getByRole('dialog', { name: 'Devis de réparation', exact: true }).getByRole('button', { name: 'Émettre le devis', exact: true }).click();
    second = await saved(issued, 201);
    expect(second).toMatchObject({ version: first.version + 1, decision: 'pending', history: [], is_current: true });
    expect(second.amounts).toMatchObject({ subtotal_ht: '62.600', discount_ht: '1.000', net_ht: '61.600', vat_amount: '11.704', total_ttc: '73.304' });
    expect((await api(page, `requests/${data.record.id}/`)).status).toBe('quotation');
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
    expect(record).toMatchObject({ status: 'quotation', closed_at: null });
    expect(record.disposition?.finance_validated_at ?? null).toBeNull();
    expect(record.exchange?.billing_validated_at ?? null).toBeNull();
  } finally { await Promise.all([context.close(), driverContext.close(), managerContext.close()]); }
});
