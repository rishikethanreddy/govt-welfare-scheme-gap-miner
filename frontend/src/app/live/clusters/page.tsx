import type { Metadata } from "next";
import { Suspense } from "react";
import ClustersView from "@/components/views/ClustersView";
import { LoadingBlock } from "@/components/ui";

export const metadata: Metadata = { title: "Live · Semantic clusters" };

export default function Page() {
  return (
    <Suspense fallback={<LoadingBlock rows={6} />}>
      <ClustersView scope="live" />
    </Suspense>
  );
}
