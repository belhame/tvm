import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  AlertCircle,
  ChevronRight,
  LoaderCircle,
  Plus,
  Search,
  Clock3,
} from "lucide-react";
import { api, dateFR, listResult, type RecordData, type User } from "./api";
import { requestCategories, requestStatusLabels, statuses } from "./resources";
import RequestTimer, { useServerTimingRefresh } from "./RequestTimer";

export type RequestCategoryCount = {
  key: string;
  label: string;
  count: number;
};
export type RequestCategoryResponse = {
  categories: RequestCategoryCount[];
  total: number;
  as_of: string;
};

function day(value: string | null | undefined) {
  if (!value) return "Non définie";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : dateFR(value);
}

export default function RequestsWorkspace({
  category,
  user,
  onCategoryChange,
  onOpen,
  onCreate,
  onCountsChange,
  refreshKey,
  initialSearch = "",
}: {
  category: string;
  user: User;
  onCategoryChange: (key: string) => void;
  onOpen: (record: RecordData) => void;
  onCreate: () => void;
  onCountsChange: (value: RequestCategoryCount[]) => void;
  refreshKey: unknown;
  initialSearch?: string;
}) {
  const [search, setSearch] = useState(initialSearch);
  const [submittedSearch, setSubmittedSearch] = useState(initialSearch);
  const [rows, setRows] = useState<RecordData[]>([]);
  const [categories, setCategories] = useState<RequestCategoryCount[] | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [countsError, setCountsError] = useState("");
  const [retry, setRetry] = useState(0);
  const [timingRefresh, setTimingRefresh] = useState(0);
  const currentScope = useRef(JSON.stringify([category, submittedSearch]));
  useServerTimingRefresh(() => setTimingRefresh((value) => value + 1));

  useEffect(() => {
    setSearch(initialSearch);
    setSubmittedSearch(initialSearch);
  }, [initialSearch]);
  useEffect(() => {
    const controller = new AbortController();
    setCountsError("");
    // Counts describe the authorized workspace, independent of the selected tab.
    api<RequestCategoryResponse>("requests/categories/", {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) {
          setCategories(result.categories);
          onCountsChange(result.categories);
        }
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setCountsError(failure.message);
      });
    return () => controller.abort();
  }, [refreshKey, onCountsChange, retry, timingRefresh]);

  useEffect(() => {
    const controller = new AbortController();
    const parameters = new URLSearchParams({ category });
    if (submittedSearch.trim()) parameters.set("q", submittedSearch.trim());
    setLoading(true);
    setError("");
    const scope = JSON.stringify([category, submittedSearch]);
    if (scope !== currentScope.current) {
      currentScope.current = scope;
      setRows([]);
    }
    api(`requests/?${parameters}`, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setRows(listResult(result));
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [category, submittedSearch, refreshKey, retry, timingRefresh]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setSubmittedSearch(search.trim());
  }
  const activeCategory =
    requestCategories.find((entry) => entry.key === category) ||
    requestCategories[requestCategories.length - 1];

  return (
    <div className="request-workspace">
      <div className="page-heading">
        <div>
          <div className="eyebrow">SUIVI DES DOSSIERS SAV</div>
          <h1>Demandes SAV</h1>
          <p>
            Classez les demandes, affectez l’équipe et retrouvez chaque
            opération de l’onduleur.
          </p>
        </div>
        {user.role !== "client" && (
          <button type="button" className="button primary" onClick={onCreate}>
            <Plus size={18} />
            Nouvelle demande
          </button>
        )}
      </div>
      <div
        className="request-category-tabs"
        role="group"
        aria-label="Catégories des demandes SAV"
      >
        {requestCategories.map((entry) => {
          const count = categories?.find((row) => row.key === entry.key)?.count;
          return (
            <button
              type="button"
              key={entry.key}
              aria-pressed={category === entry.key}
              className={`request-category-tab ${category === entry.key ? "active" : ""}`}
              onClick={() => onCategoryChange(entry.key)}
            >
              <span>{entry.label}</span>
              <span className="request-category-count">{count ?? "—"}</span>
            </button>
          );
        })}
      </div>
      {countsError && (
        <div className="error-box" role="alert">
          <AlertCircle size={17} />
          <span>
            Les compteurs n’ont pas pu être actualisés : {countsError}
          </span>
          <button
            type="button"
            className="button secondary small"
            onClick={() => setRetry((value) => value + 1)}
          >
            Réessayer
          </button>
        </div>
      )}
      <section className="card">
        <form className="request-workspace-toolbar" onSubmit={submit}>
          <div className="search-field">
            <Search size={17} />
            <input
              aria-label="Rechercher une demande"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Référence, client, numéro de série ou objet…"
            />
          </div>
          <button type="submit" className="button secondary small">
            Rechercher
          </button>
          <span className="request-list-status">
            {activeCategory.label}
            {!loading &&
              ` · ${rows.length} dossier${rows.length > 1 ? "s" : ""}`}
          </span>
        </form>
        {error && (
          <div className="error-box" role="alert">
            <AlertCircle size={18} />
            <span>{error}</span>
            <button
              type="button"
              className="button secondary small"
              onClick={() => setRetry((value) => value + 1)}
            >
              Réessayer
            </button>
          </div>
        )}
        {loading && !rows.length ? (
          <div className="loading-state">
            <LoaderCircle size={18} className="spin" />
            Chargement des demandes…
          </div>
        ) : rows.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>N° de dossier / objet</th>
                  <th>Client</th>
                  <th>Équipement</th>
                  <th>Date d’arrivée</th>
                  <th>Nbr de jours ouvrés</th>
                  <th>État</th>
                  <th>Affectation</th>
                  <th>Échéance</th>
                  <th>Priorité</th>
                  <th>
                    <span className="sr-only">Ouvrir le dossier</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className="clickable-row"
                    onClick={() => onOpen(row)}
                  >
                    <td>
                      <div className="primary-cell">
                        <span>{row.reference}</span>
                        <small>{row.subject}</small>
                      </div>
                    </td>
                    <td>{row.client_name}</td>
                    <td>
                      <div>
                        <span className="serial-text">
                          {row.equipment_serial}
                        </span>
                        <small>{row.equipment_model || ""}</small>
                      </div>
                    </td>
                    <td>
                      {row.arrived_at
                        ? dateFR(row.arrived_at, true)
                        : "Non renseignée"}
                    </td>
                    <td>
                      <RequestTimer timing={row.timing} compact />
                    </td>
                    <td>
                      <span className={`badge status-${row.status}`}>
                        <span className="badge-dot" />
                        {requestStatusLabels[row.status] || row.status}
                      </span>
                    </td>
                    <td>{row.assigned_technician_name || "Non affecté"}</td>
                    <td>
                      <span
                        className={`request-deadline ${row.is_due_overdue ? "request-overdue" : ""}`}
                      >
                        {row.is_due_overdue && <Clock3 size={13} />}
                        {day(row.due_on)}
                      </span>
                      {row.is_due_overdue && (
                        <small>En dépassement délai</small>
                      )}
                    </td>
                    <td>
                      <span className={`badge status-${row.priority}`}>
                        <span className="badge-dot" />
                        {statuses[row.priority] || row.priority}
                      </span>
                    </td>
                    <td className="action-cell">
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`Ouvrir ${row.reference}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          onOpen(row);
                        }}
                      >
                        <ChevronRight size={18} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          !error && (
            <div className="empty-state">
              <h3>Aucune demande dans cette catégorie</h3>
              <p>
                {submittedSearch
                  ? "Essayez une autre référence ou un autre terme de recherche."
                  : "Les dossiers correspondant à cette catégorie apparaîtront ici."}
              </p>
            </div>
          )
        )}
        <div className="table-footer">
          <span>
            Échéances et compteurs calculés par le serveur pour vos dossiers
            autorisés.
          </span>
          <span>{activeCategory.label}</span>
        </div>
      </section>
    </div>
  );
}
