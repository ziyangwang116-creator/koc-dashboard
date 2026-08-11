"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { authApi } from "@/lib/endpoints";
import { ApiError } from "@/lib/api-client";
import { Lock } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!password) {
      setError("请输入团队密码。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await authApi.login(password);
      if (res.data.authenticated) {
        router.replace("/dashboard");
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("登录失败，请稍后重试。");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.wrap}>
      <form onSubmit={handleSubmit} style={styles.card} aria-label="团队密码登录">
        <div style={styles.header}>
          <Lock size={20} color="var(--color-primary)" />
          <h1 style={styles.title}>KOC 数据后台</h1>
        </div>
        <label htmlFor="password" style={styles.label}>
          团队密码
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={styles.input}
        />
        {error && (
          <p role="alert" style={styles.error}>
            {error}
          </p>
        )}
        <button type="submit" disabled={submitting} style={styles.button}>
          {submitting ? "登录中..." : "登录"}
        </button>
      </form>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "var(--color-bg)",
  },
  card: {
    width: 320,
    background: "var(--color-surface)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius)",
    padding: 24,
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  header: { display: "flex", alignItems: "center", gap: 8, marginBottom: 8 },
  title: { fontSize: 16, fontWeight: 600 },
  label: { fontSize: 13, color: "var(--color-text-muted)" },
  input: {
    padding: "8px 10px",
    borderRadius: "var(--radius)",
    border: "1px solid var(--color-border)",
  },
  error: { fontSize: 12.5, color: "var(--color-danger)" },
  button: {
    marginTop: 8,
    padding: "9px 0",
    borderRadius: "var(--radius)",
    border: "none",
    background: "var(--color-primary)",
    color: "#fff",
    fontWeight: 600,
  },
};
