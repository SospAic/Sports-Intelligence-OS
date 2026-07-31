import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { AccountDetailClient } from "./account-detail-client";

export default async function AccountDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  if (!(await getCurrentUser())) redirect("/login");
  const { id } = await params;
  return <AccountDetailClient id={id} />;
}
