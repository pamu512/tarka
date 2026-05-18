import { NextResponse } from "next/server";
import { getMergedRecentItems } from "@/lib/recent-audit-store";

export async function GET() {
  const items = getMergedRecentItems(Date.now()).slice(0, 50);
  return NextResponse.json({ items }, { headers: { "Cache-Control": "no-store" } });
}
