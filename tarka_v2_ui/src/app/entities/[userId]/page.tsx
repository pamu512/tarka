import { EntityProfileView } from "@/components/entity-profile/EntityProfileView";

type PageProps = {
  params: Promise<{ userId: string }>;
};

export default async function EntityProfilePage({ params }: PageProps) {
  const { userId: raw } = await params;
  const userId = decodeURIComponent(raw || "").trim() || "unknown";
  return <EntityProfileView userId={userId} />;
}
