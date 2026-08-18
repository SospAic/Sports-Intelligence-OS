import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { PublicationsClient } from "./publications-client";

export default async function PublicationsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <PublicationsClient />;
}
