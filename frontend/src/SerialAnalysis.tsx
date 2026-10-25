import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Info,
  LoaderCircle,
  ScanLine,
} from "lucide-react";
import { api } from "./api";

type SerialSegments = {
  manufacturing_location_code: string;
  product_identification_code: string;
  year_code: string;
  week_code: string;
  week_number: number;
  unit_order_code: string;
};

type SerialAnalysisResult = {
  status: "matches" | "not_applicable";
  normalized_serial_number: string;
  rule_id: string;
  source: string;
  segments: SerialSegments | null;
  calendar_year: null;
  warnings: string[];
};

/** Advisory only. This component never edits the serial or any equipment data. */
export default function SerialAnalysis({
  serialNumber,
  brand = "",
}: {
  serialNumber: string;
  brand?: string;
}) {
  const signature = JSON.stringify([serialNumber, brand]);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [result, setResult] = useState<{
    signature: string;
    data: SerialAnalysisResult;
  } | null>(null);
  const [error, setError] = useState<{
    signature: string;
    message: string;
  } | null>(null);

  useEffect(() => {
    generation.current += 1;
    controller.current?.abort();
    setResult(null);
    setError(null);
    setPending(null);
    return () => {
      generation.current += 1;
      controller.current?.abort();
    };
  }, [signature]);

  async function analyze() {
    if (!serialNumber.trim()) return;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const requestGeneration = ++generation.current;
    const requestSignature = signature;
    setPending(requestSignature);
    setResult(null);
    setError(null);
    try {
      const data = await api<SerialAnalysisResult>("serial-analysis/", {
        method: "POST",
        signal: request.signal,
        body: JSON.stringify({ serial_number: serialNumber }),
      });
      if (request.signal.aborted || generation.current !== requestGeneration)
        return;
      setResult({ signature: requestSignature, data });
    } catch (err) {
      if (request.signal.aborted || generation.current !== requestGeneration)
        return;
      setError({
        signature: requestSignature,
        message:
          err instanceof Error
            ? err.message
            : "Impossible de joindre le service d’analyse.",
      });
    } finally {
      if (!request.signal.aborted && generation.current === requestGeneration)
        setPending(null);
    }
  }

  const current = result?.signature === signature ? result.data : null;
  const currentError = error?.signature === signature ? error.message : null;
  const busy = pending === signature;
  const segments = current?.status === "matches" ? current.segments : null;
  const values = segments
    ? [
        {
          label: "Code usine",
          value: segments.manufacturing_location_code,
          note: "Correspondance non fournie",
        },
        {
          label: "Code produit",
          value: segments.product_identification_code,
          note: "Modèle non déduit",
        },
        {
          label: "Code année",
          value: segments.year_code,
          note: "Année civile non déduite",
        },
        {
          label: "Semaine",
          value: segments.week_code,
          note: `Semaine ${segments.week_number}`,
        },
        {
          label: "Ordre de l’unité",
          value: segments.unit_order_code,
          note: "Code brut",
        },
      ]
    : [];

  return (
    <section className="serial-analysis" aria-label="Analyse du format Eaton">
      <div className="serial-analysis-toolbar">
        <button
          type="button"
          className="button secondary small"
          onClick={() => void analyze()}
          disabled={!serialNumber.trim() || busy}
          aria-busy={busy}
        >
          {busy ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <ScanLine size={15} />
          )}
          {busy ? "Analyse en cours…" : "Analyser le format Eaton"}
        </button>
        <span>Facultatif · aucune donnée modifiée</span>
      </div>

      <div className="serial-analysis-result" aria-live="polite">
        {currentError && (
          <div className="serial-analysis-message serial-analysis-error">
            <AlertCircle size={16} />
            <div>
              <strong>Analyse momentanément indisponible</strong>
              <p>{currentError}</p>
              <p>Le numéro peut être conservé et enregistré sans analyse.</p>
            </div>
          </div>
        )}

        {current?.status === "not_applicable" && (
          <div className="serial-analysis-message">
            <Info size={16} />
            <div>
              <strong>
                Hors du format Eaton décrit dans le fichier. Ce numéro peut être
                conservé.
              </strong>
              <p>
                Ce résultat ne signale pas un numéro invalide : d’autres formats
                restent acceptés.
              </p>
            </div>
          </div>
        )}

        {segments && current && (
          <div className="serial-analysis-card" data-rule-id={current.rule_id}>
            <div className="serial-analysis-heading">
              <CheckCircle2 size={17} />
              <div>
                <strong>Structure compatible avec la règle décrite</strong>
                <p>Lecture indicative de {current.normalized_serial_number}</p>
              </div>
            </div>
            <dl className="serial-segments">
              {values.map((segment) => (
                <div key={segment.label}>
                  <dt>{segment.label}</dt>
                  <dd>{segment.value}</dd>
                  <span>{segment.note}</span>
                </div>
              ))}
            </dl>
            <p className="serial-analysis-caution">
              Cette structure ne confirme ni le fabricant ni l’authenticité du
              numéro. Les codes usine, produit et année restent bruts ; aucune
              date ni garantie n’est calculée.
            </p>
          </div>
        )}

        {current && (
          <div className="serial-analysis-provenance">
            {current.warnings?.length > 0 && (
              <ul>
                {current.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            )}
            <p>
              Source : {current.source}. Règle indicative : 10 caractères,
              répartis en 1 / 3 / 1 / 2 / 3.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
