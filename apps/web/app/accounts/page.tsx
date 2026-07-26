import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { AccountsClient } from "./accounts-client";

export default async function AccountsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <AccountsClient />;
}
