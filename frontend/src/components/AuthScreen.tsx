"use client";

import { useState } from "react";
import { login, signup, type User } from "@/lib/api";

export default function AuthScreen({ onAuthenticated }: { onAuthenticated: (user: User) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      onAuthenticated(await (mode === "login" ? login : signup)(email, password));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const isLogin = mode === "login";

  return (
    <main className="grid min-h-full place-items-center px-5 py-10">
      <div className="animate-rise flex w-full max-w-md flex-col gap-8">
        <header>
          <p className="text-6xl leading-none font-bold tracking-[-0.04em]">docsqa</p>
          <h1 className="mt-6 text-3xl leading-tight font-light tracking-[-0.02em]">
            문서가 <strong className="font-bold">직접 대답하는</strong> 공간
          </h1>
        </header>

        <form onSubmit={submit} className="flex flex-col gap-3 rounded-[2rem] bg-ink-soft p-6">
          <div className="mb-2 flex gap-1 rounded-full bg-ink p-1" role="tablist">
            {(["login", "signup"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => {
                  setMode(m);
                  setError(null);
                }}
                className={`flex-1 rounded-full py-2 text-sm font-bold transition-colors ${
                  mode === m ? "bg-cream text-ink" : "text-cream-dim hover:text-cream"
                }`}
              >
                {m === "login" ? "로그인" : "회원가입"}
              </button>
            ))}
          </div>

          <label className="flex flex-col gap-1.5 text-sm font-bold">
            이메일
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-full border border-ink-line bg-transparent px-5 py-3 font-light outline-none focus:border-cream"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-sm font-bold">
            비밀번호
            <input
              type="password"
              required
              minLength={8}
              autoComplete={isLogin ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-full border border-ink-line bg-transparent px-5 py-3 font-light outline-none focus:border-cream"
            />
            {!isLogin && <span className="px-2 text-xs font-light text-cream-dim">8자 이상</span>}
          </label>

          {error && <p className="rounded-2xl bg-flame px-4 py-3 text-sm text-cream">{error}</p>}

          <button
            type="submit"
            disabled={submitting}
            className="mt-2 flex h-12 items-center justify-between rounded-full bg-flame pr-2 pl-6 font-bold text-cream transition-opacity disabled:opacity-50"
          >
            {submitting ? "잠시만요…" : isLogin ? "로그인" : "가입하고 시작하기"}
            <span className="grid size-8 place-items-center rounded-full bg-cream text-ink">→</span>
          </button>
        </form>
      </div>
    </main>
  );
}
