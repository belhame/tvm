import { useEffect, useId, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  File as FileOutline,
  FileImage,
  FileText,
  FolderOpen,
  Info,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  Share2,
  Trash2,
  Upload,
} from "lucide-react";
import { api, dateFR, type User } from "./api";

export type RequestDocument = {
  id: number;
  service_request: number;
  label: string;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  client_visible: boolean;
  uploaded_by_name: string;
  created_at: string;
  can_delete: boolean;
  download_url: string;
};

type DocumentList = {
  results: RequestDocument[];
  can_upload: boolean;
  max_file_size: number;
  allowed_extensions: string[];
  virus_scanned: boolean;
};

function fileSize(bytes: number) {
  if (!Number.isFinite(bytes) || bytes < 0) return "Taille non disponible";
  if (bytes >= 1024 * 1024)
    return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 }).format(bytes / (1024 * 1024))} Mo`;
  if (bytes >= 1024)
    return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 }).format(bytes / 1024)} Ko`;
  return `${bytes.toLocaleString("fr-FR")} octet${bytes > 1 ? "s" : ""}`;
}

function uploadDate(value: string) {
  return value && !Number.isNaN(new Date(value).getTime())
    ? dateFR(value, true)
    : "Date non disponible";
}

function FileIcon({ mimeType }: { mimeType: string }) {
  if (mimeType.startsWith("image/")) return <FileImage size={22} />;
  if (mimeType === "application/pdf" || mimeType.startsWith("text/"))
    return <FileText size={22} />;
  return <FileOutline size={22} />;
}

function protectedDownload(document: RequestDocument) {
  const fallback = `/api/documents/${document.id}/download/`;
  try {
    const url = new URL(document.download_url, window.location.origin);
    return url.origin === window.location.origin && url.pathname === fallback
      ? `${url.pathname}${url.search}`
      : fallback;
  } catch {
    return fallback;
  }
}

/** Scope and role changes dispose of pending requests and the unsent file. */
export default function RequestDocuments({
  requestId,
  user,
  onChanged,
}: {
  requestId: number;
  user: User;
  onChanged?: () => Promise<void>;
}) {
  if (!Number.isSafeInteger(requestId) || requestId <= 0)
    return (
      <section
        className="request-documents"
        aria-label="Documents du dossier SAV"
      >
        <p className="request-documents-empty">
          Ouvrez un dossier SAV enregistré pour consulter ses documents.
        </p>
      </section>
    );
  return (
    <ScopedRequestDocuments
      key={`${requestId}:${user.id}:${user.role}`}
      requestId={requestId}
      user={user}
      onChanged={onChanged}
    />
  );
}

function ScopedRequestDocuments({
  requestId,
  user,
  onChanged,
}: {
  requestId: number;
  user: User;
  onChanged?: () => Promise<void>;
}) {
  const id = useId();
  const isClient = user.role === "client";
  const endpoint = `requests/${requestId}/documents/`;
  const [data, setData] = useState<DocumentList | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [label, setLabel] = useState("");
  const [clientVisible, setClientVisible] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [deleteCandidate, setDeleteCandidate] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState("");
  const [notice, setNotice] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const loadGeneration = useRef(0);
  const mutationGeneration = useRef(0);
  const loadController = useRef<AbortController | null>(null);
  const mutationController = useRef<AbortController | null>(null);
  const mutating = useRef(false);
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  async function load() {
    loadController.current?.abort();
    const request = new AbortController();
    loadController.current = request;
    const generation = ++loadGeneration.current;
    setLoading(true);
    setLoadError("");
    try {
      const response = await api<DocumentList>(endpoint, {
        signal: request.signal,
      });
      if (
        !mounted.current ||
        request.signal.aborted ||
        loadGeneration.current !== generation
      )
        return;
      if (
        !Array.isArray(response.results) ||
        !Array.isArray(response.allowed_extensions)
      )
        throw new Error(
          "Le serveur n’a pas renvoyé une liste de documents exploitable.",
        );
      setData({
        ...response,
        results: response.results.filter(
          (document) =>
            document.service_request === requestId &&
            (!isClient || document.client_visible === true),
        ),
      });
    } catch (err) {
      if (
        !mounted.current ||
        request.signal.aborted ||
        loadGeneration.current !== generation
      )
        return;
      setLoadError(
        err instanceof Error
          ? err.message
          : "Impossible de charger les documents du dossier.",
      );
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        loadGeneration.current === generation
      )
        setLoading(false);
    }
  }

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
      loadGeneration.current += 1;
      mutationGeneration.current += 1;
      loadController.current?.abort();
      mutationController.current?.abort();
    };
  }, [endpoint]);

  const documents = data?.results || [];
  const canUpload = !isClient && data?.can_upload === true;
  const busy = uploading || deletingId !== null;
  const allowedExtensions = (data?.allowed_extensions || []).map((extension) =>
    extension.replace(/^\./, "").toLowerCase(),
  );
  const acceptedFiles = allowedExtensions
    .map((extension) => `.${extension}`)
    .join(",");
  const maximumSize = data?.max_file_size || 0;

  async function notifyChanged(generation: number) {
    if (!mounted.current || mutationGeneration.current !== generation) return;
    try {
      await onChangedRef.current?.();
    } catch {
      if (mounted.current && mutationGeneration.current === generation)
        setNotice(
          "Le document a été mis à jour. Actualisez la fiche pour recharger ses autres informations.",
        );
    }
  }

  async function upload() {
    if (!canUpload || loading || loadError || mutating.current) return;
    if (!selectedFile) {
      setUploadError("Choisissez un fichier à ajouter au dossier.");
      return;
    }
    if (selectedFile.size === 0) {
      setUploadError(
        "Ce fichier est vide. Choisissez un fichier contenant un document.",
      );
      return;
    }
    if (maximumSize <= 0 || selectedFile.size > maximumSize) {
      setUploadError(
        `Le fichier dépasse la taille autorisée (${fileSize(maximumSize)}).`,
      );
      return;
    }
    const extension = selectedFile.name.split(".").pop()?.toLowerCase() || "";
    if (!allowedExtensions.includes(extension)) {
      setUploadError(
        `Ce format n’est pas autorisé. Formats acceptés : ${allowedExtensions.join(", ").toUpperCase()}.`,
      );
      return;
    }
    if (label.length > 200) {
      setUploadError("Le libellé doit contenir au maximum 200 caractères.");
      return;
    }
    mutating.current = true;
    mutationController.current?.abort();
    const request = new AbortController();
    mutationController.current = request;
    const generation = ++mutationGeneration.current;
    const payload = new FormData();
    payload.append("file", selectedFile);
    if (label.trim()) payload.append("label", label.trim());
    payload.append("client_visible", clientVisible ? "true" : "false");
    setUploading(true);
    setUploadError("");
    setNotice("");
    try {
      await api<RequestDocument>(endpoint, {
        method: "POST",
        body: payload,
        signal: request.signal,
      });
      if (
        !mounted.current ||
        request.signal.aborted ||
        mutationGeneration.current !== generation
      )
        return;
      setSelectedFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setLabel("");
      setClientVisible(false);
      setNotice(
        "Le fichier a été enregistré sur le serveur et rattaché au dossier SAV.",
      );
      await load();
      if (
        !mounted.current ||
        request.signal.aborted ||
        mutationGeneration.current !== generation
      )
        return;
      await notifyChanged(generation);
    } catch (err) {
      if (
        !mounted.current ||
        request.signal.aborted ||
        mutationGeneration.current !== generation
      )
        return;
      setUploadError(
        err instanceof TypeError
          ? "Le serveur n’a pas confirmé l’enregistrement. Actualisez la liste avant de recommencer le téléversement."
          : err instanceof Error
            ? err.message
            : "L’ajout du fichier n’a pas pu être confirmé.",
      );
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        mutationGeneration.current === generation
      ) {
        mutating.current = false;
        setUploading(false);
      }
    }
  }

  async function remove(documentId: number) {
    const document = documents.find((item) => item.id === documentId);
    if (
      isClient ||
      !document?.can_delete ||
      loading ||
      loadError ||
      mutating.current
    )
      return;
    mutating.current = true;
    mutationController.current?.abort();
    const request = new AbortController();
    mutationController.current = request;
    const generation = ++mutationGeneration.current;
    setDeletingId(documentId);
    setDeleteError("");
    setNotice("");
    try {
      const result = await api<{ detail?: string } | null | undefined>(
        `documents/${documentId}/`,
        {
          method: "DELETE",
          signal: request.signal,
        },
      );
      if (
        !mounted.current ||
        request.signal.aborted ||
        mutationGeneration.current !== generation
      )
        return;
      setDeleteCandidate(null);
      setData((previous) =>
        previous
          ? {
              ...previous,
              results: previous.results.filter(
                (item) => item.id !== documentId,
              ),
            }
          : previous,
      );
      setNotice(
        typeof result?.detail === "string" && result.detail.trim()
          ? result.detail
          : "Le document a été supprimé du dossier.",
      );
      await load();
      if (
        !mounted.current ||
        request.signal.aborted ||
        mutationGeneration.current !== generation
      )
        return;
      await notifyChanged(generation);
    } catch (err) {
      if (
        !mounted.current ||
        request.signal.aborted ||
        mutationGeneration.current !== generation
      )
        return;
      setDeleteError(
        err instanceof TypeError
          ? "Le serveur n’a pas confirmé la suppression. Actualisez la liste avant de réessayer."
          : err instanceof Error
            ? err.message
            : "La suppression n’a pas pu être confirmée.",
      );
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        mutationGeneration.current === generation
      ) {
        mutating.current = false;
        setDeletingId(null);
      }
    }
  }

  return (
    <section
      className="request-documents"
      aria-label="Documents du dossier SAV"
    >
      <div className="request-documents-header">
        <div className="request-documents-heading">
          <FolderOpen size={20} />
          <div>
            <h3>Documents du dossier</h3>
            <p>
              {isClient
                ? "Retrouvez les fichiers partagés par votre équipe SAV."
                : "Joignez les photos, justificatifs et documents utiles au suivi SAV."}
            </p>
          </div>
          {data && (
            <span className="badge blue">
              {documents.length} document{documents.length > 1 ? "s" : ""}
            </span>
          )}
        </div>
        <div className="request-documents-actions">
          <button
            type="button"
            className="button secondary small"
            disabled={loading || busy}
            onClick={() => void load()}
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            Actualiser
          </button>
          {canUpload && (
            <button
              type="button"
              className="button primary small"
              disabled={busy}
              aria-expanded={uploadOpen}
              aria-controls={`${id}-upload`}
              onClick={() => setUploadOpen((value) => !value)}
            >
              <Upload size={15} />
              Ajouter un document
            </button>
          )}
        </div>
      </div>

      {notice && (
        <p className="request-documents-success" role="status">
          <CheckCircle2 size={16} />
          {notice}
        </p>
      )}
      {!isClient && data && !canUpload && (
        <p className="request-documents-help">
          <LockKeyhole size={14} />
          Lecture seule. Les ajouts et suppressions dépendent de vos droits sur
          ce dossier.
        </p>
      )}

      {canUpload && uploadOpen && (
        <div
          id={`${id}-upload`}
          className="request-documents-upload"
          role="group"
          aria-labelledby={`${id}-upload-title`}
        >
          <h4 id={`${id}-upload-title`}>Ajouter un fichier au dossier SAV</h4>
          <div className="request-documents-fields">
            <div className="request-documents-field">
              <label htmlFor={`${id}-file`}>Fichier</label>
              <input
                ref={fileInput}
                id={`${id}-file`}
                type="file"
                className="input"
                accept={acceptedFiles}
                disabled={busy}
                aria-describedby={`${id}-file-help`}
                onChange={(event) => {
                  setSelectedFile(event.target.files?.[0] || null);
                  setUploadError("");
                }}
              />
              <p id={`${id}-file-help`} className="request-documents-help">
                Un fichier par envoi · {fileSize(maximumSize)} maximum ·{" "}
                {allowedExtensions.join(", ").toUpperCase()}.
              </p>
              {selectedFile && (
                <p className="request-documents-selection">
                  {selectedFile.name} · {fileSize(selectedFile.size)}
                </p>
              )}
            </div>
            <div className="request-documents-field">
              <label htmlFor={`${id}-label`}>Libellé (facultatif)</label>
              <input
                id={`${id}-label`}
                className="input"
                value={label}
                maxLength={200}
                disabled={busy}
                placeholder="Ex. Photos du diagnostic, justificatif d’achat…"
                aria-describedby={`${id}-label-help`}
                onChange={(event) => {
                  setLabel(event.target.value);
                  setUploadError("");
                }}
              />
              <p id={`${id}-label-help`} className="request-documents-help">
                200 caractères maximum. Le nom du fichier sera conservé.
              </p>
            </div>
          </div>
          <label
            className="request-documents-visibility"
            htmlFor={`${id}-shared`}
          >
            <input
              id={`${id}-shared`}
              type="checkbox"
              checked={clientVisible}
              disabled={busy}
              onChange={(event) => setClientVisible(event.target.checked)}
            />
            <Share2 size={15} />
            Partager ce document avec le client du dossier
          </label>
          <p className="request-documents-help">
            <Info size={14} />
            {clientVisible
              ? "Le fichier sera accessible dans le portail de ce client."
              : "Le fichier restera réservé à l’équipe interne."}
          </p>
          {data?.virus_scanned === false && (
            <p className="request-documents-help">
              Le serveur contrôle le format et la taille. Les fichiers ne sont
              pas analysés par un antivirus.
            </p>
          )}
          {uploadError && (
            <div className="request-documents-error" role="alert">
              <AlertCircle size={16} />
              <span>{uploadError}</span>
            </div>
          )}
          <div className="request-documents-actions">
            <button
              type="button"
              className="button primary small"
              disabled={busy || loading || !!loadError || !selectedFile}
              onClick={() => void upload()}
            >
              {uploading ? (
                <LoaderCircle size={15} className="spin" />
              ) : (
                <Upload size={15} />
              )}
              {uploading ? "Téléversement…" : "Enregistrer le fichier"}
            </button>
            <button
              type="button"
              className="button secondary small"
              disabled={busy}
              onClick={() => setUploadOpen(false)}
            >
              Fermer
            </button>
          </div>
        </div>
      )}

      {loading && (
        <p className="request-documents-status" role="status">
          <LoaderCircle size={16} className="spin" />
          Chargement des documents…
        </p>
      )}
      {loadError && (
        <div className="request-documents-error" role="alert">
          <AlertCircle size={16} />
          <div>
            <p>{loadError}</p>
            <button
              type="button"
              className="button secondary small"
              disabled={loading || busy}
              onClick={() => void load()}
            >
              Réessayer
            </button>
          </div>
        </div>
      )}
      {!loading && data && documents.length === 0 && !loadError && (
        <div className="request-documents-empty" role="status">
          <FolderOpen size={32} />
          <h4>
            {isClient
              ? "Aucun document partagé"
              : "Aucun document pour ce dossier"}
          </h4>
          <p>
            {isClient
              ? "Les fichiers partagés par votre équipe SAV apparaîtront ici."
              : "Ajoutez un premier fichier pour le retrouver depuis les différents postes de l’équipe."}
          </p>
        </div>
      )}

      <ul className="request-documents-list" aria-busy={loading}>
        {documents.map((document) => (
          <li key={document.id} className="request-documents-item">
            <div className="request-documents-file-icon" aria-hidden="true">
              <FileIcon mimeType={document.mime_type} />
            </div>
            <div className="request-documents-file-details">
              <strong>{document.label || document.original_name}</strong>
              {document.label && document.label !== document.original_name && (
                <p>{document.original_name}</p>
              )}
              <div className="request-documents-file-meta">
                <span>{fileSize(document.size_bytes)}</span>
                <time dateTime={document.created_at}>
                  {uploadDate(document.created_at)}
                </time>
                <span>
                  {isClient
                    ? "Équipe SAV"
                    : document.uploaded_by_name || "Équipe SAV"}
                </span>
                <span
                  className={`badge ${document.client_visible ? "blue" : "amber"}`}
                >
                  {document.client_visible ? (
                    <Share2 size={11} />
                  ) : (
                    <LockKeyhole size={11} />
                  )}
                  {document.client_visible
                    ? "Partagé avec le client"
                    : "Interne"}
                </span>
              </div>
            </div>
            <div className="request-documents-actions">
              <a
                className="button secondary small"
                href={protectedDownload(document)}
                download={document.original_name}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Télécharger ${document.original_name}`}
              >
                <Download size={15} />
                Télécharger
              </a>
              {!isClient && document.can_delete && (
                <button
                  type="button"
                  className="button secondary small"
                  disabled={busy || loading || !!loadError}
                  aria-expanded={deleteCandidate === document.id}
                  aria-controls={`${id}-delete-${document.id}`}
                  onClick={() => {
                    setDeleteCandidate(document.id);
                    setDeleteError("");
                  }}
                  aria-label={`Supprimer ${document.original_name}`}
                >
                  <Trash2 size={14} />
                  Supprimer
                </button>
              )}
            </div>
            {!isClient &&
              document.can_delete &&
              deleteCandidate === document.id && (
                <div
                  id={`${id}-delete-${document.id}`}
                  className="request-documents-delete-confirm"
                  role="group"
                  aria-labelledby={`${id}-delete-title-${document.id}`}
                >
                  <strong id={`${id}-delete-title-${document.id}`}>
                    Supprimer ce document du dossier ?
                  </strong>
                  <p>
                    {document.original_name} ne sera plus disponible pour
                    l’équipe ni pour le client.
                  </p>
                  {deleteError && (
                    <p className="request-documents-error" role="alert">
                      <AlertCircle size={16} />
                      {deleteError}
                    </p>
                  )}
                  <div className="request-documents-actions">
                    <button
                      type="button"
                      className="button danger small"
                      disabled={busy || loading || !!loadError}
                      onClick={() => void remove(document.id)}
                    >
                      {deletingId === document.id ? (
                        <LoaderCircle size={14} className="spin" />
                      ) : (
                        <Trash2 size={14} />
                      )}
                      {deletingId === document.id
                        ? "Suppression…"
                        : "Confirmer la suppression"}
                    </button>
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={busy}
                      onClick={() => {
                        setDeleteCandidate(null);
                        setDeleteError("");
                      }}
                    >
                      Annuler
                    </button>
                  </div>
                </div>
              )}
          </li>
        ))}
      </ul>
    </section>
  );
}
