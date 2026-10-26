import { useEffect, useState } from "react";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Clock3,
  ExternalLink,
  LockKeyhole,
  MessageCircle,
  ShieldCheck,
} from "lucide-react";
import type { User } from "./api";
import NotificationCenter from "./NotificationCenter";

type IntegrationStatus = {
  configured?: boolean;
  operational?: boolean;
  available?: boolean;
  enabled?: boolean;
  status?: string;
  message?: string;
  detail?: string;
  requirements?: string[];
};
type IntegrationsPayload = {
  whatsapp?: IntegrationStatus;
  ai?: IntegrationStatus;
  assistant?: IntegrationStatus;
};

export default function Integrations({ user }: { user: User }) {
  const [data, setData] = useState<IntegrationsPayload | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch("/api/integrations/", {
          credentials: "same-origin",
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error("Impossible de vérifier l’état des intégrations.");
        const payload = await response.json();
        if (!controller.signal.aborted) setData(payload);
      } catch (err) {
        if (!controller.signal.aborted)
          setError(
            err instanceof Error ? err.message : "Le serveur est indisponible.",
          );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, []);

  const renderStatus = (status?: IntegrationStatus) => {
    if (loading) return <span className="badge">Vérification…</span>;
    if (!status || error)
      return <span className="badge">État non vérifié</span>;
    if (status.operational === true)
      return (
        <span
          className="badge"
          style={{ background: "#e5faf0", color: "#159760" }}
        >
          <CheckCircle2 size={12} />
          Service opérationnel
        </span>
      );
    if (status.configured === true)
      return (
        <span
          className="badge"
          style={{ background: "#fff4dc", color: "#ac780d" }}
        >
          <Clock3 size={12} />
          Configuré · validation requise
        </span>
      );
    return (
      <span
        className="badge"
        style={{ background: "#f1f4fa", color: "#6b7d9d" }}
      >
        <LockKeyhole size={12} />À connecter
      </span>
    );
  };
  const whatsapp = data?.whatsapp;
  const ai = data?.ai || data?.assistant;

  return (
    <div>
      <div className="page-heading">
        <div>
          <div className="eyebrow">COMMUNICATION & INTELLIGENCE</div>
          <h1>Intégrations</h1>
          <p>
            Connectez vos services en gardant le contrôle sur vos données
            clients.
          </p>
        </div>
      </div>
      {error && (
        <div
          className="card"
          role="alert"
          style={{
            padding: 16,
            color: "#bd3c50",
            display: "flex",
            gap: 9,
            marginBottom: 20,
          }}
        >
          <AlertCircle size={18} />
          {error}
        </div>
      )}
      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(100%, 330px), 1fr))",
          gap: 22,
        }}
      >
        <section className="card" style={{ padding: 26 }}>
          <div
            style={{
              display: "flex",
              alignItems: "start",
              justifyContent: "space-between",
              gap: 12,
              marginBottom: 24,
            }}
          >
            <div
              style={{
                display: "grid",
                placeItems: "center",
                width: 54,
                height: 54,
                borderRadius: 16,
                color: "#12aa69",
                background: "#e9faf2",
              }}
            >
              <MessageCircle size={27} />
            </div>
            {renderStatus(whatsapp)}
          </div>
          <h2 style={{ fontSize: 20, margin: "0 0 9px" }}>
            Notifications WhatsApp
          </h2>
          <p
            style={{
              color: "#71839e",
              fontSize: 14,
              lineHeight: 1.8,
              margin: "0 0 18px",
            }}
          >
            Informez vos clients lors de la planification d’une intervention et
            de la mise à disposition de leur rapport.
          </p>
          <div
            style={{
              padding: 15,
              background: "#f7f9fe",
              borderRadius: 10,
              color: "#586d90",
              fontSize: 13,
              lineHeight: 1.7,
            }}
          >
            {whatsapp?.message ||
              whatsapp?.detail ||
              "L’envoi automatique nécessite votre compte WhatsApp Business, un numéro validé et des modèles de messages approuvés. Aucun message n’est envoyé depuis cet écran."}
          </div>
          <h3 style={{ fontSize: 13, marginTop: 24 }}>
            Accès et éléments à préparer
          </h3>
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              display: "grid",
              gap: 13,
              fontSize: 13,
              color: "#6a7e9b",
            }}
          >
            {(whatsapp?.requirements?.length
              ? whatsapp.requirements
              : [
                  "Compte Meta WhatsApp Business et numéro de téléphone vérifié",
                  "Jeton serveur et configuration sécurisée des webhooks",
                  "Consentement des contacts et modèles de messages approuvés",
                ]
            ).map((requirement) => (
              <li
                key={requirement}
                style={{ display: "flex", gap: 9, alignItems: "start" }}
              >
                <Clock3
                  size={15}
                  style={{ color: "#94a5bd", flexShrink: 0, marginTop: 2 }}
                />
                <span>{requirement}</span>
              </li>
            ))}
          </ul>
          <a
            href="https://developers.facebook.com/docs/whatsapp/cloud-api/"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 7,
              color: "#2165ff",
              fontSize: 13,
              fontWeight: 600,
              marginTop: 24,
              textDecoration: "none",
            }}
          >
            Documentation WhatsApp Business
            <ExternalLink size={14} />
          </a>
        </section>
        <section className="card" style={{ padding: 26 }}>
          <div
            style={{
              display: "flex",
              alignItems: "start",
              justifyContent: "space-between",
              gap: 12,
              marginBottom: 24,
            }}
          >
            <div
              style={{
                display: "grid",
                placeItems: "center",
                width: 54,
                height: 54,
                borderRadius: 16,
                color: "#7461db",
                background: "#f0ecff",
              }}
            >
              <Bot size={27} />
            </div>
            {renderStatus(ai)}
          </div>
          <h2 style={{ fontSize: 20, margin: "0 0 9px" }}>
            Assistant IA connecté aux dossiers
          </h2>
          <p
            style={{
              color: "#71839e",
              fontSize: 14,
              lineHeight: 1.8,
              margin: "0 0 18px",
            }}
          >
            Préparez une synthèse d’intervention et retrouvez l’historique utile
            au diagnostic, dans le périmètre de votre compte.
          </p>
          <div
            style={{
              padding: 15,
              background: "#f7f9fe",
              borderRadius: 10,
              color: "#586d90",
              fontSize: 13,
              lineHeight: 1.7,
            }}
          >
            {ai?.message ||
              ai?.detail ||
              "Aucun modèle IA n’est connecté actuellement. Les recommandations et diagnostics ne sont pas simulés : ils seront disponibles après configuration et validation du fournisseur."}
          </div>
          <h3 style={{ fontSize: 13, marginTop: 24 }}>
            Conditions de mise en service
          </h3>
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              display: "grid",
              gap: 13,
              fontSize: 13,
              color: "#6a7e9b",
            }}
          >
            {(ai?.requirements?.length
              ? ai.requirements
              : [
                  "Fournisseur et modèle validés, clé API conservée côté serveur",
                  "Politique de confidentialité et durée de conservation définies",
                  "Contrôle des droits sur chaque dossier et validation humaine des conseils",
                ]
            ).map((requirement) => (
              <li
                key={requirement}
                style={{ display: "flex", gap: 9, alignItems: "start" }}
              >
                <ShieldCheck
                  size={15}
                  style={{ color: "#8c83c8", flexShrink: 0, marginTop: 2 }}
                />
                <span>{requirement}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
      {user.role === "admin" && (
        <div className="card integration-reminders">
          <NotificationCenter key={user.id} user={user} />
        </div>
      )}
      <div
        className="card"
        style={{
          padding: "21px 25px",
          marginTop: 22,
          display: "flex",
          gap: 14,
          alignItems: "start",
          background: "#f1f6ff",
          borderColor: "#e2ebfc",
        }}
      >
        <ShieldCheck size={23} style={{ flexShrink: 0, color: "#2165ff" }} />
        <div>
          <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>
            La sécurité de vos dossiers reste prioritaire
          </h3>
          <p
            style={{
              margin: 0,
              color: "#6d819f",
              fontSize: 13,
              lineHeight: 1.8,
            }}
          >
            Les intégrations devront appliquer les mêmes autorisations que
            l’application. Un client ne pourra consulter que ses équipements et
            ses demandes. Les accès fournisseurs doivent être saisis dans la
            configuration sécurisée du serveur, jamais dans un navigateur ni
            dans un document partagé.
          </p>
        </div>
      </div>
    </div>
  );
}
