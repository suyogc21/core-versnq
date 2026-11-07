/** Apply a workspace brand colour; text on it becomes black or white, whichever reads better. */
export function applyAccent(hex: string | undefined | null) {
  const colour = /^#[0-9a-f]{6}$/i.test(hex ?? "") ? (hex as string) : DEFAULT_ACCENT;
  const n = parseInt(colour.slice(1), 16);
  const [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255];
  const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  const fg = luminance > 0.6 ? "#111111" : "#ffffff";
  const root = document.documentElement.style;
  for (const v of ["--primary", "--ring", "--sidebar-primary"]) root.setProperty(v, colour);
  for (const v of ["--primary-foreground", "--sidebar-primary-foreground"]) root.setProperty(v, fg);
}

export const DEFAULT_ACCENT = "#4f46e5";
