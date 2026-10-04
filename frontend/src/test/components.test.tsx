import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { EventOut } from "@/api/client";
import { ConfidenceBadge, PriorityBadge, ThreatTier } from "@/components/ui/badges";
import { Markdown } from "@/components/ui/Markdown";
import { EventRow } from "@/features/events/EventRow";
import { duration, money, pct, titleCase } from "@/lib/format";

describe("format helpers", () => {
  it("formats values", () => {
    expect(titleCase("competitive_position")).toBe("Competitive Position");
    expect(pct(0.845)).toBe("85%");
    expect(pct(null)).toBe("—");
    expect(duration(850)).toBe("850 ms");
    expect(duration(12_300)).toBe("12.3 s");
    expect(money(null)).toBe("Custom");
    expect(money("99", "USD", "month")).toMatch(/99.*\/mo$/);
  });
});

describe("badges", () => {
  it("renders priority and confidence", () => {
    render(
      <>
        <PriorityBadge priority="critical" />
        <PriorityBadge priority={null} />
        <ConfidenceBadge level="confirmed" score={0.92} />
        <ThreatTier tier={4} />
      </>,
    );
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText("· 92%")).toBeInTheDocument();
    expect(screen.getByLabelText("Threat tier 4 of 5")).toBeInTheDocument();
  });
});

describe("EventRow", () => {
  const event: EventOut = {
    id: "e1",
    competitor_id: "c1",
    source_id: null,
    title: "Acme raised Growth to $99",
    summary: "",
    category: "pricing",
    key_facts: [],
    priority: "high",
    priority_score: 0.6,
    confidence_level: "likely",
    confidence_score: 0.6,
    status: "new",
    stage: "complete",
    detected_at: new Date().toISOString(),
    is_simulated: false,
    competitor_name: "Acme",
  };

  it("labels simulated events", () => {
    render(
      <MemoryRouter>
        <EventRow event={{ ...event, is_simulated: true }} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Simulated")).toBeInTheDocument();
  });

  it("links to the event detail", () => {
    render(
      <MemoryRouter>
        <EventRow event={event} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link")).toHaveAttribute("href", "/events/e1");
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
  });
});

describe("Markdown", () => {
  it("renders GFM tables and opens external links in a new tab", () => {
    render(<Markdown>{"| Plan | Price |\n|---|---|\n| Growth | $99 |\n\n[src](https://acme.com)"}</Markdown>);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "src" })).toHaveAttribute("target", "_blank");
  });
});
