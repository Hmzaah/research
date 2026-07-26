import { notFound } from "next/navigation";
import type { Metadata } from "next";
import {
  getDocContent,
  isDirectory,
  getDirectoryEntries,
  getDocsTree,
  getBreadcrumbs,
} from "@/lib/docs-content";
import { extractTocItems } from "@/lib/toc";
import { getHomeData } from "@/lib/home-feed";
import { DocsLayout } from "@/components/docs/docs-layout";
import { DirectoryIndex } from "@/components/docs/directory-index";
import { HomeView } from "@/components/home/home-view";
import { MarkdownRenderer } from "@/components/markdown/markdown-renderer";
import { ReportHeader } from "@/components/report/report-header";
import { Toc } from "@/components/report/toc";
import { MobileToc } from "@/components/report/mobile-toc";
import { Breadcrumbs } from "@/components/docs/breadcrumbs";
import { NotesPanel } from "@/components/notes/notes-panel";
import { NotesProvider } from "@/components/notes/notes-provider";
import { AnnotatedArticle } from "@/components/notes/annotated-article";

// Render docs pages on demand instead of statically pre-generating every one.
// The number of Markdown docs grows without bound, and pre-rendering all of
// them (HTML + RSC + JSON, duplicated again inside the standalone bundle) made
// the Amplify build artifact exceed its size limit. On-demand rendering keeps
// the artifact size independent of the document count. Pages are still cached
// after first render via ISR (see `revalidate`).
export const dynamicParams = true;
export const revalidate = 3600;

export function generateStaticParams(): { slug?: string[] }[] {
  return [];
}

type PageProps = {
  params: Promise<{ slug?: string[] }>;
};

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;

  if (!slug || slug.length === 0) {
    return { title: "Docs | Research Viewer" };
  }

  const doc = getDocContent(slug);
  if (doc) {
    return { title: `${doc.title} | Research Viewer` };
  }

  return { title: `${slug[slug.length - 1]} | Research Viewer` };
}

export default async function DocsPage({ params }: PageProps) {
  const { slug } = await params;
  const tree = getDocsTree();
  const currentSlug = slug ?? [];
  const breadcrumbs = getBreadcrumbs(currentSlug);
  const currentPath = currentSlug.length > 0 ? `/research/${currentSlug.join("/")}` : "/research";

  // Top page: show the home view (recent reports + search + active domains)
  // instead of a raw directory listing.
  if (currentSlug.length === 0) {
    const homeData = getHomeData();

    return (
      <DocsLayout tree={tree} currentPath={currentPath}>
        <Breadcrumbs items={breadcrumbs} />
        <HomeView data={homeData} />
      </DocsLayout>
    );
  }

  // Directory page: show listing
  if (isDirectory(currentSlug)) {
    const entries = getDirectoryEntries(currentSlug);

    return (
      <DocsLayout tree={tree} currentPath={currentPath}>
        <Breadcrumbs items={breadcrumbs} />
        <DirectoryIndex entries={entries} parentSlug={currentSlug} />
      </DocsLayout>
    );
  }

  // Markdown page: render content
  const doc = getDocContent(currentSlug);
  if (!doc) {
    notFound();
  }

  const tocItems = extractTocItems(doc.content);
  const hasMetadata = Object.keys(doc.metadata).length > 0;

  return (
    <DocsLayout
      tree={tree}
      currentPath={currentPath}
      toc={<Toc items={tocItems} className="sticky top-20" />}
      mobileToc={<MobileToc items={tocItems} />}
    >
      <Breadcrumbs items={breadcrumbs} />
      {hasMetadata && <ReportHeader title={doc.title} metadata={doc.metadata} />}
      <NotesProvider slug={currentSlug.join("/")}>
        <AnnotatedArticle>
          <MarkdownRenderer
            content={doc.content}
            basePath={currentSlug.slice(0, -1).join("/")}
          />
        </AnnotatedArticle>
        <NotesPanel />
      </NotesProvider>
    </DocsLayout>
  );
}
