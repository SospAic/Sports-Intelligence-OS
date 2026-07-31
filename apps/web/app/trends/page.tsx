import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { TrendsClient } from "./trends-client";

export default async function TrendsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <TrendsClient />;
}
