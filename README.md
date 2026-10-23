# Home Arcade 2.0.0 – Source Code / Developer Setup

Dieses Repository enthält den selbst entwickelten Home-Arcade-Anwendungsrahmen,
**keine vollständige, sofort lauffähige Distribution**. Es richtet sich an Entwickler
und technisch interessierte Anwender, die das Projekt selbst aufbauen und
gegebenenfalls anpassen möchten.

Home Arcade verwaltet eine eigene Spielebibliothek im privaten LAN. Enthalten sind
Backend, Import und Verwaltung, Weboberfläche, Controllersteuerung, Player-Adapter,
Browser-Spielstände mit drei Slots, Screenshot-Vorschau und Export sowie die eigenen
Build- und Universal-Installerquellen.

**Dies ist kein sofort installierbares Release.** Emulatoren, Firmware, Node.js,
Spiele-ROMs, Cover und andere Nutzerdaten sind nicht enthalten. Die Player werden
erst mit separat beschafften, passenden Laufzeitkomponenten funktionsfähig.

## Einstieg

1. [Setup und Integration](SETUP-INTEGRATION.md): feste Abhängigkeiten beschaffen,
   prüfen, lokal zusammenbauen und auf Ubuntu 24.04 x86_64 installieren.
2. [Bedienung und Controller](docs/CONTROLS.md).
3. [Lizenz und externe Komponenten](docs/LICENSING.md).
4. [Unterschiede und Grenzen dieses Quellenexports](docs/EXPORT-NOTES.md).

Der Build braucht keine privaten Releasearchive und lädt nichts automatisch nach.
Alle Laufzeitdateien werden anschließend lokal vom eigenen Server ausgeliefert.

## Bekannte Einschränkungen / Known Issues

- **Javatari:** Ein Neubau kann wegen unterschiedlicher npm-Abhängigkeiten von den
  getesteten Referenzdateien abweichen. Dann schlagen die Prüfsummenprüfungen fehl.
  Den dokumentierten Upstream-Stand und die dort festgelegten Abhängigkeitsversionen
  verwenden, Ausgaben vergleichen und Abweichungen untersuchen. Prüfsummen nicht
  einfach deaktivieren oder ungeprüft ersetzen. Siehe
  [Javatari-Diagnose und Lösungsweg](SETUP-INTEGRATION.md#javatari-diagnose-und-lösungsweg).
- **C64 / EmulatorJS / VICE:** Der benötigte Core ist nicht enthalten. EmulatorJS und
  VICE müssen separat beschafft und integriert werden. Enthaltene Systemfirmware
  kann gesonderten urheberrechtlichen Bedingungen unterliegen. Anwender prüfen die
  Nutzungsrechte der ergänzten Komponenten und Spiele eigenständig. Externe
  Downloads sind nicht automatisch rechtlich freigegeben. Siehe
  [C64-Diagnose und Lösungsweg](SETUP-INTEGRATION.md#c64-diagnose-und-lösungsweg).
- **Teststand:** Ein vollständiger frischer Ubuntu-Selbstaufbau ausschließlich aus
  diesem öffentlichen Export ist bisher nicht abschließend getestet. Lokale
  Quellen- und Buildtests sind keine vollständige Installationsabnahme.

## Aufbau

| Pfad | Inhalt |
|---|---|
| `app/`, `schema/` | Python-Backend und JavaScript-Katalogvalidierung |
| `web/` | Bibliothek, Import, Controller, eigene Atari-/C64-Adapter |
| `installer/` | Universal-Einstieg, Clean Install, Upgrade, Inventur, Rückfall |
| `tools/` | Quellenprüfung, Abhängigkeitszuordnung, lokaler Instanzaufbau |
| `tests/` | Synthetische Import-/Format-, Profil- und Speicherprüfungen |
| `dependencies.json` | Größen und SHA-256 der extern benötigten Dateien |
| `SOURCE-MANIFEST.json` | Vollständige Dateiliste und Prüfsummen dieses Exports |

`tests/baseline.json` enthält ausschließlich erfundene Testeinträge und wiederholte
Platzhalterprüfsummen. Diese Datei wird nicht als Spielebibliothek installiert.
`empty-catalog.json` ist die tatsächlich verwendete leere Startbibliothek.

## Quellen testen

Mit Python 3.12, Pillow und Node.js im Suchpfad, ohne Emulatoren oder Spiele:

```sh
python3 -B tools/check_source.py
python3 -B -m unittest discover -s tests -p 'test_*.py'
node tests/profiles.cjs
node tests/store.cjs
```

Die Python-Importtests verwenden Dateirechte und Prozessverhalten von Linux.
Windows allein ersetzt keine Ubuntu-Installationsabnahme. Tests erzeugen kurzlebige
synthetische Dateien, niemals mitgelieferte kommerzielle Spiele.

## Lizenz

Die eigenen, vom Rechteinhaber entsprechend freigegebenen Home-Arcade-Quellen und
Dokumentation stehen unter der [MIT-Lizenz](LICENSE), Copyright 2026 Harry Knechtel.
Das ist keine MIT-Freigabe für externe Emulatoren, Firmware, Node.js, Spiele oder
deren Rechtstexte. Diese behalten ihre eigenen Bedingungen. Siehe
[Lizenzübersicht und Adapterprüfung](docs/LICENSING.md).
