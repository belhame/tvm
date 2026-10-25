import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import {
  AlertCircle,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  Search,
  X,
} from "lucide-react";
import { api } from "./api";

type Product = {
  id: number;
  import_id: number;
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
  raw_data: Record<string, unknown>;
  code_is_usable: boolean;
  code_is_ambiguous: boolean;
  equipment_model_suggestion: string | null;
};

type Catalogue = {
  available: boolean;
  structures: string[];
  active_import: { id: number } | null;
};

type ProductPage = {
  import_id: number;
  count: number;
  next: string | null;
  previous: string | null;
  page: number;
  page_size: number;
  results: Product[];
};

type SearchQuery = { q: string; structure: string };

/** Selecting a catalogue entry only changes the model and brand explicitly. */
export default function CatalogueModelPicker({
  onSelect,
}: {
  onSelect: (selection: { model: string; brand: string }) => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [structure, setStructure] = useState("");
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [metadataLoading, setMetadataLoading] = useState(false);
  const [metadataError, setMetadataError] = useState("");
  const [result, setResult] = useState<{
    query: SearchQuery;
    page: ProductPage;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const generation = useRef(0);
  const metadataGeneration = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const metadataController = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      metadataGeneration.current += 1;
      controller.current?.abort();
      metadataController.current?.abort();
    };
  }, []);

  function invalidateProducts() {
    generation.current += 1;
    controller.current?.abort();
    setBusy(false);
    setResult(null);
    setError("");
  }

  async function loadMetadata() {
    invalidateProducts();
    setCatalogue(null);
    metadataController.current?.abort();
    const request = new AbortController();
    metadataController.current = request;
    const requestGeneration = ++metadataGeneration.current;
    setMetadataLoading(true);
    setMetadataError("");
    try {
      const data = await api<Catalogue>("catalogue/", {
        signal: request.signal,
      });
      if (
        !mounted.current ||
        request.signal.aborted ||
        metadataGeneration.current !== requestGeneration
      )
        return;
      setCatalogue(data);
    } catch (err) {
      if (
        !mounted.current ||
        request.signal.aborted ||
        metadataGeneration.current !== requestGeneration
      )
        return;
      setMetadataError(
        err instanceof Error
          ? err.message
          : "Impossible de vérifier le catalogue disponible.",
      );
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        metadataGeneration.current === requestGeneration
      )
        setMetadataLoading(false);
    }
  }

  function close() {
    generation.current += 1;
    metadataGeneration.current += 1;
    controller.current?.abort();
    metadataController.current?.abort();
    setBusy(false);
    setMetadataLoading(false);
    setOpen(false);
  }

  async function search(searchQuery: SearchQuery, page = 1) {
    const importId = catalogue?.active_import?.id;
    if (
      catalogue?.available !== true ||
      metadataLoading ||
      typeof importId !== "number" ||
      !Number.isInteger(importId) ||
      importId <= 0
    )
      return;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const requestGeneration = ++generation.current;
    const submittedQuery = {
      q: searchQuery.q.trim(),
      structure: searchQuery.structure,
    };
    const parameters = new URLSearchParams({
      q: submittedQuery.q,
      structure: submittedQuery.structure,
      page: String(page),
      page_size: "50",
      import_id: String(importId),
    });
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const data = await api<ProductPage>(
        `catalogue/products/?${parameters.toString()}`,
        { signal: request.signal },
      );
      if (
        !mounted.current ||
        request.signal.aborted ||
        generation.current !== requestGeneration
      )
        return;
      setResult({ query: submittedQuery, page: data });
    } catch (err) {
      if (
        !mounted.current ||
        request.signal.aborted ||
        generation.current !== requestGeneration
      )
        return;
      setError(
        err instanceof Error
          ? err.message
          : "La recherche dans le catalogue est momentanément indisponible.",
      );
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        generation.current === requestGeneration
      )
        setBusy(false);
    }
  }

  function searchOnEnter(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    event.stopPropagation();
    if (!busy && searchReady) void search({ q: query, structure });
  }

  function select(product: Product) {
    if (
      !searchReady ||
      busy ||
      product.import_id !== catalogue?.active_import?.id ||
      !product.product_name.trim() ||
      Array.from(product.product_name).length > 120 ||
      product.equipment_model_suggestion === null
    )
      return;
    onSelect({ model: product.product_name, brand: "Eaton" });
    close();
  }

  const page = result?.page;
  const activeImportId = catalogue?.active_import?.id;
  const searchReady =
    catalogue?.available === true &&
    !metadataLoading &&
    typeof activeImportId === "number" &&
    Number.isInteger(activeImportId) &&
    activeImportId > 0;
  const hasAmbiguousCodes = page?.results.some(
    (product) => product.code_is_ambiguous,
  );

  return (
    <section className="catalogue-picker" aria-label="Choix du modèle Eaton">
      <div className="catalogue-picker-toolbar">
        <button
          type="button"
          className="button secondary small"
          aria-expanded={open}
          aria-controls={`${id}-panel`}
          onClick={() => {
            if (open) close();
            else {
              setOpen(true);
              void loadMetadata();
            }
          }}
        >
          <BookOpen size={15} />
          Choisir dans le catalogue Eaton
        </button>
        <span>Facultatif · sélection explicite du modèle et de la marque</span>
      </div>

      {open && (
        <div id={`${id}-panel`} className="catalogue-picker-panel">
          <div className="catalogue-picker-panel-heading">
            <div>
              <strong>Catalogue produits Eaton</strong>
              <p>
                Recherchez une référence, puis choisissez le produit exact. Le
                numéro de série, le client et les garanties restent inchangés.
              </p>
            </div>
            <button
              type="button"
              className="button secondary small"
              onClick={close}
              aria-label="Fermer le choix dans le catalogue"
            >
              <X size={15} />
            </button>
          </div>

          {metadataLoading && (
            <p className="catalogue-picker-status" role="status">
              <LoaderCircle size={15} className="spin" />
              Vérification du catalogue…
            </p>
          )}
          {metadataError && (
            <div className="catalogue-picker-warning" role="alert">
              <AlertCircle size={16} />
              <div>
                <p>{metadataError}</p>
                <button
                  type="button"
                  className="button secondary small"
                  onClick={() => void loadMetadata()}
                  disabled={metadataLoading}
                >
                  Réessayer la vérification
                </button>
              </div>
            </div>
          )}
          {catalogue?.available === false && (
            <p className="catalogue-picker-warning" role="status">
              <AlertCircle size={16} />
              Aucun catalogue n’est disponible sur le serveur. Vous pouvez
              saisir le modèle manuellement dans la fiche équipement.
            </p>
          )}

          <div
            role="search"
            aria-label="Recherche d’un produit Eaton"
            className="catalogue-picker-controls"
          >
            <label htmlFor={`${id}-query`}>
              <span>Nom, code ou référence</span>
              <input
                id={`${id}-query`}
                className="input"
                type="search"
                placeholder="Nom du produit, code, référence fabricant…"
                value={query}
                onChange={(event) => {
                  invalidateProducts();
                  setQuery(event.target.value);
                }}
                onKeyDown={searchOnEnter}
                autoComplete="off"
              />
            </label>
            <label htmlFor={`${id}-structure`}>
              <span>Structure de série</span>
              <select
                id={`${id}-structure`}
                className="input"
                value={structure}
                onChange={(event) => {
                  invalidateProducts();
                  setStructure(event.target.value);
                }}
              >
                <option value="">Toutes les structures</option>
                {(catalogue?.structures || []).map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="button primary small"
              disabled={busy || !searchReady}
              onClick={() => void search({ q: query, structure })}
            >
              {busy ? (
                <LoaderCircle size={15} className="spin" />
              ) : (
                <Search size={15} />
              )}
              {busy ? "Recherche…" : "Rechercher"}
            </button>
          </div>

          <div className="catalogue-picker-results" aria-live="polite">
            {error && (
              <div className="catalogue-picker-warning" role="alert">
                <AlertCircle size={16} />
                <p>{error}</p>
              </div>
            )}
            {!busy && !result && !error && (
              <p className="catalogue-picker-status">
                Lancez une recherche pour consulter les produits. Sans terme de
                recherche, le catalogue est présenté par pages de 50 références.
              </p>
            )}
            {busy && (
              <p className="catalogue-picker-status" role="status">
                <LoaderCircle size={15} className="spin" />
                Recherche dans le catalogue serveur…
              </p>
            )}
            {page && result && (
              <>
                <p className="catalogue-picker-status">
                  {page.count} référence{page.count > 1 ? "s" : ""} trouvée
                  {page.count > 1 ? "s" : ""}
                  {result.query.q ? ` pour « ${result.query.q} »` : ""}
                  {result.query.structure
                    ? ` · Structure ${result.query.structure}`
                    : ""}
                </p>
                {hasAmbiguousCodes && (
                  <div className="catalogue-picker-warning">
                    <AlertCircle size={16} />
                    <p>
                      Certains codes correspondent à plusieurs produits du même
                      profil. Tous les candidats sont conservés : comparez leurs
                      noms et références. Aucun produit n’est choisi
                      automatiquement.
                    </p>
                  </div>
                )}
                {page.results.length === 0 && (
                  <p className="catalogue-picker-status">
                    Aucun produit ne correspond à ces critères. Modifiez la
                    recherche ou saisissez le modèle manuellement.
                  </p>
                )}
                <ul className="catalogue-picker-products">
                  {page.results.map((product) => {
                    const modelLength = Array.from(product.product_name).length;
                    const canSelect =
                      !!product.product_name.trim() &&
                      modelLength <= 120 &&
                      product.equipment_model_suggestion !== null;
                    return (
                      <li key={product.id} className="catalogue-picker-product">
                        <div className="catalogue-picker-product-main">
                          <strong>
                            {product.product_name || "Nom non fourni"}
                          </strong>
                          <div className="catalogue-picker-product-meta">
                            {product.range_name && (
                              <span>{product.range_name}</span>
                            )}
                            <span>
                              Code : {product.product_code || "non fourni"}
                            </span>
                            {product.structure && (
                              <span>Structure : {product.structure}</span>
                            )}
                            {product.manufacturing_part_number && (
                              <span>
                                Réf. fabricant :{" "}
                                {product.manufacturing_part_number}
                              </span>
                            )}
                            {product.catalogue_number && (
                              <span>
                                Réf. catalogue : {product.catalogue_number}
                              </span>
                            )}
                            {product.market_status && (
                              <span>{product.market_status}</span>
                            )}
                          </div>
                          {product.code_is_ambiguous && (
                            <div className="catalogue-picker-ambiguity">
                              <span className="badge amber">Code ambigu</span>
                              <button
                                type="button"
                                className="button secondary small"
                                onClick={() => {
                                  setQuery(product.product_code);
                                  setStructure(product.structure);
                                  void search({
                                    q: product.product_code,
                                    structure: product.structure,
                                  });
                                }}
                              >
                                Voir les candidats de ce code
                              </button>
                            </div>
                          )}
                          {!canSelect && (
                            <p className="catalogue-picker-model-limit">
                              {modelLength > 120
                                ? `Ce nom contient ${modelLength} caractères et dépasse la limite du modèle (120). Sélection indisponible ; aucune troncature n’est appliquée. Saisissez un modèle validé dans le champ prévu.`
                                : "Ce produit ne propose pas de nom utilisable pour le modèle. Saisissez un modèle validé manuellement."}
                            </p>
                          )}
                        </div>
                        <div className="catalogue-picker-product-actions">
                          <button
                            type="button"
                            className="button secondary small"
                            disabled={!canSelect || busy || !searchReady}
                            onClick={() => select(product)}
                            aria-label={`Choisir ${product.product_name || "ce produit"}`}
                          >
                            <Check size={14} />
                            Choisir ce modèle
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
                {page.count > 0 && (
                  <div className="catalogue-picker-pagination">
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={!page.previous || busy}
                      onClick={() => {
                        if (result) void search(result.query, page.page - 1);
                      }}
                    >
                      <ChevronLeft size={15} />
                      Précédent
                    </button>
                    <span>
                      Page {page.page} sur{" "}
                      {Math.max(1, Math.ceil(page.count / page.page_size))}
                    </span>
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={!page.next || busy}
                      onClick={() => {
                        if (result) void search(result.query, page.page + 1);
                      }}
                    >
                      Suivant
                      <ChevronRight size={15} />
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
