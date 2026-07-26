import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ContentsClient } from "./contents-client";
export default async function ContentsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <ContentsClient />;
}
