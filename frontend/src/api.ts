const API_BASE = import.meta.env.VITE_API_BASE || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type Source = {
  id: number;
  name: string;
  base_url: string;
  adapter_key: string;
  enabled: boolean;
  config: Record<string, unknown>;
  last_scan_at: string | null;
};

export type Listing = {
  id: number;
  source_id: number;
  external_id: string;
  title: string;
  url: string;
  employment_type: string | null;
  location: string | null;
  description: string | null;
  summary: string | null;
  status: string;
  relevance_score: number | null;
  source_name: string | null;
  latest_confidence: number | null;
  latest_reason: string | null;
  viewed_at: string | null;
  disappeared: boolean;
};

export type ScanRun = {
  id: number;
  source_id: number | null;
  started_at: string;
  finished_at: string | null;
  status: string;
  discovered: number;
  upserted: number;
  classified: number;
  candidates: number;
  errors: string | null;
  source_name: string | null;
};

export type Settings = {
  staffing_keywords: string[];
  employment_allowlist: string[];
  employment_blocklist: string[];
  confidence_candidate: number;
  confidence_review: number;
  scan_interval_hours: number;
  agent_max_listings: number;
  agent_max_pages: number;
  llm_model: string;
  llm_base_url: string;
  llm_api_key_set: boolean;
  llm_api_key_masked: string;
  llm_source: string;
};

export type SettingsUpdate = Partial<
  Omit<Settings, "llm_api_key_set" | "llm_api_key_masked" | "llm_source">
> & {
  llm_api_key?: string;
  clear_llm_api_key?: boolean;
};

export type SourceProposal = {
  id: number;
  name: string;
  career_url: string;
  base_url: string;
  origin: string;
  kind: string;
  broker_risk: number;
  reasons: string[] | Record<string, unknown> | null;
  status: string;
  raw_snippet: string | null;
  query: string | null;
  created_at: string;
  updated_at: string;
};

export type DiscoveryProposeResult = {
  created: SourceProposal[];
  updated: SourceProposal[];
  skipped: { query: string; reason: string }[];
};

export type DiscoveryHarvestResult = {
  created: SourceProposal[];
  updated: SourceProposal[];
  blocked: number;
};

export type SourceDuplicate = {
  left_id: number;
  left_name: string;
  left_url: string | null;
  right_id: number;
  right_name: string;
  right_url: string | null;
  reasons: string[];
};

export type CrawlRunRequest = {
  max_pages?: number;
  max_new_urls?: number;
  min_relevance?: number;
  queries?: string[];
  seed_urls?: string[];
};

export type CrawlRunResult = {
  run: ScanRun;
  source_id: number;
  pages_fetched: number;
  discovered: number;
  upserted: number;
  skipped_broker: number;
  skipped_low_score: number;
  skipped_dup: number;
  skipped_domain: number;
  skipped_unusable: number;
  skipped_recent: number;
  rejudged_discarded: number;
  proposals_created: number;
  avg_relevance: number;
  errors: string[];
};

export type CrawlRejudgeResult = {
  reviewed: number;
  kept: number;
  discarded: number;
};

export type CrawlClearResult = {
  listings: number;
  classifications: number;
  reviews: number;
  runs: number;
  proposals: number;
  visits: number;
};

/** Extract a readable message from FastAPI JSON error bodies. */
export function formatApiError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      return parsed.detail
        .map((item) => (typeof item === "object" && item && "msg" in item ? String((item as { msg: string }).msg) : String(item)))
        .join("; ");
    }
  } catch {
    // not JSON
  }
  return raw;
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  listSources: () => request<Source[]>("/api/sources"),
  createSource: (body: Partial<Source> & { name: string; base_url: string; adapter_key: string }) =>
    request<Source>("/api/sources", { method: "POST", body: JSON.stringify(body) }),
  updateSource: (id: number, body: Partial<Source>) =>
    request<Source>(`/api/sources/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSource: (id: number) => request<{ ok: boolean }>(`/api/sources/${id}`, { method: "DELETE" }),
  listListings: (status?: string) =>
    request<Listing[]>(`/api/listings${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  markListingViewed: (id: number) =>
    request<Listing>(`/api/listings/${id}/view`, { method: "POST" }),
  reviewListing: (id: number, decision: string, note?: string) =>
    request(`/api/listings/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ decision, note }),
    }),
  listScans: () => request<ScanRun[]>("/api/scans"),
  runAllScans: () => request<{ ok: boolean }>("/api/scans/run", { method: "POST" }),
  runSourceScan: (id: number) =>
    request<{ ok: boolean }>(`/api/scans/run/${id}`, { method: "POST" }),
  getSettings: () => request<Settings>("/api/settings"),
  updateSettings: (body: SettingsUpdate) =>
    request<Settings>("/api/settings", { method: "PATCH", body: JSON.stringify(body) }),
  proposeSources: (queries: string[]) =>
    request<DiscoveryProposeResult>("/api/discovery/propose", {
      method: "POST",
      body: JSON.stringify({ queries }),
    }),
  harvestPortals: () =>
    request<DiscoveryHarvestResult>("/api/discovery/harvest", { method: "POST" }),
  listProposals: (status = "pending") =>
    request<SourceProposal[]>(
      `/api/discovery/proposals${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),
  approveProposal: (id: number, force = false) =>
    request<Source>(`/api/discovery/proposals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ force }),
    }),
  rejectProposal: (id: number) =>
    request<SourceProposal>(`/api/discovery/proposals/${id}/reject`, { method: "POST" }),
  listSourceDuplicates: () => request<SourceDuplicate[]>("/api/discovery/duplicates"),
  runWebCrawl: (body: CrawlRunRequest = {}) =>
    request<CrawlRunResult>("/api/crawl/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  rejudgeCrawl: () =>
    request<CrawlRejudgeResult>("/api/crawl/rejudge", { method: "POST" }),
  clearCrawl: () =>
    request<CrawlClearResult>("/api/crawl/clear", { method: "POST" }),
  listCrawlRuns: () => request<ScanRun[]>("/api/crawl/runs"),
};
