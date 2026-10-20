import type { Metadata } from "next";
import { Suspense } from "react";
import ClustersView from "@/components/views/ClustersView";
import { LoadingBlock } from "@/components/ui";

export const metadata: Metadata = { title: "Dataset · Semantic clusters" };

export default function Page() {
  return (
    <Suspense fallback={<LoadingBlock rows={6} />}>
      <ClustersView scope="dataset" />
    </Suspense>
  );
}
