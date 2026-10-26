import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  FileText,
  LoaderCircle,
  Search,
  ShieldCheck,
  Truck,
  Undo2,
  Wrench,
} from "lucide-react";
import { api, dateFR, listResult, type RecordData, type User } from "./api";
import CallReference, { callPrimary } from "./CallReference";
import DispositionPanel, {
  dispositionLabels,
  type Disposition,
} from "./DispositionPanel";
import { ExchangePanel, type ExchangeProcess } from "./ExchangeWorkspace";
import { useServerTimingRefresh } from "./RequestTimer";

type DialogProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
};
type DispatchData = { ready: RecordData[]; returns: RecordData[] };
export default function DispatchWorkspace({
  user,
  equipment,
  onChanged,
  onOpenRequest,
  Dialog,
  refreshKey,
  initialSearch = "",
  billing = false,
  onOpenBilling,
}: {
  user: User;
  equipment: RecordData[];
  onChanged: () => Promise<void>;
  onOpenRequest: (record: RecordData) => void;
  Dialog: ComponentType<DialogProps>;
  refreshKey: unknown;
  initialSearch?: string;
  billing?: boolean;
  onOpenBilling?: () => void;
}) {
  const [query, setQuery] = useState(initialSearch);
  const [data, setData] = useState<DispatchData>({ ready: [], returns: [] });
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);
  const [revision, setRevision] = useState(0);
  const [view, setView] = useState("all");
  const [selected, setSelected] = useState<RecordData | null>(null);
  const finance =
    user.role !== "client" &&
    (user.role === "admin" || user.can_validate_billing === true);
  useEffect(() => setQuery(initialSearch), [initialSearch]);
  useServerTimingRefresh(() => setRevision((value) => value + 1));
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setErrors([]);
    setData({ ready: [], returns: [] });
    const timer = window.setTimeout(
      async () => {
        const endpoints = billing
          ? [["returns", "dispatch/billing/"]]
          : [
              ["ready", "dispatch/ready/"],
              ["returns", "dispatch/returns/"],
            ];
        const results = await Promise.allSettled(
          endpoints.map(async ([key, endpoint]) => ({
            key,
            rows: listResult(
              await api(`${endpoint}?q=${encodeURIComponent(query.trim())}`, {
                signal: controller.signal,
              }),
            ),
          })),
        );
        if (controller.signal.aborted) return;
        const next: DispatchData = { ready: [], returns: [] };
        const failures: string[] = [];
        results.forEach((result, index) => {
          if (result.status === "fulfilled")
            next[result.value.key as keyof DispatchData] = result.value.rows;
          else
            failures.push(
              `${endpoints[index][0] === "ready" ? "Livraisons" : "Retours"} : ${result.reason instanceof Error ? result.reason.message : "Chargement impossible"}`,
            );
        });
        setData(next);
        setErrors(failures);
        setLoading(false);
      },
      query ? 200 : 0,
    );
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, refreshKey, revision, billing]);
  const ready = data.ready.filter((row) => row.status === "ready_for_delivery");
  const returns = data.returns.filter((row) => row.status !== "closed");
  const showReady = !billing && view !== "returns";
  const showReturns = billing || view !== "ready";
  function outgoing(row: RecordData) {
    const exchange = row.exchange as ExchangeProcess | null | undefined;
    return exchange?.validated_at && exchange.ready_at
      ? {
          serial: exchange.replacement_serial_number,
          model: exchange.replacement_model,
          kind: "Échange validé",
          exchange: true,
        }
      : {
          serial:
            row.equipment_serial ||
            equipment.find((item) => item.id === row.equipment)?.serial_number,
          model:
            row.equipment_model ||
            equipment.find((item) => item.id === row.equipment)?.model,
          kind:
            row.disposition?.outcome === "repaired"
              ? "Réparation testée"
              : "État prêt existant",
          exchange: false,
        };
  }
  function card(row: RecordData, isReturn: boolean) {
    const disposition = row.disposition as Disposition | null | undefined;
    const shipped = outgoing(row);
    return (
      <article className="dispatch-record" key={row.id}>
        <div className="dispatch-record-top">
          <CallReference record={row} role={user.role} compact />
          <span
            className={`dispatch-kind ${isReturn ? "dispatch-kind-return" : ""}`}
          >
            {isReturn ? (
              <Undo2 size={13} />
            ) : shipped.exchange ? (
              <Truck size={13} />
            ) : (
              <Wrench size={13} />
            )}
            {isReturn ? "Non réparable" : shipped.kind}
          </span>
        </div>
        <p className="dispatch-record-subject">{row.subject}</p>
        <span className="dispatch-record-client">{row.client_name}</span>
        <div className="dispatch-record-equipment">
          <span>
            {isReturn
              ? "Onduleur à retourner au client"
              : shipped.exchange
                ? "Remplacement validé à livrer"
                : "Onduleur à livrer"}
          </span>
          <strong className="serial-text">
            {isReturn
              ? row.equipment_serial ||
                equipment.find((entry) => entry.id === row.equipment)
                  ?.serial_number
              : shipped.serial}
          </strong>
          <small>
            {isReturn
              ? row.equipment_model ||
                equipment.find((entry) => entry.id === row.equipment)?.model
              : shipped.model}
          </small>
          {!isReturn && shipped.exchange && (
            <small>
              Onduleur d’origine :{" "}
              {row.equipment_serial ||
                equipment.find((entry) => entry.id === row.equipment)
                  ?.serial_number}
            </small>
          )}
        </div>
        {isReturn ? (
          <div className="dispatch-record-state">
            <FileText size={14} />
            <span>
              {dispositionLabels[disposition?.state || "awaiting_quote"] ||
                "Suivi du diagnostic à vérifier"}
            </span>
            {disposition?.quote?.number && (
              <small>Devis {disposition.quote.number}</small>
            )}
          </div>
        ) : (
          <div className="dispatch-record-state">
            <CheckCircle2 size={14} />
            <span>Prêt à être livré</span>
            {disposition?.tested_on && (
              <small>Tests réussis le {dateFR(disposition.tested_on)}</small>
            )}
          </div>
        )}
        <button
          type="button"
          className="button secondary small"
          onClick={() => setSelected(row)}
          aria-label={`Ouvrir le suivi ${row.reference}`}
        >
          Ouvrir le suivi
          <ArrowRight size={15} />
        </button>
      </article>
    );
  }
  return (
    <div className="dispatch-workspace">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            {billing
              ? "DIAGNOSTICS & VALIDATION FINANCIÈRE"
              : "EXPÉDITION & RETOUR CLIENT"}
          </div>
          <h1>{billing ? "Diagnostics à facturer" : "Livraisons & retours"}</h1>
          <p>
            {billing
              ? "Confirmez les factures de diagnostic ou approuvez les gratuités justifiées, après émission du devis TVM."
              : "Les onduleurs réparés et les échanges effectivement prêts partagent la file de livraison. Les retours non réparables restent distincts."}
          </p>
        </div>
        {!billing && finance && onOpenBilling && (
          <button
            type="button"
            className="button secondary"
            onClick={onOpenBilling}
          >
            <FileText size={17} />
            Diagnostics à facturer
          </button>
        )}
      </div>
      <section className="card dispatch-search">
        <div className="resource-toolbar">
          <div className="search-field">
            <Search size={17} />
            <input
              aria-label={
                billing
                  ? "Rechercher un diagnostic à facturer"
                  : "Rechercher une livraison ou un retour"
              }
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={
                user.role === "client"
                  ? "Votre n° d’appel client, n° TVM ou numéro de série…"
                  : "N° TVM, n° d’appel client, société, série d’origine ou remplacement…"
              }
            />
          </div>
          <span className="result-count">
            {loading
              ? "Actualisation…"
              : billing
                ? `${returns.length} dossier(s)`
                : `${ready.length} livraison(s) · ${returns.length} retour(s)`}
          </span>
        </div>
        {!billing && (
          <div
            className="dispatch-view-controls page-tabs"
            role="group"
            aria-label="Vue des livraisons et retours"
          >
            {[
              ["all", "Tous"],
              ["ready", "Prêts à être livrés"],
              ["returns", "À retourner au client"],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={view === key ? "active" : ""}
                aria-pressed={view === key}
                onClick={() => setView(key)}
              >
                {label}
                <span>
                  {key === "all"
                    ? ready.length + returns.length
                    : key === "ready"
                      ? ready.length
                      : returns.length}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
      {errors.map((error, index) => (
        <div className="error-box" role="alert" key={index}>
          <AlertCircle size={18} />
          <span>{error}</span>
          <button
            type="button"
            className="button secondary small"
            onClick={() => setRevision((value) => value + 1)}
          >
            Réessayer
          </button>
        </div>
      ))}
      {loading ? (
        <div className="loading-state">
          <LoaderCircle size={18} className="spin" />
          Chargement des livraisons et retours…
        </div>
      ) : (
        <div
          className={`dispatch-columns ${!showReady || !showReturns ? "dispatch-one-column" : ""}`}
        >
          {showReady && (
            <section
              className="dispatch-column dispatch-ready"
              role="region"
              aria-label="Prêts à être livrés"
            >
              <div className="dispatch-column-heading">
                <span>
                  <Truck size={22} />
                </span>
                <div>
                  <h2>Prêts à être livrés</h2>
                  <p>Réparations avec tests réussis et échanges prêts.</p>
                </div>
                <strong>{ready.length}</strong>
              </div>
              <div className="dispatch-ready-list">
                {ready.length ? (
                  ready.map((row) => card(row, false))
                ) : (
                  <div className="dispatch-empty">
                    <CheckCircle2 size={27} />
                    <strong>Aucun onduleur prêt à livrer</strong>
                    <p>
                      Une décision après tests ou la disponibilité d’un échange
                      validé alimente cette file.
                    </p>
                  </div>
                )}
              </div>
            </section>
          )}
          {showReturns && (
            <section
              className="dispatch-column dispatch-returns"
              role="region"
              aria-label={
                billing ? "Diagnostics à régler" : "À retourner au client"
              }
            >
              <div className="dispatch-column-heading">
                <span>
                  <Undo2 size={22} />
                </span>
                <div>
                  <h2>
                    {billing ? "Diagnostics à régler" : "À retourner au client"}
                  </h2>
                  <p>
                    {billing
                      ? "Devis émis, facture ou gratuité à confirmer."
                      : "Non réparables : diagnostic et devis à régulariser."}
                  </p>
                </div>
                <strong>{returns.length}</strong>
              </div>
              <div className="dispatch-return-list">
                {returns.length ? (
                  returns.map((row) => card(row, true))
                ) : (
                  <div className="dispatch-empty">
                    <FileText size={27} />
                    <strong>Aucun retour dans cette vue</strong>
                    <p>
                      Les décisions de non-réparabilité apparaissent ici avec le
                      suivi de leur diagnostic.
                    </p>
                  </div>
                )}
              </div>
            </section>
          )}
        </div>
      )}
      <div className="dispatch-server-note">
        <ShieldCheck size={14} />
        État réel des dossiers sur le serveur. Aucun bon de livraison ni départ
        du matériel n’est créé automatiquement.
      </div>
      {selected && (
        <Dialog
          title="Livraison ou retour client"
          subtitle={callPrimary(selected, user.role)}
          onClose={() => setSelected(null)}
          wide
        >
          <div className="modal-content">
            <div className="dispatch-dialog-reference">
              <CallReference record={selected} role={user.role} />
            </div>
            {selected.exchange?.validated_at &&
            selected.exchange?.ready_at &&
            selected.disposition?.outcome !== "nonrepairable" ? (
              <ExchangePanel
                key={`${selected.id}:${user.id}`}
                record={selected}
                equipment={equipment}
                user={user}
                onChanged={async (updated) => {
                  setSelected(updated);
                  await onChanged();
                }}
              />
            ) : (
              <DispositionPanel
                key={`${selected.id}:${user.id}`}
                record={selected}
                user={user}
                onChanged={async (updated) => {
                  setSelected(updated);
                  await onChanged();
                }}
              />
            )}
            <button
              type="button"
              className="button secondary small dispatch-open-dossier"
              onClick={() => {
                setSelected(null);
                onOpenRequest(selected);
              }}
            >
              <FileText size={15} />
              Ouvrir le dossier SAV
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
