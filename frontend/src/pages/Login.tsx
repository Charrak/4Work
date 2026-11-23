import { FormEvent, ReactNode, useState } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { get, post } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { Btn, ErrorBox, Field } from "../ui";

function AuthFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="auth">
      <div className="card">
        <img className="logo" src="/logo.png" alt="physio & fit VitalZentrum Eschweiler" />
        <h1 className="center">{title}</h1>
        {children}
      </div>
    </div>
  );
}

export function Login() {
  const { me, login, refresh } = useAuth();
  const nav = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const setup = useLoad(() => get<{ setup_required: boolean }>("/auth/setup-status"), []);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [company, setCompany] = useState("physio & fit VitalZentrum Eschweiler");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me) return <Navigate to={loc.state?.from || "/"} replace />;
  const firstRun = setup.data?.setup_required === true;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      if (firstRun) {
        await post("/auth/register-tenant", { company, name, email, password });
        await refresh();
      } else {
        await login(email, password);
      }
      nav(loc.state?.from || "/", { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally { setBusy(false); }
  };

  return (
    <AuthFrame title={firstRun ? "Ersteinrichtung" : "Anmelden"}>
      {firstRun && <p className="muted">Legen Sie Ihre Firma und den ersten Administrator an. Danach legen Sie Mitarbeiter im Bereich „Verwaltung“ an.</p>}
      <form className="stack" onSubmit={submit}>
        {firstRun && <Field label="Firma"><input value={company} onChange={(e) => setCompany(e.target.value)} required minLength={2} /></Field>}
        {firstRun && <Field label="Ihr Name"><input value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" /></Field>}
        <Field label="E-Mail"><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" /></Field>
        <Field label="Passwort" hint={firstRun ? "Mindestens 10 Zeichen mit Buchstaben und Ziffern" : undefined}>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
            autoComplete={firstRun ? "new-password" : "current-password"} />
        </Field>
        <ErrorBox error={error} />
        <button className="btn primary" style={{ width: "100%" }} disabled={busy || setup.loading}>{busy ? "…" : firstRun ? "Einrichten" : "Anmelden"}</button>
        {!firstRun && <p className="center"><Link to="/passwort-vergessen">Passwort vergessen?</Link></p>}
      </form>
    </AuthFrame>
  );
}

export function ResetRequest() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setError(null);
    try { await post("/auth/password-reset/request", { email }); setDone(true); } catch (err) { setError((err as Error).message); }
  };
  return (
    <AuthFrame title="Passwort zurücksetzen">
      {done ? <div className="alert info">Falls die Adresse bekannt ist, wurde eine E-Mail mit einem Link gesendet (1 Stunde gültig). Ohne E-Mail-Versand hilft Ihnen Ihr Administrator.</div> : (
        <form className="stack" onSubmit={submit}>
          <Field label="E-Mail"><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
          <ErrorBox error={error} />
          <button className="btn primary" style={{ width: "100%" }}>Link anfordern</button>
        </form>
      )}
      <p className="center"><Link to="/login">Zur Anmeldung</Link></p>
    </AuthFrame>
  );
}

export function ResetConfirm() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const toast = useToast();
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setError(null);
    try { await post("/auth/password-reset/confirm", { token, new_password: pw }); setDone(true); toast("Passwort geändert"); } catch (err) { setError((err as Error).message); }
  };
  return (
    <AuthFrame title="Neues Passwort">
      {done ? <p className="center"><Link to="/login">Jetzt anmelden</Link></p> : (
        <form className="stack" onSubmit={submit}>
          <Field label="Neues Passwort" hint="Mindestens 10 Zeichen mit Buchstaben und Ziffern">
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} required autoComplete="new-password" />
          </Field>
          <ErrorBox error={error} />
          <Btn type="submit" kind="primary">Speichern</Btn>
        </form>
      )}
    </AuthFrame>
  );
}
