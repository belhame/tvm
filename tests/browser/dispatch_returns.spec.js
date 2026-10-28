import { test, expect } from '@playwright/test';
import { confirmCurrentAssignment, openLegacyDashboard } from './legacy_navigation.js';
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

async function reload(page) {
  const loaded = page.waitForResponse(result => result.url().endsWith('/api/dashboard/') && result.ok());
  await page.reload();
  await loaded;
  await openLegacyDashboard(page);
}

async function navigate(page, label) {
  const navigation = page.getByRole('navigation', { name: 'Navigation principale' });
  if (!await navigation.isVisible()) await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await navigation.getByText(label, { exact: true }).click();
}

function marker(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function dispositionPath(record, action = '') {
  return `requests/${record.id}/disposition/${action ? `${action}/` : ''}`;
}

async function fixture(page, tag, { status = 'testing', assignedTechnician = null } = {}) {
  const company = await api(page, 'clients/', 'POST', {
    name: `Laboratoire retour fictif ${tag}`, tax_id: `000-FISC-${tag}`,
    notes: `NOTE-CLIENT-INTERNE-${tag}`, email: `test-${Date.now()}@example.invalid`,
  });
  const equipment = await api(page, 'equipment/', 'POST', {
    client: company.id, serial_number: `${tag}-SERIE`, model: 'Onduleur de laboratoire fictif', brand: 'Eaton',
  });
  const request = await api(page, 'requests/', 'POST', {
    equipment: equipment.id, subject: `Validation fictive ${tag}`, description: `Signalement de laboratoire ${tag}.`,
    client_reference: `000-CLIENT-${tag}`, status,
    ...(assignedTechnician ? { assigned_technician: assignedTechnician } : {}),
  });
  return { company, equipment, request };
}

async function openDossier(page, record) {
  await navigate(page, 'Demandes SAV');
  await page.getByRole('group', { name: 'Catégories des demandes SAV', exact: true }).getByRole('button', { name: /^Tous/ }).click();
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(record.reference);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  await page.getByRole('button', { name: `Ouvrir ${record.reference}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Dossier SAV', exact: true });
  await dialog.getByRole('tab', { name: 'Livraison / Retour', exact: true }).click();
  return dialog;
}

async function dispatch(page, query) {
  await navigate(page, 'Livraisons & retours');
  await expect(page.getByRole('heading', { name: 'Livraisons & retours', exact: true })).toBeVisible();
  await page.getByLabel('Rechercher une livraison ou un retour', { exact: true }).fill(query);
}

async function openReturn(page, record) {
  await dispatch(page, record.reference);
  await page.getByRole('region', { name: 'À retourner au client', exact: true }).getByRole('button', { name: `Ouvrir le suivi ${record.reference}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Livraison ou retour client', exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}

function mutationResponse(page, record, action, method = 'POST') {
  return page.waitForResponse(result => result.url().endsWith(`/api/${dispositionPath(record, action)}`) && result.request().method() === method);
}

async function mutation(pending) {
  const result = await pending;
  expect(result.status(), await result.text()).toBe(200);
  return result.json();
}

function pdfText(bytes) {
  const extracted = spawnSync('pdftotext', ['-', '-'], { input: bytes, encoding: 'utf8', timeout: 10000, maxBuffer: 4 * 1024 * 1024 });
  if (!extracted.error) {
    expect(extracted.status, extracted.stderr).toBe(0);
    return extracted.stdout;
  }
  if (extracted.error.code !== 'ENOENT') throw extracted.error;
  const python = process.env.TVM_E2E_PYTHON || fileURLToPath(new URL('../../.venv/bin/python', import.meta.url));
  const fallback = spawnSync(python, ['-c', 'import io,sys; from pypdf import PdfReader; print("\\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(sys.stdin.buffer.read())).pages))'], {
    input: bytes, encoding: 'utf8', timeout: 10000, maxBuffer: 4 * 1024 * 1024,
  });
  if (fallback.error) throw fallback.error;
  expect(fallback.status, fallback.stderr).toBe(0);
  return fallback.stdout;
}

async function quotePdf(page, quote) {
  const result = await page.request.get(quote.pdf_url);
  expect(result.status()).toBe(200);
  expect(result.headers()['content-type']).toContain('application/pdf');
  expect(result.headers()['cache-control']).toContain('no-store');
  const bytes = await result.body();
  expect(bytes.subarray(0, 5).toString()).toBe('%PDF-');
  return pdfText(bytes);
}

async function prepareQuote(page, record, fields) {
  await api(page, dispositionPath(record), 'PATCH', fields);
  return api(page, dispositionPath(record, 'quote/issue'), 'POST', {});
}

test('des tests réussis et un échange validé rejoignent la même file Prêts à être livrés sans fausse validation préalable', async ({ page }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('Livraison-fictive');
  const repaired = await fixture(page, `${tag}-REPARE`);
  const exchanged = await fixture(page, `${tag}-ECHANGE`, { status: 'exchange' });
  const { as_of: today } = await api(page, 'requests/categories/');
  const rejected = await response(page, dispositionPath(repaired.request, 'repair'), 'POST', {
    diagnosis: 'Tests non validés ; ceci ne doit pas rendre le matériel livrable.', tests_passed: false, tested_on: today,
  });
  expect(rejected.status()).toBe(400);
  expect((await api(page, `requests/${repaired.request.id}/`)).status).toBe('testing');

  await reload(page);
  const dialog = await openDossier(page, repaired.request);
  await dialog.getByRole('button', { name: 'Tests validés — Réparé', exact: true }).click();
  await dialog.getByRole('textbox', { name: 'Synthèse technique des tests', exact: true }).fill(`Tests de charge fictifs réellement confirmés ${tag}`);
  await dialog.getByLabel(/^Date des tests/).fill(today);
  const passed = dialog.getByRole('checkbox', { name: 'Je confirme que les tests de fonctionnement sont réussis.', exact: true });
  await expect(passed).not.toBeChecked();
  await expect(dialog.getByRole('button', { name: 'Confirmer la réparation et mettre prêt à livrer', exact: true })).toBeDisabled();
  await passed.check();
  const repairedResponse = mutationResponse(page, repaired.request, 'repair');
  await dialog.getByRole('button', { name: 'Confirmer la réparation et mettre prêt à livrer', exact: true }).click();
  const readyRepair = await mutation(repairedResponse);
  expect(readyRepair).toMatchObject({ status: 'ready_for_delivery', equipment: repaired.equipment.id, closed_at: null, disposition: { outcome: 'repaired', state: 'ready_for_delivery', tests_passed: true, tested_on: today } });
  await dialog.getByRole('button', { name: 'Fermer', exact: true }).first().click();

  await api(page, `requests/${exchanged.request.id}/exchange/`, 'PATCH', {
    replacement_serial_number: `${tag}-REMPLACEMENT`, replacement_model: 'Remplacement fictif pour livraison commune', replacement_brand: 'Eaton',
  });
  const readyExchange = await api(page, `requests/${exchanged.request.id}/exchange/validate/`, 'POST', { mark_ready: true });
  expect(readyExchange).toMatchObject({ status: 'ready_for_delivery', exchange: { is_validated: true, is_ready: true, state: 'ready_for_delivery' } });
  const actualReady = await api(page, `dispatch/ready/?q=${encodeURIComponent(tag)}`);
  expect(actualReady.map(record => record.id).sort((a, b) => a - b)).toEqual([repaired.request.id, exchanged.request.id].sort((a, b) => a - b));
  await reload(page);
  await dispatch(page, tag);
  const readyList = page.getByRole('region', { name: 'Prêts à être livrés', exact: true });
  for (const record of [repaired.request, exchanged.request])
    await expect(readyList.getByRole('button', { name: `Ouvrir le suivi ${record.reference}`, exact: true })).toBeVisible();
  const returns = page.getByRole('region', { name: 'À retourner au client', exact: true });
  await expect(returns.getByRole('button', { name: `Ouvrir le suivi ${repaired.request.reference}`, exact: true })).toHaveCount(0);
  await expect(returns.getByRole('button', { name: `Ouvrir le suivi ${exchanged.request.reference}`, exact: true })).toHaveCount(0);
});

test('un retour facturable exige diagnostic, devis TVM HT et TVA en TND, confirmation financière puis clôture distincte', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('Retour-payant-fictif');
  const data = await fixture(page, tag);
  const foreign = await fixture(page, `${tag}-AUTRE`);
  const record = data.request;
  const { as_of: today } = await api(page, 'requests/categories/');
  const financeUsername = `retour-finance-${Date.now()}`;
  const managerUsername = `retour-manager-${Date.now()}`;
  const clientUsername = `retour-client-${Date.now()}`;
  await api(page, 'users/', 'POST', { username: financeUsername, role: 'manager', can_validate_billing: true, password });
  await api(page, 'users/', 'POST', { username: managerUsername, role: 'manager', can_validate_billing: false, password });
  await api(page, 'users/', 'POST', { username: clientUsername, role: 'client', client: data.company.id, password });
  expect((await response(page, dispositionPath(record, 'nonrepairable'), 'POST', { diagnosis: '', fee_mode: 'billable' })).status()).toBe(400);
  const diagnosis = `Diagnostic public fictif : module non réparable ${tag}.`;
  await reload(page);
  let dialog = await openDossier(page, record);
  await dialog.getByRole('button', { name: 'Non réparable — Retour client', exact: true }).click();
  await dialog.getByRole('textbox', { name: 'Diagnostic de non-réparabilité', exact: true }).fill(diagnosis);
  await dialog.getByRole('combobox', { name: 'Facturation du diagnostic', exact: true }).selectOption('billable');
  const classifiedResponse = mutationResponse(page, record, 'nonrepairable');
  await dialog.getByRole('button', { name: 'Enregistrer le retour client', exact: true }).click();
  const classified = await mutation(classifiedResponse);
  expect(classified).toMatchObject({ status: 'return_to_client', closed_at: null, disposition: { outcome: 'nonrepairable', state: 'awaiting_quote', fee_mode: 'billable', requires_diagnostic_billing: true, quote: null } });
  for (const rejected of [
    await response(page, `requests/${record.id}/`, 'PATCH', { status: 'closed' }),
    await response(page, `requests/${record.id}/timeline/`, 'POST', { kind: 'status_changed', status_after: 'closed', observation: 'Tentative de clôture avant décision financière.' }),
    await response(page, dispositionPath(record, 'close'), 'POST', {}),
  ]) expect([400, 403]).toContain(rejected.status());

  await dialog.getByRole('button', { name: 'Renseigner les conditions du devis', exact: true }).click();
  await dialog.getByLabel(/^Montant HT/).fill('100.125');
  await dialog.getByLabel(/^Taux de TVA/).fill('19');
  await dialog.getByRole('combobox', { name: 'Devise', exact: true }).selectOption('TND');
  const conditions = `Conditions publiques du devis fictif ${tag}.`;
  await dialog.getByRole('textbox', { name: 'Conditions du devis', exact: true }).fill(conditions);
  const draftedResponse = mutationResponse(page, record, '', 'PATCH');
  await dialog.getByRole('button', { name: 'Enregistrer les conditions du devis', exact: true }).click();
  const drafted = await mutation(draftedResponse);
  expect(drafted.disposition).toMatchObject({ price_ht: '100.125', currency: 'TND', quote_notes: conditions, quote: null });

  const clientContext = await browser.newContext();
  const financeContext = await browser.newContext();
  const managerContext = await browser.newContext();
  try {
    const customer = await clientContext.newPage();
    const finance = await financeContext.newPage();
    const manager = await managerContext.newPage();
    await login(customer, clientUsername);
    await login(finance, financeUsername);
    await login(manager, managerUsername);
    const clientDraft = await api(customer, dispositionPath(record));
    expect(clientDraft.disposition.quote).toBeNull();
    expect(JSON.stringify(clientDraft.disposition)).not.toContain('100.125');
    expect(JSON.stringify(clientDraft.disposition)).not.toContain(conditions);
    expect((await response(customer, dispositionPath(foreign.request))).status()).toBe(404);
    expect((await response(customer, dispositionPath(record), 'PATCH', { price_ht: '1.000', vat_rate: '0', currency: 'TND' })).status()).toBe(403);
    expect((await response(page, dispositionPath(record, 'invoice'), 'POST', { invoice_reference: 'AVANT-DEVIS-FICTIF', invoiced_on: today })).status()).toBe(400);

    const issuedResponse = mutationResponse(page, record, 'quote/issue');
    await dialog.getByRole('button', { name: 'Émettre le devis PDF', exact: true }).click();
    const issued = await mutation(issuedResponse);
    const quote = issued.disposition.quote;
    expect(issued.disposition.state).toBe('awaiting_invoice');
    expect(quote).toMatchObject({ currency: 'TND', vat_amount: '19.024', total_ttc: '119.149' });
    expect(quote.price_ht ?? quote.amount_ht).toBe('100.125');
    expect(quote.number).toEqual(expect.any(String));
    expect(quote.number.length).toBeGreaterThan(0);
    await expect(dialog.getByRole('link', { name: 'Télécharger le devis PDF', exact: true })).toHaveAttribute('href', `/api/diagnostic-quotes/${quote.id}/pdf/`);
    const initialText = await quotePdf(page, quote);
    for (const expected of [quote.number, record.reference, data.company.name, data.equipment.serial_number, diagnosis, conditions, '100.125 TND', '19.024 TND', '119.149 TND']) expect(initialText).toContain(expected);
    expect(initialText).toMatch(/TVA/);
    expect(initialText).toMatch(/Total TTC/);
    expect(initialText).not.toContain(`NOTE-CLIENT-INTERNE-${tag}`);
    expect(await quotePdf(customer, quote)).toBe(initialText);

    await api(page, dispositionPath(foreign.request, 'nonrepairable'), 'POST', { diagnosis: 'Autre diagnostic fictif indépendant.', fee_mode: 'billable' });
    const otherIssued = await prepareQuote(page, foreign.request, { price_ht: '10.000', vat_rate: '0', currency: 'TND' });
    expect((await customer.request.get(otherIssued.disposition.quote.pdf_url)).status()).toBe(404);
    expect((await response(manager, dispositionPath(record, 'invoice'), 'POST', { invoice_reference: 'MANAGER-NON-AUTORISE-FICTIF', invoiced_on: today })).status()).toBe(403);
    expect((await response(customer, dispositionPath(record, 'invoice'), 'POST', { invoice_reference: 'CLIENT-NON-AUTORISE-FICTIF', invoiced_on: today })).status()).toBe(403);

    dialog = await openReturn(finance, record);
    const invoice = `FACTURE-DIAGNOSTIC-FICTIVE-${tag}`;
    const privateNote = `NOTE-FINANCIERE-PRIVEE-${tag}`;
    await dialog.getByRole('textbox', { name: 'Référence de facture', exact: true }).fill(invoice);
    await dialog.getByLabel(/^Date de facture/).fill(today);
    await dialog.getByRole('textbox', { name: 'Notes internes de facturation', exact: true }).fill(privateNote);
    const invoicedResponse = mutationResponse(finance, record, 'invoice');
    await dialog.getByRole('button', { name: 'Confirmer la facturation du diagnostic', exact: true }).click();
    const invoiced = await mutation(invoicedResponse);
    expect(invoiced).toMatchObject({ status: 'return_to_client', closed_at: null, disposition: { state: 'invoiced', invoice_reference: invoice } });
    expect(invoiced.disposition.finance_validated_at).not.toBeNull();
    const clientInvoiced = await api(customer, dispositionPath(record));
    for (const field of ['invoice_reference', 'invoiced_on', 'billing_notes', 'finance_free_reason', 'free_reason'])
      expect(Object.hasOwn(clientInvoiced.disposition, field)).toBe(false);
    expect(JSON.stringify(clientInvoiced)).not.toContain(privateNote);
    expect(JSON.stringify(clientInvoiced)).not.toContain(invoice);
    const closedResponse = mutationResponse(finance, record, 'close');
    await dialog.getByRole('button', { name: 'Clôturer le dossier', exact: true }).click();
    expect(await mutation(closedResponse)).toMatchObject({ status: 'closed', equipment: data.equipment.id, disposition: { state: 'closed' } });
    const frozenText = await quotePdf(customer, quote);
    expect(frozenText).toBe(initialText);
    expect(frozenText).not.toContain(invoice);
    expect(frozenText).not.toContain(privateNote);
  } finally {
    await clientContext.close();
    await financeContext.close();
    await managerContext.close();
  }
});

test('un diagnostic gratuit exige un devis nul à TVA explicite puis une approbation financière motivée avant clôture', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('Retour-gratuit-fictif');
  const technician = (await api(page, 'users/')).find(user => user.username === 'technicien');
  expect(technician).toBeTruthy();
  const data = await fixture(page, tag, { assignedTechnician: technician.id });
  const record = data.request;
  const financeUsername = `gratuit-finance-${Date.now()}`;
  const clientUsername = `gratuit-client-${Date.now()}`;
  await api(page, 'users/', 'POST', { username: financeUsername, role: 'manager', can_validate_billing: true, password });
  await api(page, 'users/', 'POST', { username: clientUsername, role: 'client', client: data.company.id, password });
  const technicianContext = await browser.newContext();
  const financeContext = await browser.newContext();
  const clientContext = await browser.newContext();
  try {
    const worker = await technicianContext.newPage();
    const finance = await financeContext.newPage();
    const customer = await clientContext.newPage();
    await login(worker, 'technicien');
    await confirmCurrentAssignment(worker, record.id);
    await login(finance, financeUsername);
    await login(customer, clientUsername);
    const freeReason = `DEMANDE-GRATUITE-INTERNE-${tag}`;
    const classified = await api(worker, dispositionPath(record, 'nonrepairable'), 'POST', { diagnosis: `Diagnostic non réparable fictif ${tag}.`, fee_mode: 'free', free_reason: freeReason });
    expect(classified).toMatchObject({ status: 'return_to_client', disposition: { outcome: 'nonrepairable', fee_mode: 'free', state: 'awaiting_quote', finance_validated_at: null } });
    expect((await response(page, dispositionPath(record, 'quote/issue'), 'POST', {})).status()).toBe(400);
    await reload(page);
    const quoteDialog = await openDossier(page, record);
    await quoteDialog.getByRole('button', { name: 'Renseigner les conditions du devis', exact: true }).click();
    await quoteDialog.getByLabel(/^Montant HT/).fill('0.000');
    await quoteDialog.getByRole('combobox', { name: 'Devise', exact: true }).selectOption('TND');
    await quoteDialog.getByRole('textbox', { name: 'Motif de gratuité demandée', exact: true }).fill(freeReason);
    await expect(quoteDialog.getByLabel(/^Taux de TVA/)).toHaveValue('');
    const saveQuote = quoteDialog.getByRole('button', { name: 'Enregistrer les conditions du devis', exact: true });
    await expect(saveQuote).toBeDisabled();
    await quoteDialog.getByLabel(/^Taux de TVA/).fill('0');
    await quoteDialog.getByRole('textbox', { name: 'Conditions du devis', exact: true }).fill('Proposition gratuite fictive, approbation financière distincte.');
    const draftResponse = mutationResponse(page, record, '', 'PATCH');
    await saveQuote.click();
    await mutation(draftResponse);
    const issuedResponse = mutationResponse(page, record, 'quote/issue');
    await quoteDialog.getByRole('button', { name: 'Émettre le devis PDF', exact: true }).click();
    const issued = await mutation(issuedResponse);
    expect(issued.disposition).toMatchObject({ state: 'awaiting_free_approval', finance_validated_at: null });
    expect(issued.disposition.quote).toMatchObject({ currency: 'TND', vat_amount: '0.000', total_ttc: '0.000' });
    expect(issued.disposition.quote.price_ht ?? issued.disposition.quote.amount_ht).toBe('0.000');
    expect((await response(worker, dispositionPath(record, 'free'), 'POST', { reason: 'Le technicien ne peut pas approuver.' })).status()).toBe(403);
    expect((await response(customer, dispositionPath(record, 'free'), 'POST', { reason: 'Le client ne peut pas approuver.' })).status()).toBe(403);
    expect((await response(page, dispositionPath(record, 'close'), 'POST', {})).status()).toBe(400);
    const beforeFinance = await api(customer, dispositionPath(record));
    expect(beforeFinance.disposition.state).toBe('awaiting_free_approval');
    expect(Object.hasOwn(beforeFinance.disposition, 'free_reason')).toBe(false);
    expect(JSON.stringify(beforeFinance)).not.toContain(freeReason);

    const dialog = await openReturn(finance, record);
    const approve = dialog.getByRole('button', { name: 'Approuver la gratuité du diagnostic', exact: true });
    await expect(approve).toBeDisabled();
    const approvedReason = `APPROBATION-FINANCE-PRIVEE-${tag}`;
    await dialog.getByRole('textbox', { name: 'Motif de gratuité approuvée', exact: true }).fill(approvedReason);
    const approvedResponse = mutationResponse(finance, record, 'free');
    await approve.click();
    const approved = await mutation(approvedResponse);
    expect(approved).toMatchObject({ status: 'return_to_client', closed_at: null, disposition: { state: 'free_approved', finance_free_reason: approvedReason } });
    expect(approved.disposition.finance_validated_at).not.toBeNull();
    expect(approved.disposition.invoice_reference || '').toBe('');
    const publicApproved = await api(customer, dispositionPath(record));
    expect(Object.hasOwn(publicApproved.disposition, 'finance_free_reason')).toBe(false);
    expect(JSON.stringify(publicApproved)).not.toContain(approvedReason);
    const closedResponse = mutationResponse(finance, record, 'close');
    await dialog.getByRole('button', { name: 'Clôturer le dossier', exact: true }).click();
    expect(await mutation(closedResponse)).toMatchObject({ status: 'closed', disposition: { state: 'closed' } });
  } finally {
    await technicianContext.close();
    await financeContext.close();
    await clientContext.close();
  }
});
