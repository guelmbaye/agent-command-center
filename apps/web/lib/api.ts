// Client du Control Plane. Le frontend ne devine jamais l'etat : il le lit.
import type {
  Agent, Approval, Checkpoint, FleetMetrics, MissionDetail, MissionSummary,
  PolicyBoundary, RecoveryAttempt, TimelineEvent, TraceNode,
} from "./types";

// 127.0.0.1 rather than "localhost": on Windows, "localhost" resolves to IPv6
// (::1) first. Uvicorn listens on IPv4 only, so another service bound to
// [::1]:8080 (Apache/XAMPP, IIS, a proxy) silently intercepts the calls and
// answers with its own 404s.
const LOCAL_FALLBACK = "http://127.0.0.1:8080";

/**
 * Resolve the control plane URL.
 *
 * `NEXT_PUBLIC_*` is frozen AT BUILD TIME. On Cloud Run the API URL only
 * exists after `terraform apply`, so the very first image is necessarily built
 * without it — passing it as a runtime environment variable has no effect,
 * because the value was already inlined into the bundle.
 *
 * Both services share the same Cloud Run URL suffix within a project and
 * region, so the control plane can be derived from the page's own origin.
 * A later deployment bakes the real value in (deploy.py passes it as a build
 * argument once it is known) and this derivation is then never used.
 */
function resolveApiBase(): string {
  const baked = process.env.NEXT_PUBLIC_ACC_API;

  // `if (baked)`, never `baked ?? fallback`. The Dockerfile does
  // `ENV NEXT_PUBLIC_ACC_API=${ARG}`, so with no --build-arg the value is the
  // EMPTY STRING, not undefined. `??` only catches null and undefined, so an
  // empty string won, every call became relative, and the deployed Mission
  // Control queried its own origin — answering 404 for /api/v1/*.
  if (baked) return baked;

  if (typeof window !== "undefined") {
    const origin = window.location.origin;
    if (origin.includes("acc-web")) return origin.replace("acc-web", "acc-api");
  }
  return LOCAL_FALLBACK;
}

export const API_BASE = resolveApiBase();

const API_KEY = process.env.NEXT_PUBLIC_ACC_API_KEY ?? "";

export class ApiError extends Error {
  constructor(readonly code: string, message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(API_KEY ? { "x-api-key": API_KEY } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    // Contrat d'erreur unifié du Control Plane (Doc 08 §26).
    let code = "HTTP_ERROR";
    let message = response.statusText;
    let fromAcc = false;
    try {
      const body = await response.json();
      if (body?.error?.code) {
        code = body.error.code;
        message = body.error.message ?? message;
        fromAcc = true;
      }
    } catch {
      /* corps non JSON : très probablement une réponse étrangère */
    }
    // Une 404 qui ne respecte pas notre contrat ne vient pas d'ACC : c'est
    // presque toujours un autre serveur sur le port. Le dire explicitement
    // évite une demi-heure de recherche du côté du backend.
    if (!fromAcc && response.status === 404) {
      throw new ApiError(
        "NOT_ACC",
        `Unexpected response from ${API_BASE} ("${message}"): this port is ` +
          `probably held by another server. Check with ` +
          `"netstat -ano | findstr :8080", then "python scripts/doctor.py".`,
        404,
      );
    }
    throw new ApiError(code, message, response.status);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  listMissions: () =>
    request<{ missions: MissionSummary[]; count: number }>("/api/v1/missions"),

  getMission: (id: string) => request<MissionDetail>(`/api/v1/missions/${id}`),

  createMission: (params: {
    objective?: string;
    required_units?: number;
    deadline_hours?: number;
    priority?: string;
  } = {}) =>
    request<{ mission_id: string; status: string }>("/api/v1/missions", {
      method: "POST",
      body: JSON.stringify({
        objective: params.objective || "Protect production schedule",
        required_units: params.required_units ?? null,
        deadline_hours: params.deadline_hours ?? null,
        priority: params.priority ?? "HIGH",
        autostart: true,
      }),
    }),

  timeline: (id: string) =>
    request<{ events: TimelineEvent[] }>(`/api/v1/missions/${id}/timeline`),

  trace: (id: string) =>
    request<{ trace: TraceNode[]; objective: string; trace_id: string | null }>(
      `/api/v1/missions/${id}/trace`,
    ),

  recoveries: (id: string) =>
    request<{ recoveries: RecoveryAttempt[] }>(`/api/v1/missions/${id}/recoveries`),

  checkpoints: (id: string) =>
    request<{ checkpoints: Checkpoint[] }>(`/api/v1/missions/${id}/checkpoints`),

  resume: (id: string, checkpointId?: string) =>
    request<MissionSummary>(`/api/v1/missions/${id}/resume`, {
      method: "POST",
      body: JSON.stringify({ checkpoint_id: checkpointId ?? null }),
    }),

  agents: () => request<{ agents: Agent[] }>("/api/v1/agents"),

  approvals: (status = "PENDING") =>
    request<{ approvals: Approval[] }>(`/api/v1/approvals?status=${status}`),

  decideApproval: (id: string, approve: boolean, comment?: string) =>
    request<Approval>(`/api/v1/approvals/${id}/${approve ? "approve" : "reject"}`, {
      method: "POST",
      body: JSON.stringify({ decided_by: "operator", comment: comment ?? null }),
    }),

  metrics: () => request<FleetMetrics>("/api/v1/metrics"),

  policy: () => request<PolicyBoundary>("/api/v1/policy"),

  // Demo controls — deterministic, jamais aléatoires.
  demo: {
    reset: () => request<unknown>("/api/v1/demo/reset", { method: "POST" }),
    failSupplierA: () =>
      request<unknown>("/api/v1/demo/fail/supplier-a", { method: "POST" }),
    restoreSupplierA: () =>
      request<unknown>("/api/v1/demo/restore/supplier-a", { method: "POST" }),
    injectMalicious: () =>
      request<unknown>("/api/v1/demo/inject/malicious-input", { method: "POST" }),
    interrupt: (missionId: string) =>
      request<unknown>(`/api/v1/demo/interrupt-agent?mission_id=${missionId}`, {
        method: "POST",
      }),
  },
};

/**
 * SSE stream URL.
 *
 * The key goes in the query string because `EventSource` CANNOT set request
 * headers — there is no API for it. Without this the stream answered 401 and
 * the UI fell back to polling, losing the live timeline that carries the demo.
 */
export const streamUrl = (missionId: string) => {
  const base = `${API_BASE}/api/v1/missions/${missionId}/stream`;
  return API_KEY ? `${base}?api_key=${encodeURIComponent(API_KEY)}` : base;
};
