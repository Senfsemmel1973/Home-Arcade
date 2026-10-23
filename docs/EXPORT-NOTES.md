# Umfang und Abweichungen

Quellenstand: Home Arcade 2.0.0. Kein fertiges Release, keine frühere Git-Historie.
Die Anwendung wurde aus den finalen eigenen Quellschichten zusammengeführt.
Kein privates `dist/`-Archiv ist Buildvoraussetzung.

Bewusste Unterschiede zum internen vollständigen Build:

- Emulatoren, Firmware, Node und fremde Quellarchive fehlen vollständig.
- MAME-Referenzdaten und individuelle Spieleprüfsummenprofile fehlen. Der eigene
  Metadatengenerator bleibt verfügbar; Standardimport verwendet manuelle Mapperwahl.
- Standard-Verwaltungsname ist `admin`; externe Coverkatalogsuche ist standardmäßig
  deaktiviert. Eigene Cover sind weiterhin möglich.
- Javatari-Quellenlink verweist auf Upstream, statt ein nicht vorhandenes ZIP zu verlinken.
- Versionsanzeige und Cachekennungen sind 2.0.0. Installer-Metadaten kennzeichnen den
  lokalen Selbstaufbau; die Installationsprüfung ist nicht an einen bestimmten
  Testserver gebunden.
- Interne Berichte, historische Entwicklungsverzeichnisse, Betriebs-/Recoverypatches
  und Testausgaben sind nicht enthalten.
- Die entsprechend freigegebenen eigenen Quellen stehen im öffentlichen Export
  unter MIT, Copyright 2026 Harry Knechtel. Frühere interne Lizenzangaben werden
  nicht rückwirkend verändert; Fremdkomponenten behalten ihre Bedingungen.

Der Selbstaufbau wird als separater Veröffentlichungsumfang getestet. Die Abnahme
einer früheren vollständigen internen Installation ist keine automatische Abnahme
dieser veränderten Zusammenstellung. Quelltests ersetzen weder reale Engine- noch
Ubuntu-/Reboot- oder Xbox-Tests.
