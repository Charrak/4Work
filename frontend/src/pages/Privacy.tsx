import { get } from "../api";
import { useLoad } from "../hooks";
import type { Company } from "../types";
import { Card, Spinner } from "../ui";

export default function Privacy() {
  const c = useLoad(() => get<Company>("/auth/company"), []);
  if (c.loading && !c.data) return <Spinner />;
  return (
    <>
      <h1>Datenschutz</h1>
      <Card title="Verantwortlicher">
        <p><b>{c.data?.company_name}</b></p>
        <p>{c.data?.privacy_contact ? c.data.privacy_contact : "Ansprechpartner für Datenschutz: bitte bei der Leitung erfragen."}</p>
      </Card>
      <Card title="Welche Daten werden verarbeitet?">
        <ul>
          <li>Stammdaten: Name, E-Mail, Telefon (optional), Abteilung, Rolle.</li>
          <li>Arbeitsorganisation: Dienstplan, Tauschanfragen, Urlaub und Abwesenheiten, Arbeitszeiten (Stempelungen).</li>
          <li>Dokumente: z. B. Arbeitsvertrag, Krankschreibungen (Gesundheitsdaten – nur für Sie und die Leitung sichtbar).</li>
          <li>Team-Chat und technische Protokolle (Anmeldungen, Änderungen durch Administratoren).</li>
        </ul>
        <p>Kolleginnen und Kollegen sehen bei Abwesenheiten nur „abwesend“, niemals den Grund (z. B. Krankheit).</p>
      </Card>
      <Card title="Ihre Rechte">
        <p>Sie haben das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung und Datenübertragbarkeit. Unter „Profil“ können Sie Ihre Daten exportieren. Löschwünsche richten Sie bitte an die Leitung; personenbezogene Daten werden dann anonymisiert, soweit keine Aufbewahrungspflichten entgegenstehen.</p>
      </Card>
    </>
  );
}
