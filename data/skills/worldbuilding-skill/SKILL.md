---
name: worldbuilding-skill
description: Hilft dabei, das Setting eines Hörspiel-/Hörbuchprojekts konsistent auszuarbeiten (Ort, Zeit, Regeln/Magie/Technik, Gesellschaft, wiederkehrende Fakten) und die Ergebnisse strukturiert in AGENTS.md oder einer eigenen Welt-Notiz festzuhalten. Wird geladen, wenn der Nutzer über Setting, Welt, Zeitalter, Orte, Gesellschaft oder Regeln der Welt spricht, oder um Weltaufbau/Worldbuilding bittet.
---

# Worldbuilding

## Anweisungen für den Agenten

1. **Kernfragen zuerst**: Prämisse, Zeit/Ort, eine zentrale Regel (Magie/Technik/Gesellschaftsordnung) — nicht alles auf einmal abfragen.
2. **Kategorie-Checkliste** als Gedächtnisstütze, nur bei Bedarf vertiefen, nicht stur abfragen:
   - Geographie & Umgebung
   - Gesellschaft & Institutionen (Macht, Recht, Wirtschaft)
   - Kultur & Alltag (Bräuche, Werte, Sprache)
   - Regeln/Logik (Magie/Technik: was ist möglich, was kostet was)
   - Geschichte/Zeitachse (was prägt die Gegenwart)
3. **Konsistenz wichtiger als Vollständigkeit**: nicht jede Kategorie muss ausgefüllt sein — Antworten dürfen sich aber nicht widersprechen.
4. **Ergebnis IMMER in einer eigenen Datei festhalten**, nie direkt in AGENTS.md: nutze dafür über das `write_file`-Tool IMMER exakt den Dateinamen `Welt.md`, niemals `worldbuilding.md` oder ähnliche Varianten des Skill-Namens (der Skill-Name ist kein Dateiname). Trage in AGENTS.md stattdessen nur einen kurzen Verweis ein (z. B. "Worldbuilding: siehe `Welt.md`"), damit klar ist, wo die Details stehen.
5. **Bei Widersprüchen** zu bereits Notiertem: nachfragen statt stillschweigend überschreiben.
