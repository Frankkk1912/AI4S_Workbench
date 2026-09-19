export const UNKNOWN = "未知";
export const UNKNOWN_ETA = "unavailable";

/** Render a display value as "未知" when it is missing or a fake value. */
export function formatUnknown(
  value: string | number | null | undefined,
): string {
  if (value === null || value === undefined) return UNKNOWN;
  const text = String(value).trim();
  if (text === "" || text === UNKNOWN_ETA) return UNKNOWN;
  return text;
}

export function formatNumber(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return UNKNOWN;
  }
  return value.toFixed(digits);
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString();
}
