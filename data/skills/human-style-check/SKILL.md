---
name: human-style-check
description: Prüft den aktuellen Skripttext auf künstlich klingende Formulierungen (KI-Floskeln), nicht auf Kreativität. Wird geladen, wenn der Nutzer fragt, ob der Text nach KI klingt, ihn auf Stil/Menschlichkeit prüfen lässt, oder um ehrliches Feedback zur Sprache bittet.
---

# Stil-Check: klingt der Text nach KI oder nach einem Menschen?

## Anweisungen für den Agenten

Wenn dieser Skill aktiv ist, prüfe den aktuellen Skripttext auf die folgenden fünf
Muster. Es geht **nicht** darum, den Text kreativer zu machen — nur darum, künstlich
klingende Stellen zu erkennen.

1. **Formelhafte Übergänge/Weisheiten** — z. B. "Am Ende des Tages...", "Es ist
   wichtig zu betonen...", "auf die eine oder andere Weise".
2. **Gefühlswort + Standard-Geste kombiniert** — ein Satz benennt das Gefühl per
   Adjektiv/Adverb UND hängt eine vorgefertigte Geste dran, z. B. "**Nervös** zuckte
   ihr Auge". Das klingt nach Show-don't-tell, ist aber verkleidetes Tell. Besser:
   nur die physische Tatsache beschreiben, ohne Gefühls-Etikett — z. B. "Ihre Augen
   bewegten sich schnell hin und her". Der Hörer/Leser zieht den Schluss selbst.
3. **Austauschbare Sprecherstimmen** — alle Figuren klingen gleich gebildet/
   ausgeglichen, keine eigene Sprachfärbung.
4. **Zu glatte Auflösung** — jeder Konflikt wird sofort sauber besprochen/verstanden,
   keine Reibung, kein Abbruch, keine echte Widerrede.
5. **Gleichförmiger Satzrhythmus** — jeder Satz ähnlich lang/gebaut, keine Fragmente,
   keine Unterbrechungen, wie es echte gesprochene Sprache hätte.

**Verhalten:** Gib **Feedback**, schreibe den Text nicht selbst um. Für jede
Fundstelle: Zitat aus dem Text, welche der fünf Kategorien, ein kurzer
Verbesserungsvorschlag. Wird nichts gefunden, sag das kurz und bestätigend (z. B.
"Klingt schon menschlich, nichts gefunden.") statt gar keine Antwort zu geben.
