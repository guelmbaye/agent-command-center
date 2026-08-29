// Client du Control Plane. Le frontend ne devine jamais l'etat : il le lit.
import type {
  Agent, Approval, Checkpoint, FleetMetrics, MissionDetail, MissionSummary,
  PolicyBoundary, RecoveryAttempt, TimelineEvent, TraceNode,
} from "./types";

// 127.0.0.1 plutôt que "localhost" : sous Windows, "localhost" résout d'abord
// en IPv6 (::1). Uvicorn n'écoute qu'en IPv4, donc un autre service lié à
// [::1]:8080 (Apache/XAMPP, IIS, un proxy) intercepte silencieusement les
// appels et renvoie ses propres 404.
export const API_BASE =
  process.env.NEXT_PUBLIC_ACC_API ?? "http://127.0.0.1:8080";

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

export const streamUrl = (missionId: string) =>
  `${API_BASE}/api/v1/missions/${missionId}/stream`;
