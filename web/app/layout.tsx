import type { Metadata } from "next";
import "./studio.css";
export const metadata: Metadata = {
  title: "ClipHunter Studio",
  description: "Find, review and render stream highlights.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
