import { describe, expect, it } from "vitest";
import { addDays, fmtDate, fromInput, hm, startOfWeek, toInput, weekLabel, ymd } from "./dates";

describe("dates", () => {
  it("formats ymd with leading zeros", () => {
    expect(ymd(new Date(2027, 0, 5))).toBe("2027-01-05");
  });
  it("starts the week on Monday (also for Sunday)", () => {
    expect(ymd(startOfWeek(new Date(2027, 5, 20)))).toBe("2027-06-14"); // Sonntag
    expect(ymd(startOfWeek(new Date(2027, 5, 14)))).toBe("2027-06-14"); // Montag
    expect(ymd(startOfWeek(new Date(2027, 5, 17)))).toBe("2027-06-14"); // Donnerstag
  });
  it("adds days across month borders without mutating the input", () => {
    const d = new Date(2027, 0, 30);
    expect(ymd(addDays(d, 3))).toBe("2027-02-02");
    expect(ymd(d)).toBe("2027-01-30");
  });
  it("formats plain dates as German dd.mm.yyyy independent of timezone", () => {
    expect(fmtDate("2027-03-07")).toBe("07.03.2027");
  });
  it("round-trips local datetime input through ISO", () => {
    expect(toInput(fromInput("2027-06-14T08:30"))).toBe("2027-06-14T08:30");
  });
  it("shows durations and running entries", () => {
    expect(hm(125)).toBe("2:05 h");
    expect(hm(null)).toBe("läuft");
  });
  it("labels a week", () => {
    expect(weekLabel(new Date(2027, 5, 14))).toBe("14.06.2027 – 20.06.2027");
  });
});
