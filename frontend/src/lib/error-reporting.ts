type ErrorContext = Record<string, unknown>;

/**
 * Log an unhandled UI error to the browser console.
 *
 * Loaders and server functions often throw a raw `Response`, and
 * `String(response)` collapses to the useless "[object Response]" — so pull the
 * status and URL out instead and keep the message readable.
 */
export function reportAppError(error: unknown, context: ErrorContext = {}): void {
  if (typeof window === "undefined") return;

  const message =
    error instanceof Response
      ? `Response ${error.status}${error.url ? ` at ${error.url}` : ""}`
      : error instanceof Error
        ? error.message
        : String(error);

  console.error("[app-error]", { message, ...context });
}