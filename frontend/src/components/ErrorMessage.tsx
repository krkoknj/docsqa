export default function ErrorMessage({ children }: { children: React.ReactNode }) {
  return <p className="rounded-2xl bg-flame px-4 py-3 text-sm text-cream">{children}</p>;
}
