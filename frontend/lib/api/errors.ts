const FRIENDLY: Record<string, string> = {
  permission_denied: "You don't have permission to do that.",
  password_change_required: "Please set a new password first.",
  two_factor_setup_required: "Please set up two-factor authentication first.",
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown, // the full error body (some errors carry more, e.g. the duplicate)
  ) {
    super(message);
  }
}

/** Turn a FastAPI error body ({detail: string | validation list}) into one readable line. */
export function messageFrom(error: unknown, fallback = "Something went wrong. Please try again."): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return FRIENDLY[detail] ?? detail;
  if (Array.isArray(detail) && detail[0]?.msg) {
    return String(detail[0].msg).replace(/^Value error, /, "");
  }
  return fallback;
}

/** Return data, or throw an ApiError with a readable message. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok) {
    throw new ApiError(result.response.status, messageFrom(result.error), result.error);
  }
  return result.data as T;
}
