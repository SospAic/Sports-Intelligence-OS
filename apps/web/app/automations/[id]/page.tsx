import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { AutomationEditor } from "../automation-editor";
export default async function AutomationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  if (!(await getCurrentUser())) redirect("/login");
  const { id } = await params;
  return <AutomationEditor id={id} />;
}
