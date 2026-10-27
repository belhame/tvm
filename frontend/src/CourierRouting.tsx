import { Info, Route, UserRound } from "lucide-react";
import type { RecordData } from "./api";

export default function CourierRouting({
  record,
  recommendation = false,
}: {
  record: RecordData;
  recommendation?: boolean;
}) {
  if (recommendation && record.routing_status === "unassigned") {
    const courier = record.recommended_courier;
    return (
      <div
        className={`courier-routing-badge ${courier ? "routing-proposed" : "routing-missing"}`}
      >
        {courier ? <Route size={14} /> : <Info size={14} />}
        <span>
          {courier
            ? `Livreur recommandé : ${courier.name}`
            : "Aucun livreur actif configuré"}
          {courier && (
            <small>
              {record.routing_source === "default_courier"
                ? "Configuration : livreur client par défaut"
                : record.routing_source === "internal_courier"
                  ? "Configuration : référent TVM"
                  : "Proposition à vérifier"}{" "}
              · mission non affectée
            </small>
          )}
        </span>
      </div>
    );
  }
  const automatic = record.assignment_mode === "automatic";
  const label =
    record.assignment_mode === "manual"
      ? "Affectation manuelle"
      : automatic
        ? record.routing_source === "default_courier"
          ? "Automatique · livreur client par défaut"
          : record.routing_source === "internal_courier"
            ? "Automatique · référent TVM"
            : "Affectation automatique"
        : "Origine d’affectation non renseignée";
  return (
    <div
      className={`courier-routing-badge ${automatic ? "routing-automatic" : "routing-manual"}`}
    >
      {automatic ? <Route size={14} /> : <UserRound size={14} />}
      <span>{label}</span>
    </div>
  );
}
