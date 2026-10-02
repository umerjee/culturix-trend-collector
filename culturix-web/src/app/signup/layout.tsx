// Sign-in for existing accounts. Not a public landing page, so it is kept out of search results.
export const metadata = { title: "Sign in", robots: { index: false, follow: false } };

export default function SignupLayout({ children }: { children: React.ReactNode }) {
  return children;
}
