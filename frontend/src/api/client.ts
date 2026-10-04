import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";
import { tokenStore } from "@/lib/tokens";

type S = components["schemas"];
export type UserOut = S["UserOut"];
export type TokenOut = S["TokenOut"];
export type EventOut = S["EventOut"];
export type EventDetail = S["EventDetail"];
export type EventStats = S["EventStats"];
export type EvidenceOut = S["EvidenceOut"];
export type CompetitorOut = S["CompetitorOut"];
export type CompetitorListItem = S["CompetitorListItem"];
export type CompetitorIn = S["CompetitorIn"];
export type PricePointOut = S["PricePointOut"];
export type CompetitorProductOut = S["CompetitorProductOut"];
export type RelationshipOut = S["RelationshipOut"];
export type RelationshipGraph = S["RelationshipGraph"];
export type SourceOut = S["SourceOut"];
export type SourceIn = S["SourceIn"];
export type SourceTestOut = S["SourceTestOut"];
export type SnapshotMeta = S["SnapshotMeta"];
export type SnapshotOut = S["SnapshotOut"];
export type AlertOut = S["AlertOut"];
export type SubscriptionOut = S["SubscriptionOut"];
export type SubscriptionIn = S["SubscriptionIn"];
export type BriefMeta = S["BriefMeta"];
export type BriefOut = S["BriefOut"];
export type KnowledgeHit = S["KnowledgeHit"];
export type AgentRunOut = S["AgentRunOut"];
export type AgentRunDetail = S["AgentRunDetail"];
export type AgentStepOut = S["AgentStepOut"];
export type OrgOut = S["OrgOut"];
export type ApiKeyOut = S["ApiKeyOut"];
export type ApiKeyCreated = S["ApiKeyCreated"];
export type CompanyProfileOut = S["CompanyProfileOut"];
export type OwnProductOut = S["OwnProductOut"];
export type OwnPriceOut = S["OwnPriceOut"];
export type SegmentOut = S["SegmentOut"];
export type LLMStatus = S["LLMStatus"];
export type Priority = S["Priority"];
export type Role = S["Role"];
export type ChangeCategory = S["ChangeCategory"];
export type SourceType = S["SourceType"];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const d = (error as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? String(x)).join("; ");
  }
  return "Request failed";
}

const auth: Middleware = {
  async onRequest({ request }) {
    const token = await tokenStore.freshAccessToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 401 && tokenStore.hasSession()) tokenStore.expire();
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(auth);

/** Unwraps an openapi-fetch result, throwing ApiError on failure. */
export async function call<T>(
  p: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await p;
  if (error !== undefined || !response.ok) throw new ApiError(response.status, errorMessage(error));
  return data as T;
}
