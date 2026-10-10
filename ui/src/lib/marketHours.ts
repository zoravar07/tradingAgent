/**
 * US equity regular session, evaluated in America/New_York regardless of
 * where the machine's clock is set — the whole point of the sidebar readout
 * is that it tells you about the market, not about your timezone.
 *
 * Weekends are handled; market holidays are not, because the app has no
 * holiday calendar and inventing one that silently drifts out of date would
 * be worse than a readout that is honest about following the regular
 * schedule. The label says "Regular hours" for exactly that reason.
 */
const OPEN_MINUTES = 9 * 60 + 30; // 09:30 ET
const CLOSE_MINUTES = 16 * 60; // 16:00 ET

export interface MarketStatus {
  open: boolean;
  /** Seconds until the session closes (when open) or opens (when closed). */
  secondsUntilChange: number;
}

/** The wall-clock parts of `now` as they read in New York. */
function easternParts(now: Date): { minutes: number; seconds: number; weekday: number } {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    weekday: "short",
    hour12: false,
  });
  const parts = Object.fromEntries(fmt.formatToParts(now).map((p) => [p.type, p.value]));
  const hour = Number(parts.hour) % 24;
  const minute = Number(parts.minute);
  const second = Number(parts.second);
  const weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(parts.weekday ?? "Sun");
  return { minutes: hour * 60 + minute, seconds: second, weekday };
}

export function marketStatus(now: Date = new Date()): MarketStatus {
  const { minutes, seconds, weekday } = easternParts(now);
  const isWeekday = weekday >= 1 && weekday <= 5;
  const open = isWeekday && minutes >= OPEN_MINUTES && minutes < CLOSE_MINUTES;

  if (open) {
    return { open: true, secondsUntilChange: (CLOSE_MINUTES - minutes) * 60 - seconds };
  }

  // Minutes from now until the next 09:30 ET that falls on a weekday.
  let daysAhead = 0;
  let minutesToOpen = OPEN_MINUTES - minutes;
  if (!isWeekday || minutes >= OPEN_MINUTES) {
    daysAhead = 1;
    minutesToOpen += 24 * 60;
  }
  let day = (weekday + daysAhead) % 7;
  while (day === 0 || day === 6) {
    minutesToOpen += 24 * 60;
    day = (day + 1) % 7;
  }
  return { open: false, secondsUntilChange: minutesToOpen * 60 - seconds };
}

/** "03:02:17" — hours:minutes:seconds, zero-padded, hours uncapped. */
export function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}
