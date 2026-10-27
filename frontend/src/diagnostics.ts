export type KnowledgeState = "draft" | "approved" | "archived";
export type KnowledgeDocument = {
  id: number;
  title: string;
  brand: string;
  model: string;
  board_reference: string;
  revision: string;
  kind: "manual" | "schematic" | "procedure";
  state: KnowledgeState;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  pages: number;
  text_status: "extracted" | "partial" | "no_text";
  warnings: string[];
  created_at: string;
  created_by_name: string;
  approved_at: string | null;
  approved_by_name: string;
  archived_at: string | null;
  chunk_count: number;
  download_url: string;
};
export type KnowledgeCase = {
  id: number;
  intervention: number;
  source_intervention_reference: string;
  revision?: string;
  brand: string;
  model: string;
  board_reference: string;
  symptoms: string;
  fault_code: string;
  measurements: string;
  confirmed_cause: string;
  repair: string;
  outcome: string;
  state: KnowledgeState;
  eligible_for_retrieval: boolean;
  warnings: string[];
  created_at: string;
  created_by_name: string;
  approved_at: string | null;
  approved_by_name: string;
};
export type DiagnosticInput = {
  brand: string;
  model: string;
  symptoms: string;
  fault_code: string;
  measurements: string;
  service_request?: number;
  board_reference?: string;
  revision?: string;
};
export type DiagnosticSource = {
  id: string | number;
  title: string;
  kind: "document" | "case";
  page: number | null;
  excerpt: string;
  document_id?: number;
  case_id?: number;
  download_url?: string;
  url?: string;
  brand?: string;
  model?: string;
  revision?: string;
  board_reference?: string;
  available?: boolean;
};
export type DiagnosticResult = {
  id?: number;
  status: string;
  sources: DiagnosticSource[];
  input?: DiagnosticInput;
  output?: {
    summary: string;
    hypotheses: {
      title: string;
      explanation: string;
      source_ids: (string | number)[];
    }[];
    checks: { instructions: string; source_ids: (string | number)[] }[];
    missing_information: string[];
    uncertainties: string[];
  } | null;
  warnings: string[];
  created_at?: string;
};
export type DiagnosticStatus = {
  configured?: boolean;
  enabled?: boolean;
  available?: boolean;
  provider_configured?: boolean;
  provider_tested?: boolean;
  status?: string;
  message?: string;
  detail?: string;
  model?: string;
  provider?: string;
  [key: string]: unknown;
};
export const knowledgeStateLabels: Record<KnowledgeState, string> = {
  draft: "Brouillon",
  approved: "Approuvé",
  archived: "Archivé",
};
export const documentKindLabels = {
  manual: "Manuel technique",
  schematic: "Schéma électronique",
  procedure: "Procédure",
};
export const textStatusLabels = {
  extracted: "Texte extrait",
  partial: "Extraction partielle",
  no_text: "Sans texte indexable",
};
