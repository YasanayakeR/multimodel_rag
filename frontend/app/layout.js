import "./global.css";

export const metadata = {
  title: "Multi-Modal RAG Chat",
  description: "Next.js frontend for a FastAPI multi-modal RAG backend",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

