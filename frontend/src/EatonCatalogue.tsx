import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  Info,
  LoaderCircle,
  Search,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { api, dateFR, type User } from "./api";

type Counts = {
  products: number;
  warranties: number;
  year_mappings: number;
  na_codes: number;
  duplicate_code_groups: number;
};
type ImportSnapshot = {
  id: number;
  filename: string;
  sha256: string;
  imported_at: string;
  imported_by_name: string;
  product_count: number;
  warranty_count: number;
  metadata?: {
    revision?: string | number | null;
    revision_date?: string | number | null;
    sheets?: string[];
  };
};
type YearMapping = {
  structure: string;
  source_sheet: string;
  source_row: number;
  source_column: string | number;
  source_cells: { code: string; year: string };
  code: string;
  year: number;
  raw_code: string;
};
type CatalogueStatus = {
  available: boolean;
  active_import: ImportSnapshot | null;
  counts: Counts;
  structures: string[];
  year_tables: YearMapping[];
  warnings: string[];
};
type Product = {
  id: number;
  range_name: string;
  product_name: string;
  product_code: string;
  structure: string;
  launch_year: string;
  manufacturing_part_number: string;
  catalogue_number: string;
  market_status: string;
  replacement_product: string;
  replacement_part_number: string;
  version: string;
  return_text: string;
  source_row: number;
  code_is_usable: boolean;
  code_is_ambiguous: boolean;
};
type ProductPage = {
  count: number;
  next: string | null;
  previous: string | null;
  page: number;
  page_size: number;
  results: Product[];
};
type Warranty = {
  id: number;
  scope: string;
  category: string;
  duration_text: string;
  duration_months: number | null;
  product_name: string;
  brand_group: string;
  conditions: string;
  source_sheet: string;
  source_row: number;
  source_column: string | number;
};
type ImportResult = {
  created: boolean;
  activated: boolean;
  already_imported: boolean;
  import: ImportSnapshot;
  counts: Counts;
  warnings: string[];
};

const maxFileSize = 8 * 1024 * 1024;
const display = (value: unknown) =>
  value === null || value === undefined || value === "" ? "—" : String(value);

function Loading({ children }: { children: string }) {
  return (
    <div className="loading-state">
      <LoaderCircle size={18} className="spin" /> {children}
    </div>
  );
}

function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={18} />
      <span>{message}</span>
    </div>
  );
}

export default function EatonCatalogue({ user }: { user: User }) {
  const canImport = user.role === "admin" || user.role === "manager";
  const [status, setStatus] = useState<CatalogueStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState("");
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState<"products" | "warranties" | "years">(
    "products",
  );
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [structure, setStructure] = useState("");
  const [page, setPage] = useState(1);
  const [products, setProducts] = useState<ProductPage | null>(null);
  const [productsLoading, setProductsLoading] = useState(false);
  const [productsError, setProductsError] = useState("");
  const [warranties, setWarranties] = useState<Warranty[]>([]);
  const [warrantiesLoading, setWarrantiesLoading] = useState(false);
  const [warrantiesError, setWarrantiesError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const uploadController = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setStatusLoading(true);
    setStatusError("");
    api<CatalogueStatus>("catalogue/", { signal: controller.signal })
      .then((value) => {
        if (controller.signal.aborted) return;
        setStatus(value);
        setStructure((previous) =>
          previous && !value.structures.includes(previous) ? "" : previous,
        );
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setStatusError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setStatusLoading(false);
      });
    return () => controller.abort();
  }, [revision]);

  useEffect(() => {
    if (!status?.available || !status.active_import || tab !== "products")
      return;
    const controller = new AbortController();
    const parameters = new URLSearchParams({
      q: activeQuery,
      structure,
      page: String(page),
      page_size: "50",
      import_id: String(status.active_import.id),
    });
    setProductsLoading(true);
    setProductsError("");
    setProducts(null);
    api<ProductPage>(`catalogue/products/?${parameters}`, {
      signal: controller.signal,
    })
      .then((value) => {
        if (!controller.signal.aborted) setProducts(value);
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setProductsError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setProductsLoading(false);
      });
    return () => controller.abort();
  }, [
    status?.active_import?.id,
    status?.available,
    activeQuery,
    structure,
    page,
    tab,
    revision,
  ]);

  useEffect(() => {
    if (!status?.available || !status.active_import || tab !== "warranties")
      return;
    const controller = new AbortController();
    setWarrantiesLoading(true);
    setWarrantiesError("");
    setWarranties([]);
    api<Warranty[]>(
      `catalogue/warranties/?import_id=${status.active_import.id}`,
      { signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted) setWarranties(value);
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setWarrantiesError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setWarrantiesLoading(false);
      });
    return () => controller.abort();
  }, [status?.active_import?.id, status?.available, tab, revision]);

  useEffect(() => () => uploadController.current?.abort(), []);

  function selectFile(value: File | null) {
    setImportResult(null);
    setImportError("");
    setFile(null);
    if (!value) return;
    if (!/\.xls$/i.test(value.name)) {
      setImportError(
        "Sélectionnez le catalogue au format XLS (.xls), sans conversion en XLSX.",
      );
      return;
    }
    if (value.size > maxFileSize) {
      setImportError(
        "Ce fichier dépasse la limite de 8 Mio. Sélectionnez un catalogue XLS plus petit.",
      );
      return;
    }
    if (!value.size) {
      setImportError("Le fichier sélectionné est vide.");
      return;
    }
    setFile(value);
  }

  async function importCatalogue(event: FormEvent) {
    event.preventDefault();
    if (!file || !canImport || importing) return;
    uploadController.current?.abort();
    const controller = new AbortController();
    uploadController.current = controller;
    const body = new FormData();
    body.append("file", file);
    setImporting(true);
    setImportError("");
    setImportResult(null);
    try {
      const result = await api<ImportResult>("catalogue/import/", {
        method: "POST",
        body,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setImportResult(result);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setPage(1);
      setRevision((previous) => previous + 1);
    } catch (error) {
      if (!controller.signal.aborted)
        setImportError(
          error instanceof Error
            ? error.message
            : "L’import a échoué. Réessayez ou contactez votre administrateur.",
        );
    } finally {
      if (!controller.signal.aborted) setImporting(false);
    }
  }

  function search(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setActiveQuery(query.trim());
  }

  const yearTables = (status?.year_tables || []).filter(
    (row) => !structure || row.structure === structure,
  );
  const snapshot = status?.active_import;

  return (
    <div className="catalogue-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">RÉFÉRENTIEL PRODUITS</div>
          <h1>Catalogue Eaton</h1>
          <p>
            Les modèles, références et informations de garantie du fichier
            importé.
          </p>
        </div>
        <span className="heading-chip">
          <BookOpen size={17} /> Catalogue partagé
        </span>
      </div>

      <div className="catalogue-notice">
        <Info size={18} />
        <p>
          Ce catalogue est indépendant de votre parc. Son import ne crée aucun
          client ni équipement et ne calcule aucune date de garantie.
        </p>
      </div>

      {canImport && (
        <section className="card catalogue-import-card">
          <div className="catalogue-import-heading">
            <span className="catalogue-file-icon">
              <FileSpreadsheet size={23} />
            </span>
            <div>
              <h2>Importer un catalogue XLS</h2>
              <p>Version partagée pour toute l’équipe · 8 Mio maximum</p>
            </div>
          </div>
          <form onSubmit={importCatalogue} className="catalogue-upload-form">
            <label className="catalogue-file-field">
              Fichier catalogue XLS
              <input
                ref={fileInput}
                type="file"
                accept=".xls,application/vnd.ms-excel"
                disabled={importing}
                onChange={(event) =>
                  selectFile(event.target.files?.[0] || null)
                }
              />
            </label>
            <button
              type="submit"
              className="button primary"
              disabled={!file || importing}
            >
              {importing ? (
                <LoaderCircle size={17} className="spin" />
              ) : (
                <Upload size={17} />
              )}
              {importing ? "Import en cours…" : "Importer le catalogue"}
            </button>
          </form>
          <p className="catalogue-upload-help">
            Un fichier déjà connu est reconnu par son empreinte : il n’ajoute
            pas de lignes en double. Votre catalogue précédent reste conservé.
          </p>
          {importError && <ErrorMessage message={importError} />}
          {importResult && (
            <div className="success-box" role="status">
              <CheckCircle2 size={18} />
              <span>
                {importResult.already_imported
                  ? importResult.activated
                    ? "Ce fichier avait déjà été importé. Cette version est maintenant active, sans créer de doublons."
                    : "Ce catalogue est déjà actif. Aucune ligne en double n’a été créée."
                  : `Catalogue importé et activé : ${importResult.counts.products} produits et ${importResult.counts.warranties} garanties enregistrés.`}
              </span>
            </div>
          )}
        </section>
      )}

      {statusError && (
        <div className="catalogue-load-error">
          <ErrorMessage message={statusError} />
          <button
            className="button secondary small"
            onClick={() => setRevision((value) => value + 1)}
          >
            Réessayer
          </button>
        </div>
      )}
      {statusLoading && !status ? (
        <Loading>Chargement du catalogue partagé…</Loading>
      ) : !status?.available ? (
        !statusError && (
          <section className="card catalogue-empty">
            <BookOpen size={34} />
            <h2>Aucun catalogue importé</h2>
            <p>
              {canImport
                ? "Sélectionnez votre fichier XLS ci-dessus pour rendre ses produits consultables par l’équipe."
                : "Votre administrateur ou responsable SAV peut importer le fichier catalogue XLS."}
            </p>
          </section>
        )
      ) : (
        <>
          <section className="card catalogue-current">
            <div className="catalogue-current-title">
              <CheckCircle2 size={18} />
              <div>
                <strong>Catalogue actif</strong>
                <span>{snapshot?.filename}</span>
                {snapshot?.metadata?.revision_date && (
                  <small className="catalogue-current-meta">
                    Date de révision du fichier :{" "}
                    {display(snapshot.metadata.revision_date)}
                  </small>
                )}
              </div>
              <span className="catalogue-revision">
                {snapshot?.metadata?.revision
                  ? `Révision ${snapshot.metadata.revision}`
                  : `Import #${snapshot?.id}`}
              </span>
            </div>
            <div className="catalogue-counts">
              <div>
                <strong>{status.counts.products}</strong>
                <span>produits</span>
              </div>
              <div>
                <strong>{status.counts.warranties}</strong>
                <span>informations de garantie</span>
              </div>
              <div>
                <strong>{status.counts.year_mappings}</strong>
                <span>correspondances d’années</span>
              </div>
              <div
                className={
                  status.counts.duplicate_code_groups
                    ? "catalogue-ambiguous-count"
                    : ""
                }
              >
                <strong>{status.counts.duplicate_code_groups}</strong>
                <span>codes ambigus</span>
              </div>
            </div>
            <details className="catalogue-provenance">
              <summary>Provenance et version du fichier</summary>
              <dl>
                <div>
                  <dt>Fichier source</dt>
                  <dd>{snapshot?.filename}</dd>
                </div>
                <div>
                  <dt>Révision du catalogue</dt>
                  <dd>{display(snapshot?.metadata?.revision)}</dd>
                </div>
                <div>
                  <dt>Date de révision indiquée</dt>
                  <dd>{display(snapshot?.metadata?.revision_date)}</dd>
                </div>
                <div>
                  <dt>Feuilles source</dt>
                  <dd>
                    {Array.isArray(snapshot?.metadata?.sheets)
                      ? snapshot.metadata.sheets.join(", ")
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Import enregistré</dt>
                  <dd>
                    {snapshot?.imported_at
                      ? dateFR(snapshot.imported_at, true)
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Importé par</dt>
                  <dd>{display(snapshot?.imported_by_name)}</dd>
                </div>
                <div>
                  <dt>Empreinte SHA256</dt>
                  <dd className="catalogue-hash">{snapshot?.sha256}</dd>
                </div>
              </dl>
            </details>
          </section>

          {status.counts.duplicate_code_groups > 0 && (
            <div className="catalogue-ambiguity-warning">
              <AlertCircle size={18} />
              <p>
                <strong>
                  {status.counts.duplicate_code_groups} codes associés à
                  plusieurs produits.
                </strong>{" "}
                Un code ambigu ne suffit pas à identifier un modèle. Toutes ses
                correspondances restent visibles et doivent être départagées
                explicitement.
              </p>
            </div>
          )}
          {status.warnings?.length > 0 && (
            <details className="catalogue-import-warnings">
              <summary>
                Points à vérifier dans la source ({status.warnings.length})
              </summary>
              <ul>
                {status.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </details>
          )}

          <div
            className="page-tabs"
            role="tablist"
            aria-label="Données du catalogue"
          >
            <button
              role="tab"
              aria-selected={tab === "products"}
              className={tab === "products" ? "active" : ""}
              onClick={() => setTab("products")}
            >
              Produits <span>{status.counts.products}</span>
            </button>
            <button
              role="tab"
              aria-selected={tab === "warranties"}
              className={tab === "warranties" ? "active" : ""}
              onClick={() => setTab("warranties")}
            >
              Garanties <span>{status.counts.warranties}</span>
            </button>
            <button
              role="tab"
              aria-selected={tab === "years"}
              className={tab === "years" ? "active" : ""}
              onClick={() => setTab("years")}
            >
              Années <span>{status.counts.year_mappings}</span>
            </button>
          </div>

          {tab === "products" && (
            <section
              className="card catalogue-products-card"
              aria-label="Produits du catalogue"
            >
              <form onSubmit={search} className="catalogue-filters">
                <div className="search-field">
                  <Search size={17} />
                  <input
                    aria-label="Rechercher dans le catalogue"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    maxLength={200}
                    placeholder="Modèle, code produit ou référence…"
                  />
                </div>
                <select
                  className="input"
                  aria-label="Structure des produits"
                  value={structure}
                  onChange={(event) => {
                    setStructure(event.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">Toutes les structures</option>
                  {status.structures.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
                <button className="button secondary" type="submit">
                  <Search size={15} />
                  Rechercher
                </button>
              </form>
              {productsError && (
                <div className="catalogue-table-error">
                  <ErrorMessage message={productsError} />
                  <button
                    className="button secondary small"
                    onClick={() => setRevision((value) => value + 1)}
                  >
                    Réessayer
                  </button>
                </div>
              )}
              {productsLoading ? (
                <Loading>Recherche des produits…</Loading>
              ) : products?.results.length ? (
                <div className="table-scroll">
                  <table className="catalogue-products-table">
                    <thead>
                      <tr>
                        <th>Produit / modèle</th>
                        <th>Code produit</th>
                        <th>Structure</th>
                        <th>Référence fabricant</th>
                        <th>Référence catalogue</th>
                        <th>Lancement</th>
                        <th>Statut / remplacement</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {products.results.map((product) => (
                        <tr key={product.id}>
                          <td>
                            <strong>{display(product.product_name)}</strong>
                            <small>{display(product.range_name)}</small>
                            {product.version && (
                              <small>Version : {product.version}</small>
                            )}
                          </td>
                          <td>
                            <code>{display(product.product_code)}</code>
                            {product.code_is_ambiguous && (
                              <span className="catalogue-code-warning">
                                <AlertCircle size={12} />
                                Plusieurs correspondances
                              </span>
                            )}
                            {!product.code_is_usable && (
                              <span className="catalogue-code-unusable">
                                Code non exploitable
                              </span>
                            )}
                          </td>
                          <td>{display(product.structure)}</td>
                          <td className="serial-text">
                            {display(product.manufacturing_part_number)}
                          </td>
                          <td className="serial-text">
                            {display(product.catalogue_number)}
                          </td>
                          <td>{display(product.launch_year)}</td>
                          <td>
                            {display(product.market_status)}
                            {product.replacement_product && (
                              <small>
                                Remplacement : {product.replacement_product}
                              </small>
                            )}
                            {product.replacement_part_number && (
                              <small>
                                Réf. : {product.replacement_part_number}
                              </small>
                            )}
                            {product.return_text && (
                              <small>{product.return_text}</small>
                            )}
                          </td>
                          <td>Ligne {product.source_row}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                !productsError && (
                  <div className="catalogue-no-results">
                    <Search size={26} />
                    <h3>Aucun produit correspondant</h3>
                    <p>Essayez un autre modèle, code ou numéro de référence.</p>
                  </div>
                )
              )}
              {products && (
                <div className="catalogue-pagination">
                  <span>
                    {products.count} résultat{products.count > 1 ? "s" : ""} ·
                    Page {products.page} /{" "}
                    {Math.max(
                      1,
                      Math.ceil(products.count / products.page_size),
                    )}
                  </span>
                  <div>
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={!products.previous || productsLoading}
                      onClick={() => setPage((value) => Math.max(1, value - 1))}
                    >
                      <ChevronLeft size={16} />
                      Précédent
                    </button>
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={!products.next || productsLoading}
                      onClick={() => setPage((value) => value + 1)}
                    >
                      Suivant
                      <ChevronRight size={16} />
                    </button>
                  </div>
                </div>
              )}
            </section>
          )}

          {tab === "warranties" && (
            <section
              className="card"
              aria-label="Informations de garantie du catalogue"
            >
              <div className="catalogue-section-note">
                <ShieldCheck size={18} />
                <p>
                  Informations du catalogue uniquement : elles ne créent pas de
                  garantie sur un équipement et ne calculent aucune date de fin.
                </p>
              </div>
              {warrantiesError && (
                <div className="catalogue-table-error">
                  <ErrorMessage message={warrantiesError} />
                  <button
                    className="button secondary small"
                    onClick={() => setRevision((value) => value + 1)}
                  >
                    Réessayer
                  </button>
                </div>
              )}
              {warrantiesLoading ? (
                <Loading>Chargement des garanties du catalogue…</Loading>
              ) : warranties.length ? (
                <div className="table-scroll">
                  <table className="catalogue-warranties-table">
                    <thead>
                      <tr>
                        <th>Produit / catégorie</th>
                        <th>Périmètre</th>
                        <th>Durée indiquée</th>
                        <th>Conditions</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {warranties.map((row) => (
                        <tr key={row.id}>
                          <td>
                            <strong>
                              {display(row.product_name || row.category)}
                            </strong>
                            <small>{display(row.brand_group)}</small>
                            {row.product_name && row.category && (
                              <small>{row.category}</small>
                            )}
                          </td>
                          <td>{display(row.scope)}</td>
                          <td>
                            {display(row.duration_text)}
                            {row.duration_months !== null && (
                              <small>{row.duration_months} mois</small>
                            )}
                          </td>
                          <td>{display(row.conditions)}</td>
                          <td>
                            {display(row.source_sheet)}
                            <small>
                              Ligne {row.source_row} · colonne{" "}
                              {display(row.source_column)}
                            </small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                !warrantiesError && (
                  <div className="catalogue-no-results">
                    <ShieldCheck size={26} />
                    <h3>Aucune information de garantie dans ce fichier</h3>
                  </div>
                )
              )}
            </section>
          )}

          {tab === "years" && (
            <section
              className="card"
              aria-label="Tables des années du catalogue"
            >
              <div className="catalogue-section-note">
                <Info size={18} />
                <p>
                  Correspondances fournies par le fichier, lues séparément pour
                  chaque structure. Elles ne datent pas automatiquement vos
                  équipements.
                </p>
              </div>
              <div className="catalogue-year-filter">
                <label>
                  Structure
                  <select
                    className="input"
                    value={structure}
                    onChange={(event) => {
                      setStructure(event.target.value);
                      setPage(1);
                    }}
                  >
                    <option value="">Toutes les structures</option>
                    {status.structures.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <span>
                  {yearTables.length} correspondance
                  {yearTables.length > 1 ? "s" : ""}
                </span>
              </div>
              {yearTables.length ? (
                <div className="table-scroll">
                  <table className="catalogue-years-table">
                    <thead>
                      <tr>
                        <th>Structure</th>
                        <th>Code année</th>
                        <th>Année indiquée dans le fichier</th>
                        <th>Provenance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {yearTables.map((row, index) => (
                        <tr key={`${row.structure}-${row.source_row}-${index}`}>
                          <td>{row.structure}</td>
                          <td>
                            <code>{display(row.code)}</code>
                            {row.raw_code && row.raw_code !== row.code && (
                              <small>Valeur source : {row.raw_code}</small>
                            )}
                          </td>
                          <td>{row.year}</td>
                          <td>
                            {row.source_sheet}
                            <small>
                              Ligne {row.source_row}
                              {row.source_cells?.code && row.source_cells?.year
                                ? ` · Cellules ${row.source_cells.code} / ${row.source_cells.year}`
                                : ""}
                            </small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="catalogue-no-results">
                  <Info size={26} />
                  <h3>Aucune correspondance d’année pour cette structure</h3>
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
