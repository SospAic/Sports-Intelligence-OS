import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { EditorialClient } from "./editorial-client";

export default async function EditorialPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <EditorialClient />;
}
