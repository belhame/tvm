import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import {
  AlertCircle,
  Camera,
  Check,
  ImagePlus,
  Keyboard,
  LoaderCircle,
  ScanLine,
  Search,
  X,
} from "lucide-react";
import { api } from "./api";
import "./SerialCapture.css";

export type SerialCaptureSource = "manual" | "usb" | "camera" | "photo";
export type SerialCaptureProps = {
  value: string;
  onChange: (serial: string) => void;
  onSerialDetected?: (
    serial: string,
    metadata?: { source: SerialCaptureSource },
  ) => void;
  disabled?: boolean;
  manualLabel?: string;
};

type Candidate = { serial_number: string; source: "barcode" | "ocr" };
type Recognition = {
  candidates: Candidate[];
  method: "barcode" | "ocr" | "none";
  status: "recognized" | "ambiguous" | "not_found" | "unavailable";
  message: string;
};
type Detector = {
  detect: (
    source: HTMLVideoElement,
  ) => Promise<Array<{ rawValue: string; format?: string }>>;
};
type DetectorConstructor = {
  new (options: { formats: string[] }): Detector;
  getSupportedFormats?: () => Promise<string[]>;
};
type ScanControls = { stop: () => void };

const maximumPhotoSize = 8 * 1024 * 1024;
const preferredFormats = ["code_128", "code_39", "qr_code", "data_matrix"];

function candidatesFrom(values: Candidate[]): Candidate[] {
  const unique = new Map<string, Candidate>();
  for (const candidate of values) {
    if (typeof candidate.serial_number !== "string") continue;
    const serial = candidate.serial_number.trim();
    if (!serial || serial.length > 120) continue;
    if (!unique.has(serial.toLowerCase()))
      unique.set(serial.toLowerCase(), {
        serial_number: serial,
        source: candidate.source === "ocr" ? "ocr" : "barcode",
      });
  }
  return [...unique.values()].slice(0, 10);
}

/** Capture updates an unsaved serial only. Receipt remains an explicit parent action. */
export default function SerialCapture(props: SerialCaptureProps) {
  const { value, disabled = false, manualLabel = "Numéro de série" } = props;
  const id = useId();
  const callbacks = useRef(props);
  callbacks.current = props;
  const mounted = useRef(true);
  const input = useRef<HTMLInputElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const controls = useRef<ScanControls | null>(null);
  const cameraGeneration = useRef(0);
  const cameraRunning = useRef(false);
  const cameraTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const photoGeneration = useRef(0);
  const photoController = useRef<AbortController | null>(null);
  const previousValue = useRef(value);
  const [entryMode, setEntryMode] = useState<"manual" | "usb">("manual");
  const [cameraState, setCameraState] = useState<"off" | "starting" | "on">(
    "off",
  );
  const [cameraEngine, setCameraEngine] = useState("");
  const [photoOpen, setPhotoOpen] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState("");
  const [photoBusy, setPhotoBusy] = useState(false);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [candidateSource, setCandidateSource] = useState<"camera" | "photo">(
    "photo",
  );
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function stopCamera() {
    cameraGeneration.current += 1;
    cameraRunning.current = false;
    if (cameraTimer.current) clearTimeout(cameraTimer.current);
    cameraTimer.current = null;
    const activeControls = controls.current;
    controls.current = null;
    try {
      activeControls?.stop();
    } catch {
      /* The stream cleanup below still runs. */
    }
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    const attached = video.current?.srcObject;
    if (attached && "getTracks" in attached)
      (attached as MediaStream).getTracks().forEach((track) => track.stop());
    if (video.current) video.current.srcObject = null;
    if (mounted.current) setCameraState("off");
  }

  function cancelRecognition() {
    photoGeneration.current += 1;
    photoController.current?.abort();
    if (mounted.current) {
      setPhotoBusy(false);
      setCandidates([]);
    }
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      stopCamera();
      cancelRecognition();
    };
  }, []);

  useEffect(() => {
    if (previousValue.current !== value) {
      previousValue.current = value;
      stopCamera();
      cancelRecognition();
    }
  }, [value]);

  useEffect(() => {
    if (disabled) {
      stopCamera();
      cancelRecognition();
    }
  }, [disabled]);

  useEffect(() => {
    if (!photo) {
      setPhotoPreview("");
      return;
    }
    const url = URL.createObjectURL(photo);
    setPhotoPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  function detected(
    serial: string,
    source: SerialCaptureSource,
    updateValue = true,
  ) {
    if (!mounted.current || callbacks.current.disabled) return;
    if (!serial.trim() || serial.length > 120) {
      setError(
        "Le numéro de série doit contenir entre 1 et 120 caractères. Vérifiez l’étiquette.",
      );
      return;
    }
    stopCamera();
    cancelRecognition();
    setError("");
    setMessage(
      "Numéro préparé. Vérifiez l’étiquette avant de confirmer la réception dans le formulaire.",
    );
    if (updateValue) callbacks.current.onChange(serial);
    try {
      void Promise.resolve(
        callbacks.current.onSerialDetected?.(serial, { source }),
      ).catch(() => {
        if (
          mounted.current &&
          callbacks.current.value === serial &&
          !callbacks.current.disabled
        )
          setError(
            "Le numéro est conservé. La recherche n’a pas pu être confirmée ; réessayez depuis le formulaire.",
          );
      });
    } catch {
      if (
        mounted.current &&
        callbacks.current.value === serial &&
        !callbacks.current.disabled
      )
        setError(
          "Le numéro est conservé. Relancez la recherche depuis le formulaire.",
        );
    }
  }

  function manualChange(serial: string) {
    stopCamera();
    cancelRecognition();
    setError("");
    setMessage("");
    callbacks.current.onChange(serial);
  }

  function manualEnter(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    event.stopPropagation();
    if (!disabled && value.trim()) detected(value, entryMode, false);
  }

  function cameraCandidates(values: string[], generation: number) {
    if (
      !mounted.current ||
      callbacks.current.disabled ||
      cameraGeneration.current !== generation ||
      !cameraRunning.current
    )
      return;
    const found = candidatesFrom(
      values.map((serial_number) => ({ serial_number, source: "barcode" })),
    );
    if (!found.length) return;
    stopCamera();
    if (found.length === 1) detected(found[0].serial_number, "camera");
    else {
      setCandidates(found);
      setCandidateSource("camera");
      setMessage(
        "Plusieurs codes ont été lus. Choisissez explicitement le numéro de série de l’onduleur.",
      );
    }
  }

  async function startCamera() {
    if (callbacks.current.disabled) return;
    stopCamera();
    cancelRecognition();
    setError("");
    setMessage("");
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError(
        "La caméra en direct nécessite HTTPS ou localhost. La saisie manuelle, la douchette et la lecture d’une photo restent disponibles.",
      );
      return;
    }
    const generation = ++cameraGeneration.current;
    cameraRunning.current = true;
    setCameraState("starting");
    let detector: Detector | null = null;
    const NativeDetector = (
      window as unknown as { BarcodeDetector?: DetectorConstructor }
    ).BarcodeDetector;
    if (NativeDetector) {
      try {
        const supported = await NativeDetector.getSupportedFormats?.();
        const formats = supported
          ? preferredFormats.filter((format) => supported.includes(format))
          : preferredFormats;
        if (formats.length) detector = new NativeDetector({ formats });
      } catch {
        /* ZXing is the local fallback when the native decoder is unavailable. */
      }
    }
    const active = () =>
      mounted.current &&
      !callbacks.current.disabled &&
      cameraRunning.current &&
      cameraGeneration.current === generation;
    if (!active()) return;
    try {
      const element = video.current;
      if (!element)
        throw new Error(
          "L’aperçu de la caméra n’est pas disponible. Réessayez.",
        );
      const constraints: MediaStreamConstraints = {
        audio: false,
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      };
      if (detector) {
        setCameraEngine("Lecture locale du code-barres");
        const acquired = await navigator.mediaDevices.getUserMedia(constraints);
        if (!active()) {
          acquired.getTracks().forEach((track) => track.stop());
          return;
        }
        stream.current = acquired;
        element.srcObject = acquired;
        await element.play();
        if (!active()) return;
        setCameraState("on");
        const scan = async () => {
          if (!active()) return;
          try {
            if (element.readyState >= 2) {
              const found = await detector!.detect(element);
              if (found.length)
                cameraCandidates(
                  found
                    .filter(
                      (item) =>
                        !item.format || preferredFormats.includes(item.format),
                    )
                    .map((item) => item.rawValue),
                  generation,
                );
            }
          } catch {
            /* A frame without a readable code is not a camera error. */
          }
          if (active())
            cameraTimer.current = setTimeout(() => {
              void scan();
            }, 300);
        };
        void scan();
      } else {
        setCameraEngine("Lecture locale compatible ZXing");
        const { BrowserMultiFormatReader, BarcodeFormat } = await import(
          "@zxing/browser"
        );
        if (!active()) return;
        const reader = new BrowserMultiFormatReader(new Map(), {
          delayBetweenScanAttempts: 300,
          delayBetweenScanSuccess: 700,
        });
        const serialFormats = [
          BarcodeFormat.CODE_128,
          BarcodeFormat.CODE_39,
          BarcodeFormat.QR_CODE,
          BarcodeFormat.DATA_MATRIX,
        ];
        reader.possibleFormats = serialFormats;
        const acquired = await navigator.mediaDevices.getUserMedia(constraints);
        if (!active()) {
          acquired.getTracks().forEach((track) => track.stop());
          return;
        }
        stream.current = acquired;
        const scanner = await reader.decodeFromStream(
          acquired,
          element,
          (result) => {
            if (
              result &&
              serialFormats.includes(result.getBarcodeFormat()) &&
              active()
            )
              cameraCandidates([result.getText()], generation);
          },
        );
        if (!active()) {
          scanner.stop();
          return;
        }
        controls.current = scanner;
        const attached = element.srcObject;
        if (attached && "getTracks" in attached)
          stream.current = attached as MediaStream;
        setCameraState("on");
      }
    } catch (failure) {
      if (!active()) return;
      stopCamera();
      const refused =
        failure instanceof DOMException && failure.name === "NotAllowedError";
      setError(
        refused
          ? "L’accès à la caméra a été refusé. Autorisez-le dans le navigateur ou utilisez une photo, une douchette ou la saisie manuelle."
          : failure instanceof Error
            ? failure.message
            : "La caméra ne peut pas démarrer. Utilisez la saisie manuelle ou une photo.",
      );
    }
  }

  function choosePhoto(file: File | null) {
    cancelRecognition();
    setError("");
    setMessage("");
    if (
      file &&
      (!/\.(jpe?g|png|webp)$/i.test(file.name) ||
        file.size === 0 ||
        file.size > maximumPhotoSize)
    ) {
      setPhoto(null);
      setError(
        "Choisissez une photo JPEG, PNG ou WEBP non vide, de 8 Mio maximum.",
      );
      return;
    }
    setPhoto(file);
  }

  async function recognizePhoto() {
    if (!photo || photoBusy || callbacks.current.disabled) return;
    stopCamera();
    cancelRecognition();
    const request = new AbortController();
    photoController.current = request;
    const generation = ++photoGeneration.current;
    const payload = new FormData();
    payload.append("file", photo);
    setPhotoBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await api<Recognition>("logistics/recognize-serial/", {
        method: "POST",
        body: payload,
        signal: request.signal,
      });
      if (
        !mounted.current ||
        callbacks.current.disabled ||
        request.signal.aborted ||
        generation !== photoGeneration.current
      )
        return;
      if (!Array.isArray(response.candidates))
        throw new Error(
          "La réponse de lecture de la photo n’est pas exploitable. Saisissez le numéro manuellement.",
        );
      const found = candidatesFrom(response.candidates);
      setCandidates(found);
      setCandidateSource("photo");
      setMessage(
        response.message ||
          (found.length
            ? "Vérifiez les propositions et choisissez le numéro lu sur l’étiquette."
            : "Aucun numéro lisible n’a été trouvé. Vous pouvez le saisir manuellement."),
      );
    } catch (failure) {
      if (
        !mounted.current ||
        request.signal.aborted ||
        generation !== photoGeneration.current
      )
        return;
      setError(
        failure instanceof Error
          ? failure.message
          : "La lecture de la photo est indisponible. La saisie manuelle reste possible.",
      );
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        generation === photoGeneration.current
      )
        setPhotoBusy(false);
    }
  }

  return (
    <section className="serial-capture" aria-label="Lecture du numéro de série">
      <div
        className="serial-capture-modes"
        role="group"
        aria-label="Mode de lecture du numéro de série"
      >
        <button
          type="button"
          className="button secondary small"
          aria-pressed={entryMode === "manual" && cameraState === "off"}
          disabled={disabled}
          onClick={() => {
            stopCamera();
            setEntryMode("manual");
            input.current?.focus();
          }}
        >
          <Keyboard size={15} />
          Saisie manuelle
        </button>
        <button
          type="button"
          className="button secondary small"
          aria-pressed={entryMode === "usb" && cameraState === "off"}
          disabled={disabled}
          onClick={() => {
            stopCamera();
            setEntryMode("usb");
            input.current?.focus();
          }}
        >
          <ScanLine size={15} />
          Douchette USB / Bluetooth
        </button>
        <button
          type="button"
          className="button secondary small"
          aria-pressed={cameraState !== "off"}
          disabled={disabled}
          onClick={() => {
            if (cameraState === "off") void startCamera();
            else stopCamera();
          }}
        >
          <Camera size={15} />
          {cameraState === "off"
            ? "Scanner avec la caméra"
            : "Arrêter la caméra"}
        </button>
        <button
          type="button"
          className="button secondary small"
          aria-expanded={photoOpen}
          aria-controls={`${id}-photo-panel`}
          disabled={disabled}
          onClick={() => {
            stopCamera();
            setPhotoOpen((open) => !open);
          }}
        >
          <ImagePlus size={15} />
          Lire une photo
        </button>
      </div>
      <div className="serial-capture-camera" hidden={cameraState === "off"}>
        <video
          ref={video}
          muted
          playsInline
          aria-label="Caméra de lecture du code-barres"
        />
        {cameraState === "starting" ? (
          <div className="serial-capture-camera-loading" role="status">
            <LoaderCircle size={24} className="spin" />
            Démarrage de la caméra…
          </div>
        ) : (
          <div className="serial-capture-target" aria-hidden="true" />
        )}
        <span className="serial-capture-engine">{cameraEngine}</span>
        <button
          type="button"
          className="button secondary small serial-capture-camera-stop"
          onClick={stopCamera}
        >
          <X size={14} />
          Arrêter
        </button>
      </div>
      <div className="serial-capture-manual">
        <label htmlFor={`${id}-serial`}>{manualLabel}</label>
        <div className="serial-capture-entry">
          <input
            ref={input}
            id={`${id}-serial`}
            className="input"
            type="text"
            value={value}
            maxLength={120}
            disabled={disabled}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => manualChange(event.target.value)}
            onKeyDown={manualEnter}
            aria-describedby={`${id}-manual-help`}
            placeholder="Numéro figurant sur l’étiquette de l’onduleur"
          />
          <button
            type="button"
            className="button secondary small"
            disabled={disabled || !value.trim()}
            onClick={() => detected(value, entryMode, false)}
          >
            <Search size={15} />
            Utiliser le numéro saisi
          </button>
        </div>
        <p id={`${id}-manual-help`} className="serial-capture-help">
          {entryMode === "usb"
            ? "Mode douchette sélectionné : placez le curseur dans le champ puis scannez. La touche Entrée prépare seulement la recherche."
            : "La saisie et la touche Entrée préparent seulement le numéro. La réception doit être confirmée séparément dans le formulaire."}
        </p>
      </div>
      {photoOpen && (
        <div id={`${id}-photo-panel`} className="serial-capture-photo">
          <div className="serial-capture-photo-fields">
            <label htmlFor={`${id}-photo`}>Photo de l’étiquette</label>
            <input
              id={`${id}-photo`}
              className="input"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
              disabled={disabled || photoBusy}
              aria-describedby={`${id}-photo-help`}
              onChange={(event) => choosePhoto(event.target.files?.[0] || null)}
            />
            <p id={`${id}-photo-help`} className="serial-capture-help">
              JPEG, PNG ou WEBP, 8 Mio maximum. La photo est lue sur le serveur
              pour proposer des numéros ; elle ne crée aucun dossier ni
              équipement.
            </p>
            {photo && <p className="serial-capture-file-name">{photo.name}</p>}
            <button
              type="button"
              className="button secondary small"
              disabled={disabled || !photo || photoBusy}
              onClick={() => void recognizePhoto()}
            >
              {photoBusy ? (
                <LoaderCircle size={15} className="spin" />
              ) : (
                <ScanLine size={15} />
              )}
              {photoBusy ? "Lecture de la photo…" : "Lire l’étiquette photo"}
            </button>
          </div>
          {photoPreview && (
            <img
              className="serial-capture-photo-preview"
              src={photoPreview}
              alt="Étiquette sélectionnée pour une proposition de numéro de série"
            />
          )}
        </div>
      )}
      {error && (
        <div className="serial-capture-error" role="alert">
          <AlertCircle size={17} />
          <p>{error}</p>
        </div>
      )}
      {message && (
        <p className="serial-capture-message" role="status">
          {message}
        </p>
      )}
      {candidates.length > 0 && (
        <div
          className="serial-capture-candidates"
          role="group"
          aria-label="Numéros de série proposés"
        >
          <strong>Choisissez le numéro présent sur l’étiquette</strong>
          <p className="serial-capture-help">
            Les propositions peuvent nécessiter une correction. Aucun numéro
            n’est retenu automatiquement.
          </p>
          <ul>
            {candidates.map((candidate) => (
              <li key={candidate.serial_number}>
                <div>
                  <span className="serial-capture-candidate-value">
                    {candidate.serial_number}
                  </span>
                  <small>
                    {candidate.source === "ocr"
                      ? "Lecture du texte de l’étiquette"
                      : "Code-barres ou QR code"}
                  </small>
                </div>
                <button
                  type="button"
                  className="button secondary small"
                  disabled={disabled}
                  onClick={() =>
                    detected(candidate.serial_number, candidateSource)
                  }
                  aria-label={`Utiliser le numéro ${candidate.serial_number}`}
                >
                  <Check size={14} />
                  Utiliser ce numéro
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
