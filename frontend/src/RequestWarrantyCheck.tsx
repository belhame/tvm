import { useEffect, useId, useRef, useState } from "react";
import {
  AlertCircle,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { api } from "./api";
import type { SerialLookupResult } from "./SerialLookupSummary";
import WarrantyCheckCard from "./WarrantyCheckCard";
import { warrantyScopeLabel } from "./warranty";
import "./WarrantyCheck.css";

type Choice = {
  profile?: string;
  product_id?: number;
  warranty_reference_id?: number;
  catalogue_import_id?: number;
};

/** Optional read-only catalogue verification, separate from equipment and warranty editing. */
export default function RequestWarrantyCheck({
  serialNumber,
  equipmentId,
}: {
  serialNumber: string;
  equipmentId: number;
}) {
  const id = useId();
  const [result, setResult] = useState<SerialLookupResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const scope = JSON.stringify([equipmentId, serialNumber]);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  useEffect(() => {
    generation.current += 1;
    controller.current?.abort();
    setResult(null);
    setError("");
    setBusy(false);
    return () => {
      generation.current += 1;
      controller.current?.abort();
    };
  }, [scope]);

  async function lookup(choice: Choice = {}) {
    if (!serialNumber.trim()) return;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const stamp = ++generation.current;
    const startedScope = scope;
    setBusy(true);
    setError("");
    // Discard the previous interpretation while a different selection is being checked.
    setResult(null);
    try {
      const response = await api<SerialLookupResult>("serial-lookup/", {
        method: "POST",
        signal: request.signal,
        body: JSON.stringify({ serial_number: serialNumber, ...choice }),
      });
      if (
        !request.signal.aborted &&
        stamp === generation.current &&
        currentScope.current === startedScope
      )
        setResult(response);
    } catch (failure) {
      if (
        !request.signal.aborted &&
        stamp === generation.current &&
        currentScope.current === startedScope
      )
        setError((failure as Error).message);
    } finally {
      if (!request.signal.aborted && stamp === generation.current)
        setBusy(false);
    }
  }
  const chosen: Choice = {
    ...(result?.catalogue_import_id
      ? { catalogue_import_id: result.catalogue_import_id }
      : {}),
    ...(result?.detection.profile ? { profile: result.detection.profile } : {}),
    ...(result?.selected_product_id
      ? { product_id: result.selected_product_id }
      : {}),
    ...(result?.selected_warranty?.id
      ? { warranty_reference_id: result.selected_warranty.id }
      : {}),
  };
  return (
    <section
      className="warranty-check-panel"
      aria-label="Contrôle de garantie du dossier"
    >
      <div className="warranty-check-panel-toolbar">
        <h3>
          <ShieldCheck size={17} /> Garantie constructeur
        </h3>
        <button
          type="button"
          className="button secondary small"
          disabled={busy || !serialNumber.trim()}
          onClick={() => void lookup()}
        >
          {busy ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <RefreshCw size={16} />
          )}
          {result ? "Actualiser la garantie" : "Vérifier la garantie"}
        </button>
      </div>
      {!result && !busy && !error && (
        <p className="warranty-check-panel-note">
          Vérifiez le modèle, sa génération et les dates sans modifier
          l’équipement ni les garanties enregistrées.
        </p>
      )}
      {busy && (
        <p className="warranty-check-panel-note" role="status">
          Vérification de la garantie en cours…
        </p>
      )}
      {error && (
        <div className="error-box" role="alert">
          <AlertCircle size={17} />
          {error}
        </div>
      )}
      {result && (
        <>
          {(result.detection.requires_profile_choice ||
            result.product_candidates.length > 1 ||
            result.computed_warranty.status === "needs_choice") && (
            <div className="warranty-check-panel-choices">
              <p className="warranty-check-panel-note">
                Plusieurs références sont possibles. Aucun premier résultat
                n’est retenu à votre place.
              </p>
              {result.detection.requires_profile_choice && (
                <label htmlFor={`${id}-profile`}>
                  Structure de série à vérifier
                  <select
                    className="input"
                    id={`${id}-profile`}
                    aria-label="Structure de série à vérifier"
                    value={result.detection.profile || ""}
                    onChange={(event) => {
                      if (event.target.value)
                        void lookup({
                          catalogue_import_id:
                            result.catalogue_import_id ?? undefined,
                          profile: event.target.value,
                        });
                    }}
                  >
                    <option value="">Choisir une structure</option>
                    {result.detection.profile_options.map((profile) => (
                      <option key={profile}>{profile}</option>
                    ))}
                  </select>
                </label>
              )}
              {result.product_candidates.length > 1 && (
                <label htmlFor={`${id}-product`}>
                  Référence produit à vérifier
                  <select
                    className="input"
                    id={`${id}-product`}
                    aria-label="Référence produit à vérifier"
                    value={result.selected_product_id ?? ""}
                    onChange={(event) => {
                      if (event.target.value)
                        void lookup({
                          catalogue_import_id: chosen.catalogue_import_id,
                          profile: chosen.profile,
                          product_id: Number(event.target.value),
                        });
                    }}
                  >
                    <option value="">Choisir explicitement le produit</option>
                    {result.product_candidates.map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.catalogue_number || product.product_name} ·{" "}
                        {product.range_name} ·{" "}
                        {product.version || "Génération non précisée"} ·{" "}
                        {product.manufacturing_part_number || "P/N non fourni"}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {result.warranty_options.length > 0 &&
                ((!result.selected_warranty &&
                  result.computed_warranty.status === "needs_choice") ||
                  result.warranty_options.length > 1) && (
                  <label htmlFor={`${id}-warranty`}>
                    Couverture de garantie à vérifier
                    <select
                      className="input"
                      id={`${id}-warranty`}
                      aria-label="Couverture de garantie à vérifier"
                      value={
                        result.selected_warranty?.id ??
                        result.computed_warranty.warranty_id ??
                        ""
                      }
                      onChange={(event) => {
                        if (event.target.value)
                          void lookup({
                            ...chosen,
                            warranty_reference_id: Number(event.target.value),
                          });
                      }}
                    >
                      <option value="">Choisir une couverture</option>
                      {result.warranty_options.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.category || option.product_name} ·{" "}
                          {warrantyScopeLabel(option.scope)} ·{" "}
                          {option.duration_text || "Durée à vérifier"}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
            </div>
          )}
          <div aria-live="polite" aria-atomic="false">
            {result.warranty_check ? (
              <WarrantyCheckCard check={result.warranty_check} />
            ) : (
              <p className="warranty-check-panel-note">
                La synthèse de garantie n’a pas été fournie. Les dates
                enregistrées restent inchangées.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
