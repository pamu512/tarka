import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { DurableBoardSourceBadge } from "./DurableBoardSourceBadge";

describe("DurableBoardSourceBadge", () => {
  it("labels durable source and empty-tenant callout", () => {
    const html = renderToStaticMarkup(
      <DurableBoardSourceBadge source="durable" recordCount={0} />,
    );
    expect(html).toContain("Durable records");
    expect(html).toContain("empty board, not demo SHA aggregates");
  });

  it("labels durable+automation without empty callout when records exist", () => {
    const html = renderToStaticMarkup(
      <DurableBoardSourceBadge source="durable+automation" recordCount={3} />,
    );
    expect(html).toContain("Durable · automation");
    expect(html).not.toContain("empty board");
  });

  it("labels mock source", () => {
    const html = renderToStaticMarkup(<DurableBoardSourceBadge source="mock" recordCount={4} />);
    expect(html).toContain("Demo / mock");
  });
});
