# Selbstaufbau und Integration

## 1. Voraussetzungen und Grenzen

Ziel: **Ubuntu 24.04 x86_64, Python 3.12**. Für lokale JavaScript-Tests benötigt man
Node.js im Suchpfad. Für den späteren Serverbau wird die festgelegte Linux-Laufzeit
separat ergänzt. Apache, mod_wsgi, Python und Pillow installiert der Installer mit
`--install-dependencies` aus Ubuntu-Paketquellen.

Keine Emulator-, Firmware- oder Spielebytes gehören in diesen Checkout. Downloads,
entpackte Fremdquellen, Abhängigkeiten und die lokal zusammengesetzte Instanz bleiben
in **anderen Verzeichnissen**. Die folgenden Pfade sind Beispiele, keine echten Hosts.

Die enthaltenen VICE-Coredateien des getesteten Upstreams haben eingebettete
Commodore-System-ROMs. Vor Beschaffung, Nutzung und insbesondere Weitergabe muss
der Anwender die erforderlichen Rechte klären. Ein Upstream-Download oder dieser
Hinweis ist keine Erlaubnis des Rechteinhabers. Ohne geeigneten Core funktioniert
der C64-Player nicht. Dieses Repository behauptet keine geklärte Firmwareweitergabe.

## 2. Exakte externe Komponenten

| Bestandteil | Getesteter Stand | Primärquelle / Lizenz |
|---|---|---|
| Javatari JavaScript | 5.0.4, Commit `f954960ddfbd8b8645de447bc7dc7a1eda066877` | https://github.com/ppeccin/javatari.js — AGPL-3.0, `license.txt` |
| EmulatorJS | npm `@emulatorjs/emulatorjs@4.2.3`, Commit `e150dc0491ae747028919fb82d6598954976ede6` | https://github.com/EmulatorJS/EmulatorJS — GPL-3.0 |
| VICE-Webcore | npm `@emulatorjs/core-vice_x64sc@4.2.3`, VICE 3.9, Commit `5e885db667124eb4b8ed77b476375f8bc3c96c25` | https://github.com/EmulatorJS/vice-libretro — GPL-2.0-or-later; Firmware gesondert |
| Node.js Linux x64 | 24.22.0 | https://nodejs.org/en/download/archive/v24.22.0 — MIT und Drittkomponenten, `LICENSE` |

`dependencies.json` benennt für **jede benötigte externe Zieldatei** Größe und
SHA-256. Es werden weder `latest` noch automatisch andere Core-Builds akzeptiert.
Ein anderer Compiler-/Minifierstand kann trotz gleicher Versionsnummer andere Bytes
liefern. Dann stoppen und die Abhängigkeit prüfen; Prüfsummen nicht blind ändern.

### Javatari

```sh
mkdir -p "$HOME/arcade-input"
cd "$HOME/arcade-input"
git clone https://github.com/ppeccin/javatari.js.git javatari
cd javatari
git checkout --detach f954960ddfbd8b8645de447bc7dc7a1eda066877
npm install
npx grunt
```

Die Ausgabe `release/stable/5.0/embedded/javatari.js` wird als
`web/atari/vendor/javatari.js` benötigt.
Der Collector unten findet Dateien nach Inhalt, unabhängig vom Grunt-Ausgabeordner.
Zum getesteten Bundle gehören die Lizenztexte von Javatari, JSZip und pako. Diese
Rechtstexte liegen bereits unter `web/licenses/`; sie enthalten keinen Emulatorcode.
Der historische Grunt-Build besitzt keine vollständig
festgeschriebene npm-Abhängigkeitsauflösung. Ein bitgleicher Neubau mit heutigen
npm-Abhängigkeiten ist deshalb noch nicht zugesichert. Bei Hashabweichung kann ein
passendes unverändertes Upstream-Bundle verwendet werden, wenn Herkunft und Rechte
geprüft sind; keine private Home-Arcade-Auslieferung ist Voraussetzung.

### Javatari-Diagnose und Lösungsweg

Bei `Missing exact upstream bytes` beziehungsweise `Dependency hash mismatch`:

1. Im Verzeichnis `arcade-input/javatari` mit `git rev-parse HEAD` den oben genannten
   Commit prüfen. Nicht das ältere Java-Projekt `ppeccin/javatari` verwenden.
2. `node --version`, `npm --version` und `npm ls --depth=0` protokollieren.
   Der historische Quellstand legt `grunt-contrib-uglify` auf **2.3.0** fest; andere
   Grunt-Abhängigkeiten sind dort nicht vollständig fixiert. Für diese liegt hier
   kein vollständiger getesteter Lockfile vor. `npm audit fix` oder ein ungezieltes
   Paketupgrade wäre deshalb kein geeigneter Reparaturschritt.
3. Prüfen, ob tatsächlich `release/stable/5.0/embedded/javatari.js` gebaut wurde.
   Nicht die Standalone-HTML, eine andere Releaseversion oder die ungepackten
   Einzelquellen als Bundle einsetzen. Erwarteten Hash anzeigen:

   ```sh
   # Im Home-Arcade-Checkout:
   python3 -c 'import json; print(json.load(open("dependencies.json"))["files"]["web/atari/vendor/javatari.js"]["sha256"])'
   sha256sum "$HOME/arcade-input/javatari/release/stable/5.0/embedded/javatari.js"
   ```

4. Bei einem vorhandenen vertrauenswürdigen Referenzbundle mit `cmp` oder `diff`
   vergleichen. Ein anderer Minifier, Banner oder Zeilenumbruch kann andere Bytes
   erzeugen; das beweist weder einen Defekt noch Funktionsgleichheit. Quellen,
   Buildprotokoll und Abhängigkeitsauflösung getrennt prüfen. Einen erneuten Build
   in einem neuen Arbeitsverzeichnis durchführen, nicht über unbekannte Altdateien.
5. Für den unveränderten Referenzaufbau nur ein überprüftes, bytegleiches Bundle
   verwenden. Ist dieses nicht beschaffbar oder reproduzierbar, bleibt der Collector
   absichtlich beim STOP. Ein geprüfter abweichender Eigenbuild ist ein neuer
   Integrationsstand: Er benötigt eine bewusst dokumentierte neue Referenz in
   `dependencies.json`, ein aktualisiertes `SOURCE-MANIFEST.json` und gezielte
   Tests von Start, Steuerung, Pause und Spielständen. Dafür keine Prüfsummenprüfung
   deaktivieren und keinen unbekannten Download einfach als neue Referenz eintragen.

Beim regulären Export werden Manifest und Hashes durch den Exportmechanismus neu
erzeugt. Wer den öffentlichen Checkout eigenständig verändert, muss seine bewusst
geänderten Dateireferenzen ebenfalls nachvollziehbar aktualisieren. Der unveränderte
Checkout verspricht keinen automatischen Wechsel auf beliebige Ersatzbuilds.

### EmulatorJS und VICE

Nur nach Klärung der Rechte am gewünschten Core:

```sh
cd "$HOME/arcade-input"
mkdir emulatorjs vice
cd emulatorjs
npm pack --ignore-scripts @emulatorjs/emulatorjs@4.2.3
tar -xzf emulatorjs-emulatorjs-4.2.3.tgz
cd ../vice
npm pack --ignore-scripts @emulatorjs/core-vice_x64sc@4.2.3
tar -xzf emulatorjs-core-vice_x64sc-4.2.3.tgz
```

Aus dem Frontend werden die in `dependencies.json` genannten `data/src/`-Dateien,
`data/emulator.css`, Kompressionshelfer und `data/version.json` benötigt. Aus dem
Corepaket werden nur `vice_x64sc-wasm.data`, `vice_x64sc-legacy-wasm.data` und der
zugehörige Bericht übernommen. Ziel ist `web/c64/data/`, einschließlich
`cores/reports/vice_x64sc.json`. Die beiden `.data`-Dateien sind vollständige Archive;
nicht in den Webroot entpacken. Die benötigten GPL-Texte liegen bereits unter
`web/c64/licenses/`. Nipplejs trägt seinen eigenen MIT-Hinweis im Quelltext.

Für einen selbst gebauten anderen Core gelten dessen Buildgrundlagen. Er ist kein
automatisch kompatibler Ersatz für den festgelegten Snapshot; insbesondere
Speicherstände und Eingabe-APIs sind anschließend erneut zu prüfen.

### C64-Diagnose und Lösungsweg

Die Bezugsquellen, npm-Versionen und Zielpfade stehen unmittelbar oben. Zusätzlich
sind sämtliche Einzeldateien in `dependencies.json` aufgeführt. Der Collector sucht
in den entpackten Eingaben nach passenden Inhalten; er übernimmt keine gesamten
npm-Verzeichnisse und lädt keine fehlenden Dateien nach.

| Befund | Prüfung / Maßnahme |
|---|---|
| Collector meldet fehlende Dateien | Beide npm-Pakete müssen in getrennte Verzeichnisse entpackt sein. Mit `find "$HOME/arcade-input" -name '*vice_x64sc*'` die beiden Corearchive und den Bericht suchen. Nicht versehentlich `vice_x64` statt `vice_x64sc` verwenden. |
| Hashabweichung trotz gleicher Version | Auf eine andere Buildausgabe oder veränderte Bytes prüfen. Nicht Thread-/Legacy-/Hauptcore vertauschen. Keine `.data`-Archive entpacken oder modifizieren. Die Abweichung vor Übernahme untersuchen. |
| HTTP 404 oder `EmulatorJS` / `EJS_GameManager` nicht definiert | Browser-Entwicklerwerkzeuge, Netzwerkansicht: alle eingebundenen Skripte unter `/emulator/c64/data/src/` und beide Cores unter `/emulator/c64/data/cores/` prüfen. Ein `200` mit HTML-Fehlerseite ist keine erfolgreiche Skriptauslieferung. |
| Core lädt nicht oder WASM scheitert | Passenden Single-Thread-Core und vollständige Archive prüfen; JavaScript-Konsole und Apache-Fehlerprotokoll lesen. Kein beliebiges aktuelles Frontend mit dem alten Core kombinieren. |
| CDN-Fallback blockiert | Gewollt: Adapter und CSP begrenzen Laufzeitanfragen auf die lokale Origin. Fehlende Dateien lokal ergänzen; nicht einfach Sicherheitsprüfungen abschalten oder CDN-URLs einsetzen. |
| Emulator läuft, Spiel reagiert nicht | Spielfläche fokussieren; Trainer-/Startfragen beantworten; C64-Tastaturmodus und Joystick-Port prüfen; bei Bedarf mit gewähltem Port neu starten. Auf Xbox Edge die Spielsteuerung aktivieren. |
| Alte Speicherstände passen nicht | Identität und Format hängen auch vom Core ab. Andere Builds nicht ungeprüft als kompatibel behandeln; keine Slots überschreiben, bevor ein eigener Teststand geprüft ist. |

Ein Downloadlink ist kein Nachweis einer Firmware-Nutzungserlaubnis. Wenn die Rechte
am gewünschten Core beziehungsweise seiner Systemfirmware nicht geklärt sind, den
C64-Aufbau aussetzen. Die MIT-Lizenz der eigenen Home-Arcade-Quellen erfasst diese
Fremdkomponenten nicht.

### Node.js

```sh
cd "$HOME/arcade-input"
curl -fLO https://nodejs.org/dist/v24.22.0/node-v24.22.0-linux-x64.tar.xz
curl -fLO https://nodejs.org/dist/v24.22.0/SHASUMS256.txt
grep ' node-v24.22.0-linux-x64.tar.xz$' SHASUMS256.txt | sha256sum -c -
tar -xf node-v24.22.0-linux-x64.tar.xz
```

Zusätzlich die signierte Prüfsummenliste anhand der offiziellen
[Node-Verifikationsanleitung](https://github.com/nodejs/release-keys) prüfen.
Benötigt werden `bin/node` als `runtime/bin/node` sowie `LICENSE` als `runtime/LICENSE`.
Die Binärdatei muss eine echte Linux-Datei sein, kein Symlink auf einen wechselnden
System-Node. Der Instanzaufbau prüft ihren exakten Hash.

## 3. Abhängigkeiten zuordnen und lokal bauen

Im Quellencheckout:

```sh
python3 -B tools/check_source.py
python3 -B tools/collect_dependencies.py --input "$HOME/arcade-input" --output "$HOME/arcade-dependencies"
python3 -B tools/build_instance.py --dependencies "$HOME/arcade-dependencies" --output "$HOME/arcade-local-build"
```

Beide Ausgabeordner müssen neu sein. Der Collector schreibt erst nach vollständigem
Hashabgleich; es gibt keinen Netzwerkzugriff und keine pauschale Kopie des Downloads.
Der Builder erstellt ausschließlich einen **lokalen Arbeitsbaum**, kein Archiv und
kein öffentliches Release. Der Quellencheckout bleibt frei von Fremdkomponenten.
Auch dieser lokale Baum ist nicht automatisch zur Weitergabe freigegeben.

Atari-Referenzmetadaten sind bewusst nicht enthalten (`app/atari-profiles.json` ist
leer). Unbekannte ROMs brauchen im Import eine ausdrücklich gewählte unterstützte
Mapperkonfiguration; Dateigröße allein ist kein Nachweis. Wer die automatische
Erkennung benötigt, kann die CC0-Metadaten separat beziehen:

```sh
curl -fL https://raw.githubusercontent.com/mamedev/mame/c993311c3074fa0dc6395e37aa44d7b4adce28ae/hash/a2600.xml -o "$HOME/arcade-input/a2600.xml"
python3 -B tools/build_profiles.py --input "$HOME/arcade-input/a2600.xml" > /tmp/home-arcade-atari-profiles.json
```

Der Generator kontrolliert den XML-Hash. Beim lokalen Instanzaufbau optional
`--atari-profiles /tmp/home-arcade-atari-profiles.json` ergänzen. Der Checkout bleibt
unverändert; nur die lokale Instanz erhält die separat erzeugten Referenzdaten.
Der Standardaufbau benötigt diese Erweiterung nicht. Keine privaten
Spielprüfsummenprofile und kein MAME-Emulatorquelltext werden mitgeliefert.

## 4. Installation auf frischem Ubuntu

Erst nach erfolgreichem lokalem Aufbau. Die Befehle ändern das explizit gewählte
Ubuntu-Ziel; sie sind keine Anweisung, eine bestehende Produktivinstanz zu verwenden.

```sh
sudo install -d -m 755 /opt/home-arcade-source-build
sudo cp -a "$HOME/arcade-local-build/." /opt/home-arcade-source-build/
sudo chown -R root:root /opt/home-arcade-source-build
sudo chmod -R go-w /opt/home-arcade-source-build
cd /opt/home-arcade-source-build
sudo python3 -I -B install.py --expect-host arcade --hostname arcade --network 192.168.1.0/24 --listen-address 192.168.1.50 --login admin --disable-covers
```

`arcade`, Netz und IP durch die tatsächlichen privaten Werte ersetzen. Der erste
Aufruf ist nur Preflight. Erst mit denselben Parametern plus
`--install-dependencies --apply` wird installiert. Das neue Verwaltungspasswort wird
zweimal im Terminal eingegeben, nie in einer Datei oder Kommandozeile abgelegt.
Bei Abbruch nicht blind neu ausführen: Ausgabe und Installer-Backup prüfen.

Der Installer richtet Apache ein und aktiviert/neustartet den Dienst. Oberfläche:
`http://arcade/emulator/`. Erneut `sudo python3 -I -B install.py --expect-host arcade`
aufrufen: erwartet wird `ALREADY_CURRENT` ohne Datenänderung.

Programm: `/opt/home-arcade`; Daten: `/var/lib/home-arcade`; geschützte Konfiguration:
`/etc/home-arcade`. Bibliothek startet leer. `--disable-covers` deaktiviert nur die
externe Katalogsuche; eigene Cover können weiterhin importiert werden. Eine externe
Coverquelle ist standardmäßig nicht konfiguriert. LAN-HTTP ist kein Schutz vor
Mitlesen im lokalen Netz; die Instanz nicht ungeprüft ins Internet freigeben.

Prüfen: Versionsanzeige, geschützter Import, eigener Spieleimport, Emulatorstart,
Controller, Menü, Pause, Vollbild, drei Speicherplätze und Browserneustart.

## 5. Bestehende Installationen und Rückfall

Die Universalquellen enthalten den gezielten Erkennungsweg für den bekannten
Legacy-Stand 1.0.0-rc2 sowie 2.0.0-rc1/2.0.0. Versionskennung allein genügt nicht;
unbekannte Dateien, Pfade oder Hashabweichungen führen zum STOP. Der öffentliche
Selbstaufbau hat einen eigenen Programmbestand und benötigt eine eigene Ubuntu-
Abnahme vor jedem realen Upgrade. Frühere interne Tests sind keine Abnahme dieses
neuen Aufbauwegs. Keine stillschweigende Umgehung von Kompatibilitätsprüfungen.

Vor einem später ausdrücklich genehmigten Upgrade Inventur erstellen:

```sh
sudo python3 -I -B inventory.py --expect-host arcade --output /root/arcade-before.json
sudo python3 -I -B install.py --expect-host arcade --baseline-inventory /root/arcade-before.json
```

Erst nach geprüftem Preflight zusätzlich `--apply`. Der Installer stoppt Apache,
sichert Programm, Daten, Konfiguration und Apache unter
`/var/backups/home-arcade-update-TRANSAKTION`, entpackt das Backup und vergleicht
Dateiinventur und Hashes vor dem Austausch. Kein erfolgreicher Nachweis: kein Upgrade.
Bei Aktivierungsfehlern Programmrollback, keine alten Nutzerdaten über neue Daten.
Manueller Rückfall nur nach Prüfung:

```sh
sudo python3 -I -B install.py --expect-host arcade --rollback /var/backups/home-arcade-update-TRANSAKTION --apply
```

Clean Install sichert den Ausgangszustand unter
`/var/backups/home-arcade-install-before-2.0.0`; es gibt kein automatisches
Paket-/Betriebssystemrollback. Browser-Spielstände liegen origin- und geräteabhängig
im Browser und gehören nicht zum Serverbackup.

## 6. Neustart und Betrieb

Nach der Erstinstallation einmal kontrolliert neu starten und Erreichbarkeit prüfen.
Apache bindet nur an die gewählten privaten Adressen. Wenn eine konfigurierte Adresse
beim Boot noch fehlt, kann der Start scheitern. Diagnose:
`sudo journalctl -u apache2 -b --no-pager -n 40` und `ip address`.
Die rechtzeitige Adressbereitstellung muss zur Netzkonfiguration passen; dieser Export
installiert keinen standortspezifischen Boot-Patch. Internetzugang wird für den
Spielbetrieb nicht benötigt. Abhängigkeiten/apt benötigen ihn nur beim Aufbau.

## 7. Bekannter Teststand

Der Quellenexport wurde lokal auf Aufbau, Dateizuordnung, Hashprüfungen und mit
synthetischen Anwendungsprüfungen getestet. Ein vollständiger frischer Ubuntu-
Selbstaufbau ausschließlich aus diesem Export, einschließlich erneutem Download/
Neubau aller Fremdkomponenten, echter Emulatorausführung und Reboot, wurde bisher
nicht abschließend getestet. Diese Anleitung richtet sich an Entwickler; die
verbleibenden Integrationsfragen sind keine zugesicherte Ein-Klick-Installation.
