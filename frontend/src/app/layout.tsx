import type { Metadata } from "next";
import { Bricolage_Grotesque, Noto_Sans_KR } from "next/font/google";
import "./globals.css";

// Bricolage for Latin glyphs; Hangul falls back to Noto Sans KR.
const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
});

const notoSansKr = Noto_Sans_KR({
  variable: "--font-noto-kr",
  subsets: ["latin"],
  weight: ["300", "400", "700"],
});

export const metadata: Metadata = {
  title: "DocsQA",
  description: "문서 기반 RAG 질의응답 에이전트",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={`${bricolage.variable} ${notoSansKr.variable} h-full antialiased`}>
      <body className="flex h-full flex-col font-sans">{children}</body>
    </html>
  );
}
