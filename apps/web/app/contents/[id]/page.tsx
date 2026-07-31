import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ContentDetailClient } from "./content-detail-client";
export default async function ContentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  if (!(await getCurrentUser())) redirect("/login");
  const { id } = await params;
  return <ContentDetailClient id={id} />;
}
