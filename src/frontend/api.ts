/**
 * Pemanggil API dasar (menyertakan token CSRF otomatis pada method yang mengubah data). Klien bertipe hasil `simpy generate` (.simpy/api.ts) memakai `request`.
 * Hanya path satu origin yang diizinkan (mis. "/api/hello"), jadi tidak bisa dipakai untuk
 * mengirim data ke situs lain.
 */

import { currentCsrfToken } from "./csrf.ts";

export interface ApiErrorDetail {
  readonly loc: readonly (string | number)[];
  readonly msg: string;
}

/** Error dari server (status >= 400), atau status 0 bila server tidak terjangkau. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: readonly ApiErrorDetail[];

  constructor(
    status: number,
    code: string,
    message: string,
    details: readonly ApiErrorDetail[] = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  readonly body?: unknown;
  readonly signal?: AbortSignal;
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

function isDetail(value: unknown): value is ApiErrorDetail {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as { loc?: unknown; msg?: unknown };
  return Array.isArray(candidate.loc) && typeof candidate.msg === "string";
}

function toApiError(status: number, payload: unknown, statusText: string): ApiError {
  if (typeof payload === "object" && payload !== null) {
    const body = payload as { error?: unknown; message?: unknown; details?: unknown };
    if (typeof body.error === "string" && typeof body.message === "string") {
      const details = Array.isArray(body.details) ? body.details.filter(isDetail) : [];
      return new ApiError(status, body.error, body.message, details);
    }
  }
  return new ApiError(status, "http_error", statusText || "Permintaan gagal.");
}

export async function request<T>(
  method: HttpMethod,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Path API harus relatif ke origin yang sama, mis. '/api/hello'.");
  }
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method, headers, credentials: "same-origin" };
  if (options.signal) {
    init.signal = options.signal;
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  if (method !== "GET") {
    const csrfToken = currentCsrfToken();
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
  }

  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new ApiError(0, "network_error", "Tidak dapat terhubung ke server.");
  }

  if (response.status === 204) {
    return undefined as T;
  }
  const mediaType = (response.headers.get("content-type") ?? "").split(";")[0]?.trim().toLowerCase();
  const isJson = mediaType === "application/json";
  let payload: unknown;
  if (isJson) {
    try {
      payload = await response.json();
    } catch {
      payload = undefined;
    }
  }
  if (!response.ok) {
    throw toApiError(response.status, payload, response.statusText);
  }
  if (!isJson || payload === undefined) {
    throw new ApiError(response.status, "invalid_response", "Respons server bukan JSON yang valid.");
  }
  return payload as T;
}
