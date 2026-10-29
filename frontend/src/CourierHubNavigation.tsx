import { useId } from "react";
import { ArrowRight, MapPin, Truck } from "lucide-react";
import "./CourierHubNavigation.css";

export default function CourierHubNavigation({
  deliveries,
  available,
  awaitingAcceptance,
  pickups,
  pickupsInTransit,
  loading,
  sharedLoading,
  hasDeliveryError,
  hasPickupError,
  hasSharedError,
  canPickups,
  canReadyQueue,
  view,
  onDeliveries,
  onPickups,
}: {
  deliveries: number;
  available: number;
  awaitingAcceptance: number;
  pickups: number;
  pickupsInTransit: number;
  loading: boolean;
  sharedLoading: boolean;
  hasDeliveryError: boolean;
  hasPickupError: boolean;
  hasSharedError: boolean;
  canPickups: boolean;
  canReadyQueue: boolean;
  view: string;
  onDeliveries: () => void;
  onPickups: () => void;
}) {
  const id = useId();
  const deliveryCount = loading || hasDeliveryError ? "—" : deliveries;
  const availableCount = sharedLoading || hasSharedError ? "—" : available;
  const pickupCount = loading || hasPickupError ? "—" : pickups;
  return (
    <section
      className={`courier-hub-navigation ${!canPickups ? "courier-hub-single" : ""}`}
      aria-label="Navigation des transports"
    >
      <button
        type="button"
        className={`courier-hub-section ${view === "home" || view === "ready" ? "active" : ""}`}
        aria-label="À livrer"
        aria-describedby={`${id}-delivery-details`}
        aria-pressed={view === "home" || view === "ready"}
        onClick={onDeliveries}
      >
        <span className="courier-hub-section-icon"><Truck size={25} /></span>
        <span className="courier-hub-section-content">
          <strong>À livrer</strong>
          <span id={`${id}-delivery-details`}>
            <b>{deliveryCount}</b> mission{deliveries > 1 ? "s" : ""} affectée{deliveries > 1 ? "s" : ""} à vous
            {!loading && !hasDeliveryError && awaitingAcceptance > 0 && (
              <span className="courier-hub-detail">dont {awaitingAcceptance} à accepter</span>
            )}
            {canReadyQueue && (
              <span className="courier-hub-detail"><b>{availableCount}</b> prêt{available > 1 ? "s" : ""} disponible{available > 1 ? "s" : ""} · tous les clients</span>
            )}
          </span>
        </span>
        <ArrowRight size={20} aria-hidden="true" />
      </button>
      {canPickups && (
        <button
          type="button"
          className={`courier-hub-section ${view === "routes" ? "active" : ""}`}
          aria-label="À récupérer"
          aria-describedby={`${id}-pickup-details`}
          aria-pressed={view === "routes"}
          onClick={onPickups}
        >
          <span className="courier-hub-section-icon"><MapPin size={25} /></span>
          <span className="courier-hub-section-content">
            <strong>À récupérer</strong>
            <span id={`${id}-pickup-details`}>
              <b>{pickupCount}</b> enlèvement{pickups > 1 ? "s" : ""} affecté{pickups > 1 ? "s" : ""} à vous
              {!loading && !hasPickupError && pickupsInTransit > 0 && (
                <span className="courier-hub-detail">dont {pickupsInTransit} en transport vers l’atelier</span>
              )}
            </span>
          </span>
          <ArrowRight size={20} aria-hidden="true" />
        </button>
      )}
    </section>
  );
}
