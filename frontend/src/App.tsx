import { useEffect, useState } from "react";

type KillSwitchStatus = { active: boolean; source: string };

async function fetchStatus(): Promise<KillSwitchStatus> {
  const res = await fetch("/api/kill-switch");
  if (!res.ok) throw new Error(`kill-switch status ${res.status}`);
  return res.json();
}

async function activateKillSwitch(actor: string): Promise<KillSwitchStatus> {
  const res = await fetch("/api/kill-switch", {
    method: "POST",
    headers: { "X-Actor": actor, "X-Reason": "manual activation from UI" },
  });
  if (!res.ok) throw new Error(`activate failed: ${res.status}`);
  return res.json();
}

export function App() {
  const [status, setStatus] = useState<KillSwitchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await fetchStatus();
        if (!cancelled) setStatus(s);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    };
    void tick();
    const id = window.setInterval(tick, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const onClickKill = async () => {
    if (status?.active) return;
    const ok = window.confirm(
      "Activate the kill switch? All open orders will be cancelled and new submissions blocked.",
    );
    if (!ok) return;
    setBusy(true);
    try {
      const s = await activateKillSwitch("ui-user");
      setStatus(s);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const active = status?.active ?? false;

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 24, maxWidth: 720 }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>x-social-trader</h1>
        <button
          onClick={onClickKill}
          disabled={busy || active}
          title={active ? "Kill switch active — manual deactivation required" : "Click to halt all trading"}
          style={{
            padding: "10px 18px",
            borderRadius: 6,
            border: "none",
            cursor: active ? "not-allowed" : "pointer",
            background: active ? "#b00020" : "#e53935",
            color: "#fff",
            fontWeight: 700,
            letterSpacing: 0.5,
            animation: active ? "xst-blink 1s step-end infinite" : undefined,
          }}
        >
          {active ? "KILL SWITCH ACTIVE" : "KILL SWITCH"}
        </button>
      </header>

      <p style={{ marginTop: 16, color: "#555" }}>
        Status: <code>{status ? (status.active ? "active" : "inactive") : "…loading"}</code>
        {status && <> · source: <code>{status.source}</code></>}
      </p>

      {error && (
        <p style={{ color: "#b00020" }}>
          Error: <code>{error}</code>
        </p>
      )}

      <ul>
        <li>Dashboard + journal arrivent en UI-02 (phase 12).</li>
        <li>Bouton kill-switch actif (KILL-04) : POST <code>/api/kill-switch</code>.</li>
        <li>Invariants : voir <code>CLAUDE.md</code> §2.</li>
      </ul>

      <style>{`@keyframes xst-blink { 50% { opacity: 0.55; } }`}</style>
    </main>
  );
}
