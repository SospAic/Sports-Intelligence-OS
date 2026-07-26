import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { NewsClient } from "./news-client";
export default async function NewsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <NewsClient />;
}
