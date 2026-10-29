import { Download, History, Info } from "lucide-react";
import { dateFR } from "./api";
import CallReference from "./CallReference";
import type { User } from "./api";
import {
  repairQuoteDecisionLabels,
  repairQuoteMoney,
  repairQuotePdfUrl,
  type RepairQuote,
} from "./repairQuotes";

export function RepairQuoteTotals({ quote }: { quote: RepairQuote }) {
  const amounts = quote.amounts;
  const value = (amount: string) =>
    repairQuoteMoney(amount, amounts.currency, amounts.precision);
  return (
    <div
      className="repair-quotes-amounts"
      aria-label="Totaux calculés par le serveur"
    >
      <dl>
        <div>
          <dt>Sous-total HT</dt>
          <dd>{value(amounts.subtotal_ht)}</dd>
        </div>
        <div>
          <dt>
            Remise HT
            {amounts.discount_kind === "percent"
              ? ` (${amounts.discount_value} %)`
              : ""}
          </dt>
          <dd>{value(amounts.discount_ht)}</dd>
        </div>
        <div>
          <dt>Net HT</dt>
          <dd>{value(amounts.net_ht)}</dd>
        </div>
        <div>
          <dt>TVA ({amounts.vat_rate} %)</dt>
          <dd>{value(amounts.vat_amount)}</dd>
        </div>
        <div className="repair-quotes-total">
          <dt>Total TTC</dt>
          <dd>{value(amounts.total_ttc)}</dd>
        </div>
      </dl>
      {amounts.fully_discounted && (
        <p className="repair-quotes-info">
          <Info size={16} />
          Remise totale sur ce devis. Cette remise ne confirme ni facturation ni
          gratuité d’une autre prestation.
        </p>
      )}
    </div>
  );
}

export default function RepairQuoteSummary({
  quote,
  user,
}: {
  quote: RepairQuote;
  user: User;
}) {
  const pdf = repairQuotePdfUrl(quote);
  const validUntil =
    quote.valid_until && /^(\d{4})-(\d{2})-(\d{2})$/.exec(quote.valid_until);
  return (
    <>
      <header className="repair-quotes-detail-header">
        <div>
          <span className="eyebrow">
            DEVIS DE RÉPARATION · VERSION {quote.version}
          </span>
          <h2>{quote.reference || `Brouillon · version ${quote.version}`}</h2>
          <CallReference record={quote} role={user.role} compact />
        </div>
        <span
          className={`repair-quotes-state ${quote.state === "draft" ? "draft" : quote.decision}`}
        >
          {quote.state === "draft"
            ? "Brouillon non publié"
            : repairQuoteDecisionLabels[quote.decision]}
        </span>
      </header>
      {quote.state === "issued" && !quote.is_current && (
        <div className="repair-quotes-obsolete" role="status">
          <Info size={18} />
          Cette version a été remplacée. Son PDF et ses décisions sont conservés
          dans l’historique ; seule la version courante peut recevoir une
          nouvelle réponse.
        </div>
      )}
      <dl className="repair-quotes-summary">
        <div>
          <dt>Client</dt>
          <dd>{quote.client.name}</dd>
        </div>
        <div>
          <dt>Équipement</dt>
          <dd>
            {[quote.equipment.brand, quote.equipment.model]
              .filter(Boolean)
              .join(" · ") || "Modèle à identifier"}
          </dd>
        </div>
        <div>
          <dt>Numéro de série</dt>
          <dd>{quote.equipment.serial_number}</dd>
        </div>
        <div>
          <dt>{quote.state === "draft" ? "Création" : "Émission"}</dt>
          <dd>{dateFR(quote.issued_at || quote.created_at, true)}</dd>
        </div>
        {validUntil && (
          <div>
            <dt>Valable jusqu’au</dt>
            <dd>{`${validUntil[3]}/${validUntil[2]}/${validUntil[1]}`}</dd>
          </div>
        )}
        <div>
          <dt>Version</dt>
          <dd>
            {quote.version}
            {quote.is_current
              ? " · Courante"
              : quote.state === "draft"
                ? " · En préparation"
                : " · Historique"}
          </dd>
        </div>
      </dl>
      <div className="repair-quotes-quote-line-table">
        <table>
          <caption>Lignes du devis</caption>
          <thead>
            <tr>
              <th>Désignation</th>
              <th>Quantité</th>
              <th>Prix unitaire HT</th>
              <th>Total HT</th>
            </tr>
          </thead>
          <tbody>
            {quote.amounts.lines.map((line, index) => (
              <tr key={index}>
                <td>{line.description}</td>
                <td>{line.quantity}</td>
                <td>
                  {repairQuoteMoney(
                    line.unit_ht,
                    quote.amounts.currency,
                    quote.amounts.precision,
                  )}
                </td>
                <td>
                  {repairQuoteMoney(
                    line.total_ht,
                    quote.amounts.currency,
                    quote.amounts.precision,
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <RepairQuoteTotals quote={quote} />
      {quote.terms && (
        <section className="repair-quotes-terms">
          <h3>Conditions du devis</h3>
          <p>{quote.terms}</p>
        </section>
      )}
      {pdf && (
        <a
          className="button primary"
          href={pdf}
          target="_blank"
          rel="noreferrer"
        >
          <Download size={17} />
          Télécharger le devis PDF
        </a>
      )}
      <section
        className="repair-quotes-history"
        aria-label="Historique des réponses au devis"
      >
        <h3>
          <History size={18} />
          Historique des réponses
        </h3>
        {quote.history.length ? (
          <ol>
            {[...quote.history]
              .sort((a, b) => b.revision - a.revision)
              .map((entry) => (
                <li key={entry.id}>
                  <span className={`repair-quotes-state ${entry.decision}`}>
                    {repairQuoteDecisionLabels[entry.decision]}
                  </span>
                  <div>
                    <strong>{entry.actor_label}</strong>
                    <time dateTime={entry.decided_at}>
                      {dateFR(entry.decided_at, true)}
                    </time>
                  </div>
                  <small>
                    Réponse n° {entry.revision} · version {quote.version}
                  </small>
                </li>
              ))}
          </ol>
        ) : (
          <p>
            {quote.state === "draft"
              ? "Aucune décision : ce brouillon n’est pas publié au client."
              : "Aucune réponse enregistrée pour cette version."}
          </p>
        )}
      </section>
    </>
  );
}
