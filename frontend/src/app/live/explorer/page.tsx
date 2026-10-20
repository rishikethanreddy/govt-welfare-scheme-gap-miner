import type { Metadata } from "next";
import { Suspense } from "react";
import ExplorerView from "@/components/views/ExplorerView";
import { LoadingBlock } from "@/components/ui";

export const metadata: Metadata = { title: "Live · Records" };

export default function Page() {
  return (
    <Suspense fallback={<LoadingBlock rows={6} />}>
      <ExplorerView scope="live" />
    </Suspense>
  );
}
