/** Cinematic background shared by the chat and the sign-in screen. */
export function Backdrop() {
  return (
    <div className="qc-backdrop" aria-hidden="true">
      <span className="qc-aurora qc-aurora--a" />
      <span className="qc-aurora qc-aurora--b" />
      <span className="qc-aurora qc-aurora--c" />
      <span className="qc-grid" />
      <span className="qc-grain" />
      <span className="qc-vignette" />
    </div>
  );
}
