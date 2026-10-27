import {
  useEffect,
  useId,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  Building2,
  ChevronRight,
  Download,
  Eye,
  FileSpreadsheet,
  LoaderCircle,
  Mail,
  MapPin,
  Pencil,
  Phone,
  Plus,
  Search,
  ShieldCheck,
  Upload,
  Users,
  Truck,
  X,
} from "lucide-react";
import {
  api,
  dateFR,
  initials,
  listResult,
  type RecordData,
  type User,
} from "./api";

type DialogProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
};
type DirectoryProps = {
  user: User;
  clients: RecordData[];
  refreshKey: unknown;
  initialSearch?: string;
  onEdit: (value: { resource: string; record?: RecordData }) => void;
  onChanged: () => Promise<void>;
  onNavigate: (page: string, search?: string) => void;
  Dialog: ComponentType<DialogProps>;
};
type ImportRow = {
  line: number;
  status: string;
  name: string;
  data: RecordData;
  errors: string[];
  existing_id: number | null;
};
type ImportResult = {
  mode: "preview" | "apply";
  sha256: string;
  summary: {
    total: number;
    create: number;
    existing: number;
    duplicate: number;
    conflict: number;
    invalid: number;
    created: number;
    skipped: number;
  };
  rows: ImportRow[];
  applied: boolean;
};
const importLabels: Record<string, string> = {
  create: "À créer",
  existing: "Déjà présent",
  duplicate: "Doublon du fichier",
  conflict: "À vérifier",
  invalid: "Invalide",
};
const csvColumns =
  "name;contact_name;tax_id;email;phone;address;city;postal_code;country;notes\r\n";
const templateUrl = `data:text/csv;charset=utf-8,${encodeURIComponent(`\ufeff${csvColumns}`)}`;
const value = (entry: unknown) =>
  entry === null || entry === undefined || entry === ""
    ? "Non renseigné"
    : String(entry);

function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={18} />
      <span>{message}</span>
    </div>
  );
}

export default function ClientsDirectory({
  user,
  clients,
  refreshKey,
  initialSearch = "",
  onEdit,
  onChanged,
  onNavigate,
  Dialog,
}: DirectoryProps) {
  const canManage = user.role === "admin" || user.role === "manager";
  const [query, setQuery] = useState(initialSearch);
  const [rows, setRows] = useState<RecordData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<RecordData | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  useEffect(() => setQuery(initialSearch), [initialSearch]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setRows([]);
    const timer = window.setTimeout(
      () => {
        api(`clients/?q=${encodeURIComponent(query.trim())}`, {
          signal: controller.signal,
        })
          .then((result) => {
            if (!controller.signal.aborted) setRows(listResult(result));
          })
          .catch((failure: Error) => {
            if (!controller.signal.aborted) setError(failure.message);
          })
          .finally(() => {
            if (!controller.signal.aborted) setLoading(false);
          });
      },
      query ? 200 : 0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, refreshKey, retry]);
  return (
    <div className="clients-directory">
      <div className="page-heading">
        <div>
          <div className="eyebrow">CLIENTS & CONTACTS</div>
          <h1>Clients</h1>
          <p>
            Retrouvez les coordonnées, les équipements et les dossiers de chaque
            société.
          </p>
        </div>
        {canManage && (
          <div className="client-heading-actions">
            <button
              type="button"
              className="button secondary"
              onClick={() => setImportOpen(true)}
            >
              <Upload size={17} />
              Importer des clients
            </button>
            <button
              type="button"
              className="button primary"
              onClick={() => onEdit({ resource: "clients" })}
            >
              <Plus size={18} />
              Nouveau client
            </button>
          </div>
        )}
      </div>
      <section
        className="card client-directory-card"
        aria-label="Annuaire clients"
      >
        <div className="resource-toolbar">
          <div className="search-field">
            <Search size={17} />
            <input
              aria-label="Rechercher un client"
              placeholder="Raison sociale, contact, matricule fiscal, e-mail ou téléphone…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            {query && (
              <button
                type="button"
                aria-label="Effacer la recherche clients"
                onClick={() => setQuery("")}
              >
                <X size={15} />
              </button>
            )}
          </div>
          <span className="result-count" role="status">
            {loading
              ? "Recherche…"
              : `${rows.length} client${rows.length > 1 ? "s" : ""}`}
          </span>
        </div>
        {error && (
          <>
            <ErrorMessage message={error} />
            <button
              type="button"
              className="button secondary small"
              onClick={() => setRetry((count) => count + 1)}
            >
              Réessayer
            </button>
          </>
        )}
        {loading ? (
          <div className="loading-state">
            <LoaderCircle size={18} className="spin" />
            Chargement de l’annuaire…
          </div>
        ) : rows.length ? (
          <div className="table-scroll">
            <table className="client-directory-table">
              <thead>
                <tr>
                  <th>Raison sociale / contact</th>
                  <th>Matricule fiscal</th>
                  <th>Coordonnées</th>
                  <th>Adresse</th>
                  <th>Parc / SAV</th>
                  <th>
                    <span className="sr-only">Actions client</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((client) => (
                  <tr key={client.id}>
                    <td>
                      <button
                        type="button"
                        className="client-name-button"
                        aria-label={`Consulter ${client.name}`}
                        onClick={() => setSelected(client)}
                      >
                        <span className="client-avatar">
                          {initials(client.name || "Client")}
                        </span>
                        <span className="primary-cell">
                          <span>{client.name}</span>
                          <small>
                            {client.contact_name || "Contact non renseigné"}
                          </small>
                        </span>
                      </button>
                    </td>
                    <td className="client-tax-id">{value(client.tax_id)}</td>
                    <td>
                      <div className="client-contact-lines">
                        {client.email && (
                          <a
                            href={`mailto:${encodeURIComponent(client.email)}`}
                          >
                            <Mail size={13} />
                            {client.email}
                          </a>
                        )}
                        {client.phone && (
                          <a href={`tel:${encodeURIComponent(client.phone)}`}>
                            <Phone size={13} />
                            {client.phone}
                          </a>
                        )}
                        {!client.email && !client.phone && (
                          <span>Non renseignées</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <div className="client-address">
                        <span>
                          {client.address || "Adresse non renseignée"}
                        </span>
                        <small>
                          {[client.postal_code, client.city, client.country]
                            .filter(Boolean)
                            .join(" · ")}
                        </small>
                      </div>
                    </td>
                    <td>
                      <div className="client-linked-counts">
                        <span>
                          {client.equipment_count ?? "—"} équipement
                          {client.equipment_count !== 1 ? "s" : ""}
                        </span>
                        <small>
                          {client.open_requests_count ?? "—"} dossier
                          {client.open_requests_count !== 1 ? "s" : ""} ouvert
                          {client.open_requests_count !== 1 ? "s" : ""}
                        </small>
                      </div>
                    </td>
                    <td className="action-cell">
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`Consulter la fiche ${client.name}`}
                        onClick={() => setSelected(client)}
                      >
                        <Eye size={17} />
                      </button>
                      {canManage && (
                        <button
                          type="button"
                          className="icon-button"
                          aria-label={`Modifier ${client.name}`}
                          onClick={() =>
                            onEdit({ resource: "clients", record: client })
                          }
                        >
                          <Pencil size={16} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          !error && (
            <div className="empty-state">
              <Building2 size={30} />
              <h3>
                {query ? "Aucun client trouvé" : "Votre annuaire est prêt"}
              </h3>
              <p>
                {query
                  ? "Essayez une autre raison sociale, un contact ou un matricule fiscal."
                  : "Ajoutez une société, avec son nom seul ou ses coordonnées complètes."}
              </p>
              {canManage && !query && (
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => onEdit({ resource: "clients" })}
                >
                  <Plus size={16} />
                  Nouveau client
                </button>
              )}
            </div>
          )
        )}
        <div className="table-footer">
          <span>
            <ShieldCheck size={13} />
            Annuaire partagé, enregistré sur le serveur
          </span>
          <span>
            {clients.length} société{clients.length > 1 ? "s" : ""} enregistrée
            {clients.length > 1 ? "s" : ""}
          </span>
        </div>
      </section>
      {selected && (
        <Dialog
          title="Fiche client"
          subtitle={selected.name}
          wide
          onClose={() => setSelected(null)}
        >
          <ClientDetails
            key={selected.id}
            initial={selected}
            user={user}
            onClose={() => setSelected(null)}
            onEdit={(record) => {
              setSelected(null);
              onEdit({ resource: "clients", record });
            }}
            onNavigate={(page, search) => {
              setSelected(null);
              onNavigate(page, search);
            }}
          />
        </Dialog>
      )}
      {importOpen && canManage && (
        <Dialog
          title="Importer des clients"
          subtitle="Vérifiez le fichier avant d’ajouter les nouvelles sociétés."
          wide
          onClose={() => setImportOpen(false)}
        >
          <ClientImport
            onChanged={onChanged}
            onClose={() => setImportOpen(false)}
          />
        </Dialog>
      )}
    </div>
  );
}

function ClientDetails({
  initial,
  user,
  onClose,
  onEdit,
  onNavigate,
}: {
  initial: RecordData;
  user: User;
  onClose: () => void;
  onEdit: (record: RecordData) => void;
  onNavigate: (page: string, search?: string) => void;
}) {
  const [client, setClient] = useState(initial);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    api<RecordData>(`clients/${initial.id}/`, { signal: controller.signal })
      .then((record) => {
        if (!controller.signal.aborted) setClient(record);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [initial.id]);
  const canManage = user.role === "admin" || user.role === "manager";
  return (
    <>
      <div className="modal-content client-profile">
        {error && <ErrorMessage message={error} />}
        <div className="client-profile-heading">
          <span className="client-avatar large">
            <Building2 size={25} />
          </span>
          <div>
            <h3>{client.name}</h3>
            <p>{client.contact_name || "Contact principal non renseigné"}</p>
          </div>
          {loading && (
            <LoaderCircle
              size={18}
              className="spin"
              aria-label="Actualisation de la fiche"
            />
          )}
        </div>
        <div className="client-profile-stats">
          <div>
            <strong>{client.equipment_count ?? "—"}</strong>
            <span>Équipements</span>
          </div>
          <div>
            <strong>{client.open_requests_count ?? "—"}</strong>
            <span>Dossiers SAV ouverts</span>
          </div>
          {user.role !== "client" && (
            <div>
              <strong>{client.portal_users_count ?? "—"}</strong>
              <span>Comptes portail associés</span>
            </div>
          )}
        </div>
        <div className="client-profile-grid">
          <section className="request-dossier-card">
            <h3>
              <Users size={17} />
              Société et contact
            </h3>
            <dl className="request-dossier-facts">
              <div>
                <dt>Raison sociale</dt>
                <dd>{client.name}</dd>
              </div>
              <div>
                <dt>Matricule fiscal</dt>
                <dd className="client-tax-id">{value(client.tax_id)}</dd>
              </div>
              <div>
                <dt>Contact principal</dt>
                <dd>{value(client.contact_name)}</dd>
              </div>
              <div>
                <dt>Téléphone</dt>
                <dd>
                  {client.phone ? (
                    <a href={`tel:${encodeURIComponent(client.phone)}`}>
                      {client.phone}
                    </a>
                  ) : (
                    "Non renseigné"
                  )}
                </dd>
              </div>
              <div>
                <dt>Adresse e-mail</dt>
                <dd>
                  {client.email ? (
                    <a href={`mailto:${encodeURIComponent(client.email)}`}>
                      {client.email}
                    </a>
                  ) : (
                    "Non renseignée"
                  )}
                </dd>
              </div>
            </dl>
          </section>
          <section className="request-dossier-card">
            <h3>
              <MapPin size={17} />
              Adresse
            </h3>
            <dl className="request-dossier-facts">
              <div>
                <dt>Adresse</dt>
                <dd className="client-preserve-lines">
                  {value(client.address)}
                </dd>
              </div>
              <div>
                <dt>Ville</dt>
                <dd>{value(client.city)}</dd>
              </div>
              <div>
                <dt>Code postal</dt>
                <dd>{value(client.postal_code)}</dd>
              </div>
              <div>
                <dt>Pays</dt>
                <dd>{value(client.country)}</dd>
              </div>
            </dl>
          </section>
        </div>
        {user.role !== "client" && (
          <section className="request-dossier-card client-courier-settings">
            <h3>
              <Truck size={18} />
              Livreurs et notifications de la société
            </h3>
            <dl className="request-dossier-facts">
              <div>
                <dt>Livreur client par défaut</dt>
                <dd>
                  {client.default_courier_name ||
                    "Aucun livreur client configuré"}
                </dd>
              </div>
              <div>
                <dt>Référent livreur TVM</dt>
                <dd>
                  {client.internal_courier_name ||
                    "Aucun référent TVM configuré"}
                </dd>
              </div>
              <div>
                <dt>Notifications client par e-mail</dt>
                <dd>
                  {client.notify_email
                    ? "Autorisées pour cette société"
                    : "Désactivées"}
                </dd>
              </div>
              <div>
                <dt>Notifications client WhatsApp</dt>
                <dd>
                  {client.notify_whatsapp
                    ? "Autorisées pour cette société"
                    : "Désactivées"}
                </dd>
              </div>
            </dl>
            <p>
              À la mise prêt à livrer, le livreur client actif est prioritaire,
              puis le référent TVM. Les missions déjà affectées sont conservées.
              Une notification autorisée reste soumise à la disponibilité réelle
              du fournisseur.
            </p>
          </section>
        )}
        {user.role !== "client" && (
          <section className="request-dossier-card client-private-notes">
            <h3>Notes internes</h3>
            <p className="client-preserve-lines">
              {client.notes || "Aucune note interne renseignée."}
            </p>
            <small>
              Réservées à votre équipe ; absentes du portail client.
            </small>
          </section>
        )}
        {user.role !== "client" && (
          <section className="client-portal-access">
            <ShieldCheck size={20} />
            <div>
              <strong>Accès au portail client</strong>
              <p>
                {Number(client.portal_users_count) > 0
                  ? `${client.portal_users_count} compte(s) associé(s) à cette société.`
                  : "Aucun compte portail associé à cette société."}{" "}
                Les comptes sont créés séparément par un administrateur.
              </p>
              {user.role === "admin" && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => onNavigate("users", client.name)}
                >
                  Gérer les comptes et accès
                  <ChevronRight size={15} />
                </button>
              )}
            </div>
          </section>
        )}
        <small className="client-created-date">
          {client.created_at
            ? `Fiche créée le ${dateFR(client.created_at)}`
            : "Date de création non renseignée"}
        </small>
      </div>
      <div className="modal-footer">
        <span>Coordonnées de la société et suivi du parc</span>
        <div>
          <button type="button" className="button secondary" onClick={onClose}>
            Fermer
          </button>
          {canManage && (
            <button
              type="button"
              className="button primary"
              onClick={() => onEdit(client)}
            >
              <Pencil size={16} />
              Modifier le client
            </button>
          )}
        </div>
      </div>
    </>
  );
}

function ClientImport({
  onChanged,
  onClose,
}: {
  onChanged: () => Promise<void>;
  onClose: () => void;
}) {
  const id = useId();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [limit, setLimit] = useState(100);
  const [source, setSource] = useState<"file" | "paste">("file");
  const [pasted, setPasted] = useState("");
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const generation = useRef(0);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      controller.current?.abort();
    };
  }, []);
  function chooseFile(next: File | null) {
    controller.current?.abort();
    generation.current += 1;
    setResult(null);
    setError("");
    setBusy(null);
    setLimit(100);
    if (next && (!/\.csv$/i.test(next.name) || next.size > 2 * 1024 * 1024)) {
      setFile(null);
      setError("Choisissez un fichier CSV de 2 Mo maximum.");
      return;
    }
    setFile(next);
  }
  async function upload(mode: "preview" | "apply") {
    if (
      !file ||
      busy ||
      (mode === "apply" &&
        (!result || result.applied || result.summary.create < 1))
    )
      return;
    controller.current?.abort();
    const pending = new AbortController();
    controller.current = pending;
    const current = ++generation.current;
    const body = new FormData();
    body.append("file", file);
    body.append("mode", mode);
    if (mode === "apply" && result) body.append("sha256", result.sha256);
    setBusy(mode);
    setError("");
    try {
      const response = await api<ImportResult>("clients/import/", {
        method: "POST",
        body,
        signal: pending.signal,
      });
      if (
        !mounted.current ||
        pending.signal.aborted ||
        current !== generation.current
      )
        return;
      setResult(response);
      setLimit(100);
      if (response.applied) {
        try {
          await onChanged();
        } catch {
          if (mounted.current && current === generation.current)
            setError(
              "L’import est enregistré. L’actualisation de l’annuaire a échoué ; rechargez la page pour retrouver les sociétés créées.",
            );
        }
      }
    } catch (failure) {
      if (
        mounted.current &&
        !pending.signal.aborted &&
        current === generation.current
      )
        setError(
          failure instanceof Error
            ? failure.message
            : "L’import n’a pas abouti.",
        );
    } finally {
      if (
        mounted.current &&
        !pending.signal.aborted &&
        current === generation.current
      )
        setBusy(null);
    }
  }
  return (
    <>
      <div className="modal-content client-import">
        <div className="client-import-guide">
          <FileSpreadsheet size={25} />
          <div>
            <strong>Un CSV, puis un aperçu avant l’enregistrement</strong>
            <p>
              UTF-8, séparateur point-virgule ou virgule, 2 Mo et 5 000 lignes
              maximum. Seule la colonne <code>name</code> est obligatoire. Les
              champs absents restent vides.
            </p>
            <a
              className="button secondary small"
              href={templateUrl}
              download="modele-clients.csv"
            >
              <Download size={15} />
              Télécharger le modèle CSV
            </a>
          </div>
        </div>
        <div
          className="page-tabs client-import-source"
          role="group"
          aria-label="Source du CSV clients"
        >
          <button
            type="button"
            aria-pressed={source === "file"}
            className={source === "file" ? "active" : ""}
            disabled={busy !== null}
            onClick={() => {
              setSource("file");
              chooseFile(null);
            }}
          >
            Importer un fichier
          </button>
          <button
            type="button"
            aria-pressed={source === "paste"}
            className={source === "paste" ? "active" : ""}
            disabled={busy !== null}
            onClick={() => {
              setSource("paste");
              chooseFile(
                pasted.trim()
                  ? new File([pasted], "clients-colles.csv", {
                      type: "text/csv",
                    })
                  : null,
              );
            }}
          >
            Coller un CSV
          </button>
        </div>
        {source === "file" ? (
          <div className="form-field">
            <label htmlFor={`${id}-file`}>Fichier clients CSV</label>
            <input
              id={`${id}-file`}
              className="input"
              type="file"
              accept=".csv,text/csv"
              disabled={busy !== null}
              onChange={(event) => chooseFile(event.target.files?.[0] || null)}
              aria-describedby={`${id}-file-help`}
            />
            <small id={`${id}-file-help`}>
              {csvColumns.trim()} — Aucun compte portail n’est créé par cet
              import.
            </small>
          </div>
        ) : (
          <div className="form-field">
            <label htmlFor={`${id}-paste`}>Contenu CSV à coller</label>
            <textarea
              id={`${id}-paste`}
              className="input client-csv-paste"
              rows={7}
              disabled={busy !== null}
              value={pasted}
              onChange={(event) => {
                setPasted(event.target.value);
                chooseFile(
                  event.target.value.trim()
                    ? new File([event.target.value], "clients-colles.csv", {
                        type: "text/csv",
                      })
                    : null,
                );
              }}
              aria-describedby={`${id}-paste-help`}
              placeholder="name;contact_name;tax_id;email;phone"
            />
            <small id={`${id}-paste-help`}>
              Incluez la ligne d’en-têtes. Le CSV collé suit les mêmes
              vérifications et le même aperçu que le fichier ; aucun compte
              portail n’est créé.
            </small>
          </div>
        )}
        {error && <ErrorMessage message={error} />}
        {result && (
          <section
            className="client-import-preview"
            aria-label="Aperçu de l’import clients"
          >
            <div className="client-import-summary" role="status">
              <div>
                <strong>{result.summary.total}</strong>
                <span>Lignes</span>
              </div>
              <div>
                <strong>
                  {result.applied
                    ? result.summary.created
                    : result.summary.create}
                </strong>
                <span>
                  {result.applied ? "Clients créés" : "Clients à créer"}
                </span>
              </div>
              <div>
                <strong>
                  {result.summary.existing + result.summary.duplicate}
                </strong>
                <span>Déjà présents / doublons</span>
              </div>
              <div>
                <strong>
                  {result.summary.conflict + result.summary.invalid}
                </strong>
                <span>Lignes à vérifier</span>
              </div>
            </div>
            <p className="client-import-notice">
              {result.applied
                ? `Import enregistré : ${result.summary.created} société(s) créée(s), ${result.summary.skipped} ligne(s) ignorée(s).`
                : "L’aperçu n’a créé aucune société. L’application ajoute les nouvelles lignes valides et ignore les autres ; les fiches existantes restent à modifier manuellement."}
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Ligne</th>
                    <th>État</th>
                    <th>Raison sociale</th>
                    <th>Contact / matricule fiscal</th>
                    <th>Vérification</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.slice(0, limit).map((row) => (
                    <tr key={row.line}>
                      <td>{row.line}</td>
                      <td>
                        <span
                          className={`client-import-status client-import-${row.status}`}
                        >
                          {result.applied && row.status === "create"
                            ? "Créé"
                            : importLabels[row.status] || row.status}
                        </span>
                      </td>
                      <td>{row.name || "Nom manquant"}</td>
                      <td>
                        <div className="client-address">
                          <span>{row.data.contact_name || "—"}</span>
                          <small>{row.data.tax_id || "—"}</small>
                        </div>
                      </td>
                      <td>
                        {row.errors.length
                          ? row.errors.join(" · ")
                          : row.status === "create"
                            ? "Nouvelle société"
                            : "Aucune modification automatique"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {result.rows.length > limit && (
              <button
                type="button"
                className="button secondary small"
                onClick={() => setLimit((count) => count + 100)}
              >
                Afficher 100 lignes supplémentaires
              </button>
            )}
          </section>
        )}
      </div>
      <div className="modal-footer">
        <span>{file?.name || "Choisissez le fichier à vérifier."}</span>
        <div>
          <button
            type="button"
            className="button secondary"
            disabled={busy !== null}
            onClick={onClose}
          >
            Fermer
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={!file || busy !== null}
            onClick={() => void upload("preview")}
          >
            {busy === "preview" ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Eye size={16} />
            )}
            Prévisualiser l’import
          </button>
          {result && !result.applied && (
            <button
              type="button"
              className="button primary"
              disabled={busy !== null || result.summary.create < 1}
              onClick={() => void upload("apply")}
            >
              {busy === "apply" ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <Upload size={16} />
              )}
              Appliquer l’import
            </button>
          )}
        </div>
      </div>
    </>
  );
}
