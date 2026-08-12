---
name: tag-suggestions
description: Schlägt passende [tags] aus dem festen Vokabular an eindeutig emotionalen/betonten Stellen im Skripttext vor, wo noch keine gesetzt sind. Wird geladen, wenn der Nutzer fragt, welche Tags fehlen, Tags vorschlagen lässt, oder um Emotion/Betonung im Skript markieren bittet.
---

# Tag-Vorschläge für emotionale Skript-Stellen

## Anweisungen für den Agenten

Wenn dieser Skill aktiv ist, ergänze im aktuellen Skripttext `[tags]` an Stellen, die
eine erkennbare Emotion oder Betonung tragen, aber noch keinen Tag haben — nach diesen
festen Regeln:

1. **Nur eindeutige Stellen**: ergänze einen Tag nur dort, wo die Emotion klar aus dem
   Text hervorgeht (explizite Gefühlswörter, Ausrufezeichen, eindeutige
   Regieanweisungen im Text). Im Zweifel lieber **keinen** Tag setzen als einen
   falschen oder übertriebenen.
2. **Nur aus dem bekannten Vokabular**: verwende ausschließlich Tags aus der Liste, die
   dir bereits im System-Prompt mitgeteilt wurde — erfinde niemals neue Tags. Übernimm
   den Tag dabei exakt in dieser Schreibweise, übersetze ihn niemals in die Sprache des
   Skripttextes.
3. **Text bleibt unverändert**: der eigentliche Dialogtext wird wortwörtlich
   beibehalten. Du fügst ausschließlich `[tag]`-Marker ein, du schreibst und kürzt
   nichts um.
4. **Bereits getaggte Zeilen bleiben unangetastet**: Zeilen, die schon ein `[tag]`
   enthalten, werden nicht verändert, überschrieben oder verdoppelt.
5. **Antwortformat bleibt wie immer**: gib den kompletten Skripttext mit den ergänzten
   Tags zurück, im selben Zeilenformat 'Sprecher: Text' — genau wie bei jeder anderen
   Anfrage, damit "In Skript übernehmen" direkt nutzbar bleibt. Keine separate Liste
   oder Erklärung der Änderungen.
