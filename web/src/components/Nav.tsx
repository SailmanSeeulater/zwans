"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Sessions", match: (path: string) => path === "/" || path.startsWith("/session") },
  { href: "/evals/", label: "Evals", match: (path: string) => path.startsWith("/evals") },
];

export function Nav() {
  const path = usePathname();
  return (
    <nav className="nav">
      <Link href="/" className="nav-brand">
        Zwans
      </Link>
      {LINKS.map((link) => (
        <Link key={link.href} href={link.href} aria-current={link.match(path) ? "page" : undefined}>
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
