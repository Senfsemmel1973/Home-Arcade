# Eigene Quellen und externe Lizenzen

Dieser Export enthält keine Emulatorimplementierungen, Firmware oder Laufzeitbinaries.
Die Root-Datei `LICENSE` ist die vollständige MIT-Lizenz mit Copyright
`2026 Harry Knechtel`. Sie gilt für die eigenen, vom Rechteinhaber entsprechend
freigegebenen Home-Arcade-Quellen und Dokumentation in diesem Export. Der Betreiber
hat diese MIT-Veröffentlichung ausdrücklich freigegeben. Frühere interne
Lizenzkennzeichnungen beziehungsweise Auslieferungen werden nicht rückwirkend
geändert.

Die zusätzlichen Rechtstexte unter `licenses/`, `web/licenses/` und
`web/c64/licenses/` dokumentieren die Bedingungen separat integrierter
Fremdkomponenten. Diese Texte und die darin genannten fremden Werke werden durch
die Root-Lizenz nicht auf MIT umgestellt. Auch die Zusammenstellung mit später
ergänztem GPL-/AGPL-Code kann Pflichten für die integrierte Ausgabe auslösen; ein
MIT-lizenzierter Adapter hebt diese nicht auf.

Kurze Prüfung der Adapter: `web/atari/player.js`, `web/c64/player.js`,
`web/state-adapters.js`, `web/input-router.js` und `web/player-host.js` enthalten
Integrationslogik für die Fremd-APIs. Der C64-Adapter ersetzt zur Laufzeit einzelne
Prototypmethoden (Gamepad-Routing, Updateprüfung, Dateisystem, lokale Downloads).
Er enthält keine vollständige Emulatorimplementierung. Geprüft wurden außerdem
`web/state-store.js` und der Manifestadapter. Die Sichtprüfung und ein ergänzender
Vergleich gegen die vorhandenen Javatari-/EmulatorJS-Quellen haben keine übernommenen
Emulator-Codeblöcke identifiziert. Es wurde dabei keine identische Folge von 30
lexikalischen Tokens in den untersuchten Dateien gefunden. Das ist eine gezielte
Plausibilitätsprüfung, kein vollständiger Nachweis der unabhängigen Urheberschaft
jeder Zeile und keine Aussage, dass reine API-Integration alle Lizenzfragen löst.

Die früheren eigenen AGPL-Kennzeichnungen des Manifest-/Atari-Adapters sowie die
eigenen GPL-/AGPL-Angaben in den Integrationshinweisen wurden ausschließlich im
öffentlichen Export entsprechend der Rechteinhaberfreigabe auf MIT angepasst.
Es wurde kein festgestellter Fremdcode umlizenziert. Nach dieser Prüfung liegt kein
konkreter identifizierter Fremdcodeabschnitt vor, der die MIT-Freigabe der eigenen
Quellen blockiert. Bei späterem Fund bleiben dessen Herkunft und Lizenz gesondert
zu klären, statt ihn automatisch als MIT zu behandeln.

| Extern ergänzt | Bedingungen / Quelle |
|---|---|
| Javatari 5.0.4 | AGPL-3.0, Copyright Paulo Augusto Peccin; JSZip-/pako-Hinweise erhalten. https://github.com/ppeccin/javatari.js |
| EmulatorJS 4.2.3 | GPL-3.0, Copyright-/Bibliothekshinweise erhalten; nipplejs MIT. https://github.com/EmulatorJS/EmulatorJS/blob/e150dc0491ae747028919fb82d6598954976ede6/LICENSE |
| VICE 3.9 | GPL-2.0-or-later für Software; Commodore-System-ROMs ausdrücklich getrennt. https://raw.githubusercontent.com/EmulatorJS/vice-libretro/5e885db667124eb4b8ed77b476375f8bc3c96c25/vice/README |
| Node.js | MIT und Lizenzen gebündelter Bibliotheken. https://github.com/nodejs/node/blob/v24.22.0/LICENSE |

Wer ergänzte Komponenten weitergibt, muss die jeweiligen Lizenzpflichten einschließlich
Copyright, vollständiger korrespondierender Quellen und erforderlicher Buildgrundlagen
selbst erfüllen. AGPL enthält außerdem Anforderungen für geänderte Fassungen mit
Netzwerkinteraktion. Die getrennte Beschaffung ist kein Ersatz für Lizenzbeachtung.
Lizenztexte: https://www.gnu.org/licenses/agpl-3.0.html und
https://www.gnu.org/licenses/gpl-3.0.html .

Bei den bekannten VICE-Webcores ist Firmware eingebettet. Eine Erlaubnis zu deren
Weitergabe wird von diesem Projekt nicht erteilt oder behauptet. Upstream-Verfügbarkeit
beweist keine Freigabe durch Firmware-Rechteinhaber. Dasselbe gilt unabhängig davon
für ergänzte Spiele und Cover. Anwender klären die Rechte ihrer Instanz selbst;
dieser Hinweis beseitigt keine eigenen Pflichten der Herausgeber.
