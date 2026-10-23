import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  Camera,
  CheckCircle2,
  Keyboard,
  LoaderCircle,
  ScanLine,
  ShieldCheck,
  X,
} from "lucide-react";

type Equipment = {
  id: number;
  serial_number: string;
  model: string;
  brand?: string;
  client_name?: string;
  location?: string;
  status?: string;
};

type Detector = {
  detect: (source: HTMLVideoElement) => Promise<Array<{ rawValue: string }>>;
};
type DetectorConstructor = {
  new (options?: { formats: string[] }): Detector;
  getSupportedFormats?: () => Promise<string[]>;
};

const equipmentStatuses: Record<string, string> = {
  active: "En service",
  maintenance: "En maintenance",
  inactive: "Hors service",
};

export default function Scanner({
  onEquipment,
}: {
  onEquipment?: (id: number) => void;
}) {
  const [serial, setSerial] = useState("");
  const [results, setResults] = useState<Equipment[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [cameraState, setCameraState] = useState<"off" | "starting" | "on">(
    "off",
  );
  const [error, setError] = useState("");
  const [cameraMessage, setCameraMessage] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const runningRef = useRef(false);
  const cameraGenerationRef = useRef(0);
  const mountedRef = useRef(true);

  const stopCamera = () => {
    cameraGenerationRef.current += 1;
    runningRef.current = false;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    if (mountedRef.current) setCameraState("off");
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stopCamera();
      abortRef.current?.abort();
    };
  }, []);

  const search = async (value: string) => {
    const query = value.trim();
    if (!query) {
      setError("Saisissez un numéro de série pour rechercher un équipement.");
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setSearching(true);
    setError("");
    setSearched(false);
    try {
      const response = await fetch(
        `/api/search/?q=${encodeURIComponent(query)}`,
        {
          credentials: "same-origin",
          signal: controller.signal,
        },
      );
      if (!response.ok)
        throw new Error(
          response.status === 401 || response.status === 403
            ? "Votre session ne permet pas cette recherche. Reconnectez-vous si nécessaire."
            : "La recherche est momentanément indisponible. Réessayez.",
        );
      const data = await response.json();
      if (controller.signal.aborted || !mountedRef.current) return;
      setResults(Array.isArray(data.equipment) ? data.equipment : []);
      setSearched(true);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (mountedRef.current)
        setError(
          err instanceof Error
            ? err.message
            : "Impossible de joindre le serveur.",
        );
    } finally {
      if (!controller.signal.aborted && mountedRef.current) setSearching(false);
    }
  };

  const startCamera = async () => {
    setError("");
    setCameraMessage("");
    const BarcodeDetectorClass = (
      window as unknown as { BarcodeDetector?: DetectorConstructor }
    ).BarcodeDetector;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setCameraMessage(
        "La caméra nécessite une connexion HTTPS (ou localhost). Vous pouvez saisir le numéro de série ci-dessous.",
      );
      return;
    }
    if (!BarcodeDetectorClass) {
      setCameraMessage(
        "La lecture automatique des codes n’est pas disponible dans ce navigateur. Essayez Chrome sur Android ou utilisez la saisie manuelle.",
      );
      return;
    }
    setCameraState("starting");
    const generation = ++cameraGenerationRef.current;
    runningRef.current = true;
    try {
      const supportedFormats =
        await BarcodeDetectorClass.getSupportedFormats?.();
      if (!mountedRef.current || generation !== cameraGenerationRef.current)
        return;
      const preferred = [
        "code_128",
        "code_39",
        "ean_13",
        "ean_8",
        "qr_code",
        "data_matrix",
      ];
      const formats = supportedFormats
        ? preferred.filter((format) => supportedFormats.includes(format))
        : preferred;
      if (!formats.length)
        throw new Error(
          "Aucun format de code compatible n’est disponible. Utilisez la saisie manuelle.",
        );
      const detector = new BarcodeDetectorClass({ formats });
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      if (
        !mountedRef.current ||
        !runningRef.current ||
        generation !== cameraGenerationRef.current
      ) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      const video = videoRef.current;
      if (!video)
        throw new Error("La caméra ne peut pas être affichée. Réessayez.");
      video.srcObject = stream;
      await video.play();
      if (
        !runningRef.current ||
        !mountedRef.current ||
        generation !== cameraGenerationRef.current
      )
        return;
      setCameraState("on");
      const detect = async () => {
        if (
          !runningRef.current ||
          !mountedRef.current ||
          !videoRef.current ||
          generation !== cameraGenerationRef.current
        )
          return;
        try {
          if (videoRef.current.readyState >= 2) {
            const codes = await detector.detect(videoRef.current);
            const detected = codes
              .find((code) => code.rawValue.trim())
              ?.rawValue.trim();
            if (
              detected &&
              runningRef.current &&
              mountedRef.current &&
              generation === cameraGenerationRef.current
            ) {
              setSerial(detected);
              setCameraMessage(
                "Code détecté. Vérifiez que la valeur correspond au numéro de série de l’onduleur.",
              );
              stopCamera();
              void search(detected);
              return;
            }
          }
        } catch {
          // Un code illisible n'interrompt pas la caméra ; la saisie manuelle reste disponible.
        }
        if (runningRef.current && generation === cameraGenerationRef.current)
          timerRef.current = setTimeout(() => {
            void detect();
          }, 350);
      };
      void detect();
    } catch (err) {
      if (generation !== cameraGenerationRef.current) return;
      stopCamera();
      if (!mountedRef.current) return;
      const denied =
        err instanceof DOMException &&
        (err.name === "NotAllowedError" ||
          err.name === "PermissionDeniedError");
      setCameraMessage(
        denied
          ? "L’accès à la caméra a été refusé. Autorisez-le dans les paramètres du navigateur ou saisissez le numéro manuellement."
          : err instanceof Error
            ? err.message
            : "Impossible de démarrer la caméra. Utilisez la saisie manuelle.",
      );
    }
  };

  return (
    <div>
      <div className="page-heading">
        <div>
          <div className="eyebrow">IDENTIFICATION DES ÉQUIPEMENTS</div>
          <h1>Scanner & garanties</h1>
          <p>
            Retrouvez un onduleur et son dossier à partir de son numéro de
            série.
          </p>
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(100%, 330px), 1fr))",
          gap: 22,
        }}
      >
        <section className="card" style={{ padding: 24 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 18,
            }}
          >
            <ScanLine size={20} color="#2165ff" />
            <h2 style={{ margin: 0, fontSize: 17 }}>
              Lecture du numéro de série
            </h2>
          </div>
          <div
            style={{
              position: "relative",
              background: "#101d38",
              borderRadius: 14,
              minHeight: 260,
              overflow: "hidden",
              display: "grid",
              placeItems: "center",
            }}
          >
            <video
              ref={videoRef}
              muted
              playsInline
              aria-label="Vue de la caméra pour scanner un numéro de série"
              style={{
                width: "100%",
                minHeight: 260,
                maxHeight: 360,
                objectFit: "cover",
                display: cameraState === "on" ? "block" : "none",
              }}
            />
            {cameraState !== "on" && (
              <div
                style={{ padding: 28, color: "#c0d3f8", textAlign: "center" }}
              >
                {cameraState === "starting" ? (
                  <LoaderCircle size={40} className="spin" />
                ) : (
                  <Camera size={48} strokeWidth={1.3} />
                )}
                <p
                  style={{ fontSize: 14, margin: "14px 0 0", color: "#d4def1" }}
                >
                  {cameraState === "starting"
                    ? "Démarrage de la caméra…"
                    : "Placez le code-barres ou QR code dans le cadre"}
                </p>
                <p style={{ fontSize: 12, opacity: 0.6, marginTop: 8 }}>
                  La vidéo reste sur votre appareil
                </p>
              </div>
            )}
            {cameraState === "on" && (
              <div
                aria-hidden="true"
                style={{
                  position: "absolute",
                  inset: "25% 12%",
                  border: "2px solid #51acff",
                  borderRadius: 12,
                  boxShadow: "0 0 0 300px #07142655",
                  pointerEvents: "none",
                }}
              />
            )}
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            {cameraState === "off" ? (
              <button
                className="button primary"
                type="button"
                onClick={() => {
                  void startCamera();
                }}
              >
                <Camera size={17} />
                Activer la caméra
              </button>
            ) : (
              <button
                className="button secondary"
                type="button"
                onClick={stopCamera}
              >
                <X size={16} />
                Arrêter la caméra
              </button>
            )}
          </div>
          {cameraMessage && (
            <p
              role="status"
              style={{
                display: "flex",
                gap: 8,
                fontSize: 13,
                lineHeight: 1.6,
                color: "#4c6283",
                margin: "14px 0 0",
              }}
            >
              <AlertCircle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
              {cameraMessage}
            </p>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void search(serial);
            }}
            style={{ marginTop: 24 }}
          >
            <label
              htmlFor="serial-search"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                fontWeight: 600,
                fontSize: 13,
                marginBottom: 9,
              }}
            >
              <Keyboard size={16} />
              Ou saisir le numéro de série
            </label>
            <input
              id="serial-search"
              className="input"
              placeholder="Ex. 93PM2408F00123"
              value={serial}
              onChange={(event) => setSerial(event.target.value)}
              autoComplete="off"
              style={{ width: "100%", boxSizing: "border-box" }}
            />
            <button
              className="button primary"
              type="submit"
              disabled={searching || !serial.trim()}
              style={{ width: "100%", justifyContent: "center", marginTop: 12 }}
            >
              {searching ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <ScanLine size={16} />
              )}
              {searching ? "Recherche en cours…" : "Rechercher l’équipement"}
            </button>
          </form>
          {error && (
            <p
              role="alert"
              className="error"
              style={{ color: "#c5364b", fontSize: 13, marginBottom: 0 }}
            >
              {error}
            </p>
          )}
        </section>
        <section className="card" style={{ padding: 24, alignSelf: "start" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 18,
            }}
          >
            <ShieldCheck size={20} color="#2165ff" />
            <h2 style={{ margin: 0, fontSize: 17 }}>Équipements retrouvés</h2>
          </div>
          {!searched && !searching && (
            <div
              style={{
                padding: "42px 16px",
                textAlign: "center",
                color: "#8a99b1",
              }}
            >
              <ScanLine size={40} strokeWidth={1.1} />
              <h3 style={{ fontSize: 15, color: "#485b7b", fontWeight: 600 }}>
                Votre équipement, en un scan
              </h3>
              <p
                style={{
                  fontSize: 13,
                  lineHeight: 1.7,
                  maxWidth: 320,
                  margin: "0 auto",
                }}
              >
                Scannez son étiquette ou saisissez son numéro. Seuls les
                équipements auxquels votre compte a accès apparaissent ici.
              </p>
            </div>
          )}
          {searching && (
            <p role="status" style={{ color: "#6a7e9c", fontSize: 14 }}>
              Recherche dans la base partagée…
            </p>
          )}
          {searched && !results.length && (
            <div
              role="status"
              style={{
                padding: "30px 4px",
                color: "#61728e",
                lineHeight: 1.7,
                fontSize: 14,
              }}
            >
              Aucun équipement accessible ne correspond à ce numéro. Vérifiez la
              saisie ou contactez votre responsable SAV.
            </div>
          )}
          {results.map((equipment) => (
            <article
              key={equipment.id}
              style={{
                border: "1px solid #e8edf7",
                borderRadius: 12,
                padding: 18,
                marginBottom: 12,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  alignItems: "start",
                }}
              >
                <div>
                  <div
                    style={{
                      color: "#8898b1",
                      fontSize: 11,
                      fontWeight: 600,
                      marginBottom: 5,
                    }}
                  >
                    NUMÉRO DE SÉRIE
                  </div>
                  <strong style={{ fontSize: 17 }}>
                    {equipment.serial_number}
                  </strong>
                </div>
                <CheckCircle2 size={20} color="#12b976" />
              </div>
              <p
                style={{ fontSize: 14, margin: "12px 0 5px", color: "#405374" }}
              >
                {equipment.brand} {equipment.model}
              </p>
              <p style={{ fontSize: 13, margin: "0 0 10px", color: "#7f8fa8" }}>
                {equipment.client_name}
                {equipment.location ? ` · ${equipment.location}` : ""}
              </p>
              {equipment.status && (
                <span className="badge">
                  {equipmentStatuses[equipment.status] || equipment.status}
                </span>
              )}
              {onEquipment && (
                <button
                  className="button secondary"
                  type="button"
                  style={{ display: "flex", marginTop: 14 }}
                  onClick={() => onEquipment(equipment.id)}
                >
                  Voir l’équipement
                  <ArrowRight size={15} />
                </button>
              )}
            </article>
          ))}
          <div
            style={{
              borderTop: "1px solid #edf0f7",
              paddingTop: 18,
              marginTop: 20,
              display: "flex",
              gap: 10,
              color: "#7a8da8",
              fontSize: 12,
              lineHeight: 1.7,
            }}
          >
            <ShieldCheck
              size={20}
              style={{ flexShrink: 0, color: "#1764ff" }}
            />
            Les résultats proviennent de la base serveur. Les droits de votre
            compte s’appliquent également aux recherches par numéro de série.
          </div>
        </section>
      </div>
    </div>
  );
}
