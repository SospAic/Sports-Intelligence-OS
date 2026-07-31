import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { NewsDetailClient } from "./news-detail-client";
export default async function NewsDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  if (!(await getCurrentUser())) redirect("/login");
  const { id } = await params;
  return <NewsDetailClient id={id} />;
}
