export function App() {
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 24, maxWidth: 720 }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>x-social-trader</h1>
        {/* KILL-04: permanent kill-switch button lands in phase 6. */}
        <span
          title="Placeholder — permanent kill switch arrives in KILL-04 (phase 6)"
          style={{
            padding: "6px 12px",
            borderRadius: 6,
            background: "#cccccc",
            color: "#555",
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: 0.5,
          }}
        >
          KILL SWITCH (phase 6)
        </span>
      </header>
      <p>
        Scaffolding UI only (phase 1). Real dashboard arrives in UI-02 (phase 12).
      </p>
      <ul>
        <li>Health backend : <code>GET /api/health</code> (proxied vers <code>api:8000</code>).</li>
        <li>Invariants : voir <code>CLAUDE.md</code> §2.</li>
      </ul>
    </main>
  );
}
