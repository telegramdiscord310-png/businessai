// Client de l'API : cookies de session, jeton CSRF, messages d'erreur en français.
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

let csrfToken = "";
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string) {
  csrfToken = token;
}

export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

async function request<T>(method: string, url: string, body?: unknown, options: { silent401?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
  } catch {
    throw new ApiError("Impossible de joindre le serveur. Vérifiez votre connexion Internet, puis réessayez.", 0);
  }
  if (response.status === 401 && !options.silent401) onUnauthorized?.();
  if (!response.ok) {
    let message = "";
    try {
      const data = await response.json();
      if (typeof data?.detail === "string") message = data.detail;
    } catch {
      /* réponse non JSON */
    }
    if (!message) {
      message =
        response.status === 413
          ? "Fichier trop volumineux."
          : response.status >= 500
            ? "Le serveur a rencontré une erreur. Réessayez dans un instant ; le détail est dans la page Logs."
            : "La demande n'a pas pu aboutir.";
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(url: string, options?: { silent401?: boolean }) => request<T>("GET", url, undefined, options),
  post: <T>(url: string, body?: unknown, options?: { silent401?: boolean }) => request<T>("POST", url, body ?? {}, options),
  put: <T>(url: string, body?: unknown) => request<T>("PUT", url, body ?? {}),
  patch: <T>(url: string, body?: unknown) => request<T>("PATCH", url, body ?? {}),
  delete: <T>(url: string) => request<T>("DELETE", url),
  upload: <T>(url: string, form: FormData) => request<T>("POST", url, form),
};

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Une erreur est survenue.";
}
